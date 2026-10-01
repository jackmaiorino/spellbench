"""Re-verify a published tournament directory from its files alone.

Dispatch is on the manifest's schema: ``spellbench-tournament/v2`` runs go to
:func:`validate_v2_run`, anything else to the frozen legacy verifier.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from .. import digests
from ..errors import ValidationError
from ..messages import PROTOCOL_MINOR, EngineIdentity, EngineProfile, Rules
from ..run_secret import RunSecret
from . import leaderboard, legacy_v1, registry, store
from .config import TournamentConfig, TournamentError
from .ledger import LedgerRow, LedgerSeat, parse_ledger
from .manifest import (
    FAIRNESS_LABEL,
    MANIFEST_KEYS,
    TOURNAMENT_SCHEMA_V2,
    CommitmentProof,
    EngineFile,
    commitment_record,
    isolation_record,
    is_rated,
    manifest_body,
    run_status,
    validator_record,
)
from .schedule import GameContext, schedule
from .throughput import Allocation


def validate_tournament_dir(directory: Path) -> list[str]:
    """Re-verify a published tournament; returns the failures (empty means OK).

    A v2 manifest (schema ``spellbench-tournament/v2``) goes to the v2
    verifier; anything else goes to the frozen legacy verifier.
    """
    try:
        schema = store.read_json(directory / store.MANIFEST_NAME).get("schema")
    except store.StoreError:
        schema = None  # no readable manifest: either verifier reports that itself
    if schema == TOURNAMENT_SCHEMA_V2:
        return validate_v2_run(directory)
    return legacy_v1.validate_v1_run(directory)


def _arena_version() -> str:
    """The running package version, read at call time (a later release bumps it)."""
    from .. import __version__

    return __version__


def _read_for_comparison(path: Path, failures: list[str]) -> bytes | None:
    """A published file's bytes, or None after recording a failure that names it."""
    try:
        return path.read_bytes()
    except OSError:
        failures.append(f"cannot read {path.name} to compare it with a recomputation")
        return None


def _violations(rows: Sequence[LedgerRow]) -> list[dict[str, Any]]:
    """The violations the ledger implies: one per row halted for ``host_validator:<rule>`` (spec 11.3)."""
    violations = []
    for row in rows:
        if row.reason.startswith("host_validator:"):
            violations.append(
                {
                    "game_index": row.game_index,
                    "game_id": row.game_id,
                    "rule": row.reason.split(":", 1)[1],
                    "detail": None if row.adjudication is None else row.adjudication.detail,
                }
            )
    return violations


def _scheduled_decks(context: GameContext, row: LedgerRow, deck_ids: dict[str, str]) -> bool:
    """The row's decks as scheduled: a decklist deck's deck_id recomputed; one catalog id, one deck_id."""
    for spec, deck in zip(context.decks, row.decks):
        if spec.catalog_id is not None:
            if deck.catalog_id != spec.catalog_id or deck_ids.setdefault(spec.catalog_id, deck.deck_id) != deck.deck_id:
                return False
            continue
        if deck.catalog_id is not None or deck.name != spec.name:
            return False
        assert spec.decklist is not None
        if deck.deck_id != digests.deck_id([item.to_json() for item in spec.decklist]):
            return False
    return True


def _schedule_failures(
    config: TournamentConfig,
    by_name: Mapping[str, registry.RegistryEntry],
    contexts: Sequence[GameContext],
    rows: Sequence[LedgerRow],
) -> list[str]:
    """Differences between the ledger and the prefix of the schedule it must be (spec 11.6)."""
    if len(rows) > len(contexts):
        return [f"the ledger has {len(rows)} games but the schedule has {len(contexts)}"]
    failures = []
    deck_ids: dict[str, str] = {}  # catalog id -> the deck_id every row with it must share
    for context, row in zip(contexts, rows):
        seats = tuple(
            LedgerSeat(seat=seat, bot_id=by_name[spec.name].bot_id, name=spec.name, version=spec.version)
            for seat, spec in context.seat_specs
        )
        scheduled = (context.game_index, context.game_id, context.matchup_index, context.pair_index, context.pair_slot)
        recorded = (row.game_index, row.game_id, row.matchup_index, row.pair_index, row.pair_slot)
        if (
            recorded != scheduled
            or row.format != config.format
            or row.seats != seats
            or not _scheduled_decks(context, row, deck_ids)
        ):
            failures.append(f"ledger row {row.game_index} ({row.game_id}) does not match the schedule")
    return failures


def _information_rules_failures(info_rules: Any, profile: EngineProfile) -> list[str]:
    """The information rules against the recorded engine profile (spec 12.2, 14)."""
    if not isinstance(info_rules, dict):
        return ["information_rules is not an object"]
    failures = []
    if info_rules.get("fairness_label") != FAIRNESS_LABEL:
        failures.append(f"information_rules.fairness_label must be {FAIRNESS_LABEL!r}")
    try:
        rules = Rules.from_json(info_rules["rules"], "information_rules.rules")
    except (KeyError, TypeError, ValidationError) as exc:
        return [*failures, f"information_rules.rules: {exc}"]
    if info_rules.get("observation") != dict(profile.observation) or info_rules.get("engine_defaults") != dict(
        profile.engine_defaults
    ):
        failures.append("information_rules.observation and .engine_defaults must equal the engine profile's")
    audited: dict[str, Any] = {}
    recorded = info_rules.get("native_id_extensions")
    if isinstance(recorded, list):
        audited = {item.get("name"): item.get("audit") for item in recorded if isinstance(item, dict)}
    enabled = {decl.name for decl in profile.extensions if decl.native_ids} & set(rules.extensions)
    if set(audited) != enabled:
        failures.append("information_rules.native_id_extensions must be exactly the enabled native-id extensions")
    for name in sorted(enabled):
        if type(audited.get(name)) is not str or not audited[name]:
            failures.append(f"information_rules: native-id extension {name!r} has no audit")
    return failures


def validate_v2_run(directory: Path) -> list[str]:
    """Re-verify a published v2 tournament; returns a list of failures (empty = OK).

    Checks (fail closed), each failure one line: the manifest's keys; the
    arena version (a run made by another version gets the single v1-style
    message, and nothing more); the files list (``COMMITMENT.json``, then the
    data files) and every digest; that the config, registry and ledger parse
    as v2; the revealed run secret against ``secrets.commitment`` and against
    ``COMMITMENT.json`` with this run's benchmark and label (spec 11.6,
    R3-30); the ledger as a prefix of ``schedule(config, run_secret)``; the
    validator verdict re-derived from the rows (spec 11.3); the run's status
    (R3-13) and rated flag (Decision 3, R3-7); the isolation record (R3-9);
    the information rules against the engine profile (spec 12.2); every row's
    engine provenance; and byte-exact recomputations of ``leaderboard.json``,
    ``LEADERBOARD.md`` and the manifest body itself.
    """
    failures: list[str] = []
    if not store.is_published(directory):
        return [f"{directory} has no manifest.json (not a published tournament)"]
    try:
        document = store.read_json(directory / store.MANIFEST_NAME, schema=TOURNAMENT_SCHEMA_V2)
        store.require_keys(document, MANIFEST_KEYS, "manifest")
    except (store.StoreError, ValidationError) as exc:
        return [f"manifest: {exc}"]
    tournament = document["tournament"]
    made_by = tournament.get("arena_version") if isinstance(tournament, dict) else None
    arena_version = _arena_version()
    if made_by != arena_version:
        shown = made_by if type(made_by) is str and made_by.isprintable() else repr(made_by)
        return [
            f"this run was made by spellbench arena {shown}; this is {arena_version}: "
            f"rerun the benchmark, or validate with arena {shown}"
        ]
    files = document["files"]
    listed = [entry.get("path") for entry in files if isinstance(entry, dict)] if isinstance(files, list) else None
    expected_files = [store.COMMITMENT_NAME, *store.DATA_FILE_NAMES]
    if listed != expected_files:
        failures.append(f"manifest files must list exactly {expected_files}")
    failures.extend(store.verify_file_digests(directory, document))
    try:
        # Everything comes from the directory itself: bot ids from the registry
        # (a checkpoint is never re-hashed), the rest re-derived.
        config = TournamentConfig.from_json(store.read_json(directory / store.CONFIG_NAME, schema=store.CONFIG_SCHEMA))
        entries = registry.read_registry(directory / store.REGISTRY_NAME)
        rows = parse_ledger(store.read_jsonl(directory / store.LEDGER_NAME, schema=store.LEDGER_SCHEMA))
    except (store.StoreError, ValidationError, TournamentError) as exc:
        return [*failures, f"the v2 artifacts do not parse: {exc}"]
    by_name = {entry.name: entry for entry in entries}
    if sorted(by_name) != sorted(spec.name for spec in config.bots) or len(entries) != len(config.bots):
        return [*failures, "registry.json does not hold exactly the configured bots"]
    try:
        # The secrets and the commitment (spec 11.6, Decision 9; R3-30).
        secrets = document["secrets"]
        run_block = document["run"]
        run_secret = RunSecret.from_hex(secrets["run_secret"])
        if run_secret.commitment() != secrets["commitment"]:
            failures.append("the revealed run_secret does not hash to the recorded commitment")
        proof_value = secrets["commitment_proof"]
        commitment_proof = None if proof_value is None else CommitmentProof.from_json(proof_value)
        expected_commitment = commitment_record(
            run_secret=run_secret, benchmark_id=run_block["benchmark_id"], run_label=run_block["label"]
        )
        if store.read_json(directory / store.COMMITMENT_NAME) != expected_commitment:
            failures.append("COMMITMENT.json does not hold this run's commitment, benchmark_id and run_label (R3-30)")
        # The ledger is a prefix of the schedule (a complete run: all of it).
        contexts = schedule(config, run_secret)
        failures.extend(_schedule_failures(config, by_name, contexts, rows))
        # The validator verdict re-derived from the rows (spec 11.3).
        violations = _violations(rows)
        validator = validator_record(rows, violations)
        if document["validator"] != validator:
            failures.append("the validator block does not match the rows and their violations")
        # The run's status (R3-13) and rated flag (Decision 3, R3-7) from the same inputs.
        allocation = Allocation.from_json(document["allocation"])
        engine_files = [EngineFile.from_json(item) for item in document["engine_files"]]
        status = run_status(scheduled=len(contexts), rows=len(rows), violations=len(violations))
        if run_block["status"] != status:
            failures.append(f"run.status must be {status!r} for these rows and violations (R3-13)")
        rated = is_rated(
            status=status,
            verdict=validator["verdict"],
            commitment_proof=commitment_proof,
            allocation=allocation,
            engine_files=engine_files,
        )
        if run_block["rated"] != rated:
            failures.append(f"run.rated must be {rated} for this allocation and these engine files (R3-7)")
        # The isolation record (R3-9) and the information rules (spec 12.2).
        if document["isolation"] != isolation_record(config):
            failures.append("isolation does not match isolation_record(config) (R3-9)")
        engine = EngineIdentity.from_json(document["engine"], "manifest.engine")
        profile = EngineProfile.from_json(document["engine_profile"], "manifest.engine_profile")
        info_rules = document["information_rules"]
        failures.extend(_information_rules_failures(info_rules, profile))
        if any(row.engine != engine.provenance().to_json() for row in rows):
            failures.append("ledger engine provenance does not match manifest.engine")
        # The leaderboard, byte for byte.
        board, markdown = leaderboard.build_leaderboard(
            rows,
            entries,
            anchor_bot_id=by_name[config.rating_anchor].bot_id,
            base_seed=config.stats_seed,
            bootstrap_replicates=config.bootstrap_replicates,
            format=config.format,
            schema=leaderboard.LEADERBOARD_SCHEMA_V2,
        )
        expected_json = store.canonical_bytes(board) + b"\n"
        actual_json = _read_for_comparison(directory / store.LEADERBOARD_JSON_NAME, failures)
        if actual_json is not None and actual_json != expected_json:
            failures.append("leaderboard.json does not match a recomputation from matches.jsonl")
        actual_md = _read_for_comparison(directory / store.LEADERBOARD_MD_NAME, failures)
        if actual_md is not None and actual_md != markdown.encode("utf-8"):
            failures.append("LEADERBOARD.md does not match a recomputation from matches.jsonl")
        # The manifest body itself, rebuilt from the same pieces.
        expected = manifest_body(
            config=config,
            entries=[by_name[spec.name] for spec in config.bots],
            anchor_bot_id=by_name[config.rating_anchor].bot_id,
            engine=engine,
            profile=profile,
            protocol_minor=PROTOCOL_MINOR,
            info_rules=info_rules,
            rows=rows,
            violations=violations,
            scheduled=len(contexts),
            leaderboard_status=board["status"],
            status=status,
            benchmark_id=run_block["benchmark_id"],
            run_label=run_block["label"],
            run_secret=run_secret,
            commitment_proof=commitment_proof,
            allocation=allocation,
            engine_files=engine_files,
        )
        for key in MANIFEST_KEYS:
            if key != "files" and document[key] != expected[key]:
                failures.append(f"manifest {key} does not match the tournament data")
    except (KeyError, TypeError, ValueError, ValidationError, store.StoreError, TournamentError) as exc:
        failures.append(f"recomputation failed: {exc}")
    return failures
