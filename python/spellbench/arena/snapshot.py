"""Immutable reference-panel snapshots. Source runs retain their commitments and ledgers.

Only whole, compatible matchup blocks are selected. Pair indices are assigned locally
for the rating fit, never written back into a source ledger.
"""
from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import leaderboard, registry, store, validity
from .config import BASE_FORM, EXPORT_FORM, BotSpec, Ladder, TournamentConfig, TournamentError, ladder_pairs
from .ledger import LedgerRow, parse_ledger
from .manifest import EngineFile
from ..run_secret import RunSecret

SCHEMA = "spellbench-snapshot/v1"
# A snapshot that holds blocks of both forms of a ladder with export blocks: schema v1 plus one object,
# ``export_blocks`` (the export form's contract, engine facts and matchups). The top level stays the base form's,
# so a snapshot without an export-form block is written exactly as before, schema id included.
SCHEMA_TWO_FORMS = "spellbench-snapshot/v2"
SCHEMAS = (SCHEMA, SCHEMA_TWO_FORMS)
_FACT_KEYS = ("protocol", "engine", "engine_profile", "information_rules", "engine_files")
FILES = (store.CONFIG_NAME, store.REGISTRY_NAME, store.LEADERBOARD_JSON_NAME, store.LEADERBOARD_MD_NAME)
CAVEAT = (
    "Reference-panel rating: entrants are compared through shared local opponents. Unplayed head-to-head "
    "matchups are not measured; matchup-specific strengths can differ from the ranking. Compatible earlier "
    "evaluations are reused, so this is a dated model measurement. Elo and its interval can change when the "
    "combined results are refitted without replaying earlier games."
)
LADDER_CAVEAT = (
    "Ladder rating: the references (rungs) play the rungs nearest them in rating and each entrant plays the "
    "rungs named for it, so ratings connect through overlapping matchups. Unplayed head-to-head matchups are "
    "not measured; matchup-specific strengths can differ from the ranking. Compatible earlier evaluations are "
    "reused, so this is a dated model measurement. Elo and its interval can change when the combined results "
    "are refitted without replaying earlier games."
)


def caveat(config: TournamentConfig) -> str:
    return LADDER_CAVEAT if config.ladder is not None else CAVEAT


class SnapshotError(ValueError):
    pass


def files_identity(files: Sequence[EngineFile]) -> str:
    return store.sha256_hex(store.canonical_bytes([file.to_json() for file in files]))


def checked_label(label: Any) -> str:
    if type(label) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:-[1-9][0-9]*)?", label):
        raise SnapshotError("source and snapshot labels must be dated run names")
    datetime.date.fromisoformat(label[:10])
    return label


def bot_inputs(spec: BotSpec, config: TournamentConfig) -> dict[str, Any]:
    """What a block's player must share with the current roster entry: its arena entry without the registry
    metadata, and its effective resources (spec 11.4) where they differ from ``config``'s board block, which the
    contract compares. A bot declaring the board block plays exactly as one inheriting it."""
    doc = spec.to_json()
    for key in ("training_style_tags", "registered_at"):
        doc.pop(key)
    doc.pop("resources", None)
    if config.bot_resources(spec) != config.resources:
        doc["resources"] = config.bot_resources(spec).to_json()
    return doc


def contract(config: TournamentConfig) -> dict[str, Any]:
    """The evaluation conditions a run's blocks were played under, compared whole. ``config`` is one form: a run's
    config, or a board's config as one of its forms (:func:`form_contracts`)."""
    if config.export_blocks is not None:
        raise SnapshotError("a board with export blocks has one contract for each form")
    if not config.opponent_panel or config.evaluation_engine_identity is None:
        raise SnapshotError("a reference-panel snapshot needs fingerprinted inputs; run bench prepare first")
    by_name = {bot.name: bot for bot in config.bots}
    if any(bot.evaluation_identity is None for bot in config.bots):
        raise SnapshotError("every entrant needs an evaluation_identity; run bench prepare first")
    doc = config.to_json()
    keys = ("format", "engine", "deck_pool", "decks", "pairs_per_matchup", "rules", "extensions",
            "native_id_audits", "time_control", "limits", "resources", "rating_anchor",
            "evaluation_version", "evaluation_engine_identity", "evaluation_engine_inputs",
            "deck_pairing",  # written only for all_pairs, so mirror boards keep their contract
            "validity")  # written only for a board that names a validity unit, likewise
    conditions = {key: doc[key] for key in keys if key in doc}
    if config.ladder is not None:
        # A ladder block is one matchup under these conditions; select_blocks matches both players' inputs. The
        # rungs, band and entrant lists only schedule matchups, so adding a rung or an entrant reuses every block.
        return {**conditions, "schedule": "ladder"}
    return {**conditions, "references": {name: bot_inputs(by_name[name], config)
                                         for name in sorted(config.opponent_panel)}}


def form_contracts(config: TournamentConfig) -> dict[str, dict[str, Any] | None]:
    """The contract of each form of ``config``'s blocks: the base form alone, or the base and export forms of a
    ladder with export blocks. A run supplies the block of a matchup only when its own contract equals the
    contract of that matchup's form (``config.form_of``), so an export-form run never supplies a block without
    an export bot, and a base-form run never supplies a block with one. The export form is None until
    ``bench prepare`` has fingerprinted its engine: no run matches it yet."""
    contracts: dict[str, dict[str, Any] | None] = {BASE_FORM: contract(config.as_form(BASE_FORM))}
    if config.export_blocks is not None:
        export = config.as_form(EXPORT_FORM)
        contracts[EXPORT_FORM] = None if export.evaluation_engine_identity is None else contract(export)
    return contracts


def _forms_of(source_config: TournamentConfig, expected: Mapping[str, dict[str, Any] | None]) -> set[str]:
    """The forms whose contract a run's own contract equals (none for an incompatible or unreadable run)."""
    try:
        terms = contract(source_config)
    except SnapshotError:
        return set()
    return {form for form, wanted in expected.items() if wanted is not None and terms == wanted}


def required_matchups(config: TournamentConfig) -> tuple[tuple[str, str], ...]:
    names = sorted(bot.name for bot in config.bots)
    if config.ladder is not None:
        scheduled = ladder_pairs(config.opponent_panel, config.ladder)
        return tuple((a, b) for i, a in enumerate(names) for b in names[i + 1:] if frozenset((a, b)) in scheduled)
    panel = set(config.opponent_panel)
    return tuple((a, b) for i, a in enumerate(names) for b in names[i + 1:] if a in panel or b in panel)


def without_entrants(config: TournamentConfig, names: tuple[str, ...]) -> TournamentConfig:
    """The same evaluation without the named roster entries."""
    if not names:
        return config
    export = config.export_blocks
    if export is not None:  # export blocks without a bot left are no export blocks: the base form alone remains
        kept = tuple(name for name in export.bots if name not in names)
        export = replace(export, bots=kept) if kept else None
    left = replace(config, bots=tuple(bot for bot in config.bots if bot.name not in names),
                   matchups=None if config.matchups is None else
                   tuple(pair for pair in config.matchups if not set(pair) & set(names)),
                   ladder=None if config.ladder is None else Ladder(config.ladder.band,
                       {name: rungs for name, rungs in config.ladder.entrants.items() if name not in names}),
                   export_blocks=export)
    return TournamentConfig.from_json(left.to_json())


@dataclass(frozen=True)
class Source:
    path: Path
    config: TournamentConfig
    manifest: dict[str, Any]
    entries: tuple[registry.RegistryEntry, ...]
    rows: tuple[LedgerRow, ...]
    manifest_sha256: str

    def scheduled(self, pair: tuple[str, str]) -> list[Any]:
        """The games this run scheduled for the matchup ``pair`` (sorted names), from its own schedule."""
        from .schedule import schedule
        contexts = schedule(self.config, RunSecret.from_hex(self.manifest["secrets"]["run_secret"]))
        return [context for context in contexts
                if tuple(sorted(spec.name for _, spec in context.seat_specs)) == pair]

    def blocks(self) -> dict[tuple[str, str], tuple[LedgerRow, ...]]:
        groups: dict[tuple[str, str], list[LedgerRow]] = {}
        for row in self.rows:
            key = tuple(sorted(seat.name for seat in row.seats))
            if key[0] != key[1]:
                groups.setdefault(key, []).append(row)
        return {key: tuple(rows) for key, rows in groups.items()
                if len(rows) == 2 * self.config.pairs_per_matchup
                and len({(row.pair_index, row.pair_slot) for row in rows}) == len(rows)}


def read_source(path: Path) -> Source:
    from .validate import validate_v2_run
    checked_label(path.name)
    if path.is_symlink():
        raise SnapshotError(f"source {path.name} is a symbolic link")
    failures = validate_v2_run(path)
    if failures:
        raise SnapshotError(f"source {path.name}: " + "; ".join(failures))
    manifest = store.read_json(path / store.MANIFEST_NAME)
    config = TournamentConfig.from_json(store.read_json(path / store.CONFIG_NAME))
    if manifest["run"]["status"] != "complete":
        raise SnapshotError(f"source {path.name} is not a complete run")
    if manifest["run"]["label"] != path.name:
        raise SnapshotError(f"source {path.name} does not match its recorded run label")
    if config.evaluation_engine_identity != files_identity(
        [EngineFile.from_json(file) for file in manifest["engine_files"]]
    ):
        raise SnapshotError(f"source {path.name} has incompatible engine fingerprints")
    return Source(path, config, manifest, registry.read_registry(path / store.REGISTRY_NAME),
                  parse_ledger(store.read_jsonl(path / store.LEDGER_NAME)),
                  store.sha256_hex((path / store.MANIFEST_NAME).read_bytes()))


def _run_order(name: str) -> tuple[str, int]:
    """A run name's place in time: its date, then its suffix (the first run of a day is 1)."""
    return name[:10], int(name[11:] or "1")


def select_blocks(config: TournamentConfig, sources: Sequence[Source], *, rated_only: bool = True,
                  barred: Mapping[tuple[str, str], str] | None = None) -> dict[tuple[str, str], Source]:
    """Latest compatible whole block per matchup; outcomes never influence the selection.

    ``barred`` maps a matchup to the committed run that played it under this evaluation and failed the board's
    validity unit: a block of that matchup from a later run is never selected, so nothing stands in for a failed
    evaluation."""
    expected = form_contracts(config)
    current = {bot.name: bot for bot in config.bots}
    wanted = set(required_matchups(config))
    selected = {}
    for source in sorted(sources, key=lambda s: _run_order(s.path.name)):
        if rated_only and source.manifest["run"]["rated"] is not True:
            continue
        if validity.verdict(source.manifest.get(validity.MANIFEST_KEY)) == "fail":
            continue  # a run that failed its board's validity unit is never measured, rated or not
        forms = _forms_of(source.config, expected)
        if not forms:
            continue
        by_name = {bot.name: bot for bot in source.config.bots}
        for pair in wanted & source.blocks().keys():
            if config.form_of(pair) not in forms:
                continue  # a run supplies only the blocks of its own form
            if barred and pair in barred and _run_order(source.path.name) > _run_order(barred[pair]):
                continue
            if all(bot_inputs(by_name[name], source.config) == bot_inputs(current[name], config) for name in pair):
                selected[pair] = source
    return selected


def _committed_attempts(run_dirs: Sequence[Path]) -> list[tuple[str, TournamentConfig, dict[str, Any], bool]]:
    """Each committed run of a board with a validity unit, oldest first: its name, config, snapshot contract and
    whether it failed the unit. Runs without a validity record (boards that name no unit), unrated runs and runs
    whose files cannot be read as a fingerprinted config are left out."""
    attempts = []
    for run_dir in sorted(run_dirs, key=lambda path: _run_order(path.name)):
        try:
            manifest = store.read_json(run_dir / store.MANIFEST_NAME)
            if not isinstance(manifest, dict) or validity.MANIFEST_KEY not in manifest:
                continue
            secrets = manifest.get("secrets")
            if not isinstance(secrets, dict) or secrets.get("commitment_proof") is None:
                continue
            config = TournamentConfig.from_json(store.read_json(run_dir / store.CONFIG_NAME))
            terms = contract(config)
        except (store.StoreError, SnapshotError, TournamentError, ValueError, TypeError, KeyError):
            continue  # not a readable, fingerprinted config: it binds nothing, and the validator reports it
        attempts.append((run_dir.name, config, terms, validity.verdict(manifest[validity.MANIFEST_KEY]) == "fail"))
    return attempts


def _played(config: TournamentConfig) -> dict[tuple[str, str], tuple[Any, Any]]:
    """Each matchup a run scheduled (its listed matchups, or the round robin; no self-play) with both players'
    inputs."""
    return {tuple(sorted((first.name, second.name))): tuple(
                bot_inputs(spec, config) for spec in sorted((first, second), key=lambda spec: spec.name))
            for first, second in config.scheduled_pairs() if first.name != second.name}


def failed_attempts(run_dirs: Sequence[Path], desired: TournamentConfig) -> dict[tuple[str, str], str]:
    """Each matchup that a committed run among ``run_dirs`` scheduled under ``desired``'s evaluation conditions,
    with the same two players, and that failed the board's validity unit: the matchup (sorted names) and the
    earliest such run.

    Such a run stays published and excluded. Its matchups are not played again under the same evaluation, and
    no later run's block of such a matchup is ever selected, so a later attempt cannot stand in for a failed one;
    a new evaluation (another ``evaluation_version``, engine or bot) is a reviewed change of the definition.
    Unrated runs are never rated, so they bind nothing here. A board without a validity unit has none. Only the
    bots ``desired`` holds are compared, so a roster entry that is not scheduled needs no fingerprint.
    """
    if desired.validity is None:
        return {}
    expected = form_contracts(desired)
    current = {bot.name: bot_inputs(bot, desired) for bot in desired.bots}
    found: dict[tuple[str, str], str] = {}
    for name, config, terms, failed in _committed_attempts(run_dirs):
        forms = {form for form, wanted in expected.items() if wanted is not None and terms == wanted}
        if not failed or not forms:
            continue
        for pair, inputs in _played(config).items():
            if (desired.form_of(pair) in forms and all(player in current for player in pair)
                    and inputs == tuple(current[player] for player in pair)):
                found.setdefault(pair, name)  # oldest first
    return found


def replaying_runs(run_dirs: Sequence[Path]) -> dict[str, str]:
    """Each committed run that scheduled a matchup which an earlier committed run had played under the same
    evaluation conditions, with the same two players, and failed: its name and the reason it is excluded.

    ``bench commit`` and ``bench run`` refuse such a run, so it should not exist; if it does (two commitments made
    before either played, say), it is excluded like the failed run itself, whatever it scored, and so are the
    snapshots that cite it. Nothing stands in for a failed evaluation."""
    attempts = _committed_attempts(run_dirs)
    replays: dict[str, str] = {}
    for name, config, terms, _ in attempts:
        for earlier, failed_config, failed_terms, failed in attempts:
            if not failed or failed_terms != terms or _run_order(earlier) >= _run_order(name):
                continue
            before = _played(failed_config)
            again = sorted(pair for pair, inputs in _played(config).items() if before.get(pair) == inputs)
            if again:
                replays[name] = (f"plays {' vs '.join(again[0])} again, which run {earlier} played under the same "
                                 "evaluation and failed the board's validity unit; nothing stands in for a failed "
                                 "evaluation")
                break
    return replays


def dropped_ladder_blocks(config: TournamentConfig, sources: Sequence[Source]) -> list[tuple[str, str]]:
    """Rated rung-versus-rung blocks, compatible with ``config``, that its ladder no longer schedules.

    Reordering or inserting rungs can move played pairs out of the band; their results would silently leave the
    fit. Entrant blocks may change with placement, so only rung pairs count. Removing a rung from the panel
    takes its rung blocks with it by design: that is a new rung set, decided in the definition's review.
    """
    if config.ladder is None:
        return []
    expected = form_contracts(config)
    current = {bot.name: bot for bot in config.bots}
    rungs = set(config.opponent_panel)
    wanted = set(required_matchups(config))
    dropped = set()
    for source in sources:
        if source.manifest["run"]["rated"] is not True:
            continue
        forms = _forms_of(source.config, expected)
        if not forms:
            continue
        by_name = {bot.name: bot for bot in source.config.bots}
        for pair in source.blocks().keys() - wanted:
            if config.form_of(pair) in forms and set(pair) <= rungs and all(bot_inputs(by_name[name], source.config) == bot_inputs(current[name], config)
                                          for name in pair):
                dropped.add(pair)
    return sorted(dropped)


def materialize(config: TournamentConfig, chosen: dict[tuple[str, str], Source], *, benchmark_id: str,
                label: str, rated_only: bool = True, pending: Sequence[str] = ()
                ) -> tuple[dict[str, Any], list[registry.RegistryEntry], dict[str, Any], str]:
    pending = list(pending)
    if (len(set(pending)) != len(pending) or any(type(name) is not str or not name for name in pending)
            or set(pending) & {bot.name for bot in config.bots}):
        raise SnapshotError("pending entrants must be distinct names outside the snapshot roster")
    wanted = set(required_matchups(config))
    if chosen.keys() - wanted:
        raise SnapshotError("snapshot contains matchups outside the reference panel")
    missing = sorted(wanted - chosen.keys())
    if missing:
        raise SnapshotError("missing compatible panel matchups: " + ", ".join(f"{a} vs {b}" for a, b in missing))
    expected = form_contracts(config)
    rows = []
    entries_by_name = {}
    specs = {bot.name: bot for bot in config.bots}
    receipts: dict[str, dict[str, Any]] = {}
    sources = {}
    next_pair = 0
    facts: dict[str, dict[str, Any]] = {}  # each form's engine facts, shared by every source run of that form
    parts = []  # each selected block's run, scheduled games and ledger, for the board's validity unit
    for pair in sorted(chosen):
        source = chosen[pair]
        form = config.form_of(pair)
        if source.manifest["run"]["benchmark_id"] != benchmark_id:
            raise SnapshotError(f"source {source.path.name} belongs to another benchmark")
        if form not in _forms_of(source.config, expected):
            raise SnapshotError(f"source {source.path.name} has incompatible evaluation conditions")
        by_name = {bot.name: bot for bot in source.config.bots}
        if any(bot_inputs(by_name[name], source.config) != bot_inputs(specs[name], config) for name in pair):
            raise SnapshotError(f"source {source.path.name} has incompatible entrant inputs")
        if rated_only and not source.manifest["run"]["rated"]:
            raise SnapshotError(f"source {source.path.name} is not rated")
        if validity.verdict(source.manifest.get(validity.MANIFEST_KEY)) == "fail":
            raise SnapshotError(f"source {source.path.name} failed its board's validity unit")
        source_facts = {key: source.manifest[key] for key in _FACT_KEYS}
        source_facts["resolved_decks"] = sorted(
            {store.canonical_bytes(deck.to_json()) for row in source.rows for deck in row.decks})
        source_facts["resolved_decks"] = [json.loads(item) for item in source_facts["resolved_decks"]]
        if facts.setdefault(form, source_facts) != source_facts:
            raise SnapshotError("source runs disagree on engine, deck domain, profile or information rules")
        sources[source.path.name] = source
        receipt = receipts.setdefault(source.path.name, {"run": source.path.name,
            "manifest_sha256": source.manifest_sha256, "matchups": []})
        receipt["matchups"].append(list(pair))
        block = source.blocks().get(pair)
        if block is None:
            raise SnapshotError(f"source {source.path.name} lacks a complete {pair} matchup")
        if config.validity is not None:
            parts.append((source.path.name, source.scheduled(pair), source.rows))
        # The raw files stay intact. Give each source pair its own identity inside the temporary fit ledger.
        local_pairs = {index: next_pair + i for i, index in enumerate(sorted({row.pair_index for row in block}))}
        next_pair += len(local_pairs)
        rows.extend(replace(row, pair_index=local_pairs[row.pair_index]) for row in block)
        for entry in source.entries:
            if entry.name in pair:
                previous = entries_by_name.get(entry.name)
                if previous is not None and previous.bot_id != entry.bot_id:
                    raise SnapshotError(f"sources disagree on {entry.name!r}'s identity")
                spec = specs[entry.name]
                entries_by_name[entry.name] = replace(entry, training_style_tags=spec.training_style_tags,
                                                    registered_at=spec.registered_at)
    entries = [entries_by_name[bot.name] for bot in config.bots]
    if BASE_FORM not in facts:
        raise SnapshotError("a snapshot needs at least one block of the base form")
    export_pairs = sorted(pair for pair in chosen if config.form_of(pair) == EXPORT_FORM)
    if export_pairs and any(facts[EXPORT_FORM][key] != facts[BASE_FORM][key] for key in ("protocol", "resolved_decks")):
        raise SnapshotError("the two forms' source runs disagree on the protocol or the deck domain")
    # Each source passed the unit by itself; the sample this rating is fitted from must pass it too.
    record = validity.evaluate_composition(config, parts)
    if record is not None and record["verdict"] == "fail":
        raise SnapshotError("the composed results fail the board's validity unit: " + "; ".join(record["failures"]))
    document, _ = leaderboard.build_leaderboard(rows, entries,
        anchor_bot_id=entries_by_name[config.rating_anchor].bot_id, base_seed=config.stats_seed,
        bootstrap_replicates=config.bootstrap_replicates, format=config.format, schema=store.LEADERBOARD_SCHEMA,
        deck_slices=config.deck_slices)
    if document["status"] != "ok" or any(not row["rated"] for row in document["rows"]):
        raise SnapshotError("panel results do not connect every entrant to the rating anchor")
    document["evaluation"] = {"mode": "reference_panel" if config.ladder is None else "ladder",
        "version": config.evaluation_version,
        "opponents": list(config.opponent_panel), "sources": sorted(sources), "caveat": caveat(config),
        "observed_matchups": len(document["matchups"]), "possible_matchups": len(entries) * (len(entries) - 1) // 2}
    if config.ladder is not None:
        document["evaluation"]["band"] = config.ladder.band
    document["notes"] = [*document["notes"], caveat(config)]
    if export_pairs:
        # Two evaluation versions in one fit: say which blocks were played under which, and with what.
        export = config.export_blocks
        assert export is not None
        document["evaluation"]["export_blocks"] = {"version": export.evaluation_version, "bots": sorted(export.bots),
            "extensions": list(export.extensions), "matchups": len(export_pairs)}
        document["notes"].append(
            f"Evaluation versions by block: the {len(export_pairs)} blocks of {', '.join(sorted(export.bots))} were "
            f"played under {export.evaluation_version} (extensions: {', '.join(export.extensions)}); the other "
            f"{len(chosen) - len(export_pairs)} blocks under {config.evaluation_version} "
            f"(extensions: {', '.join(config.extensions)}).")
    if pending:
        # Listed, not rated: these roster entries have no compatible panel block yet.
        document["evaluation"]["pending"] = sorted(pending)
        document["notes"].append("Pending, no panel results yet: " + ", ".join(sorted(pending)))
    manifest = {"schema": SCHEMA_TWO_FORMS if export_pairs else SCHEMA, **facts[BASE_FORM],
        "contract": expected[BASE_FORM],
        # The export form's own contract and engine facts, and the matchups played under it. Written only for a
        # snapshot that holds such a block, so every other snapshot keeps its bytes.
        **({"export_blocks": {"contract": expected[EXPORT_FORM],
                              **{key: facts[EXPORT_FORM][key] for key in _FACT_KEYS if key != "protocol"},
                              "matchups": [list(pair) for pair in export_pairs]}} if export_pairs else {}),
        "sources": [receipts[name] for name in sorted(receipts)],
        "allow_unrated": not rated_only,
        **({"pending": sorted(pending)} if pending else {}),
        # Written only for a board that names a validity unit, so earlier snapshots keep their bytes.
        **({validity.MANIFEST_KEY: record} if record is not None else {}),
        "run": {"benchmark_id": benchmark_id, "label": checked_label(label), "status": "complete",
                "rated": rated_only and all(source.manifest["run"]["rated"] for source in sources.values())},
        "validator": {"verdict": "pass", "decisions_checked": sum(row.decisions_checked for row in rows),
                      "violations": []},
        "isolation": {"self_reported": any(source.manifest["isolation"]["self_reported"] for source in sources.values())},
        "games": document["games"], "leaderboard_status": document["status"]}
    return manifest, entries, document, leaderboard.render_markdown(document)


def write_snapshot(directory: Path, config: TournamentConfig, chosen: dict[tuple[str, str], Source], *,
                   benchmark_id: str, rated_only: bool = True, pending: Sequence[str] = ()) -> Path:
    body, entries, board, markdown = materialize(config, chosen, benchmark_id=benchmark_id,
                                                label=directory.name, rated_only=rated_only, pending=pending)
    store.prepare_tournament_dir(directory)
    store.write_json_atomic(directory / store.CONFIG_NAME, config.to_json())
    registry.write_registry(directory / store.REGISTRY_NAME, entries)
    store.write_json_atomic(directory / store.LEADERBOARD_JSON_NAME, board)
    store.write_bytes_atomic(directory / store.LEADERBOARD_MD_NAME, markdown.encode("utf-8"))
    body["files"] = [store.file_entry(directory / name, name) for name in FILES]
    store.write_json_atomic(directory / store.MANIFEST_NAME, body)  # publication boundary, last
    return directory


def source_directory(directory: Path, label: str) -> Path:
    checked_label(label)
    exported = directory / "sources" / label
    return exported if exported.exists() else directory.parent.parent / "runs" / label


def validate_snapshot(directory: Path) -> list[str]:
    try:
        manifest = store.read_json(directory / store.MANIFEST_NAME)
        if manifest.get("schema") not in SCHEMAS:
            raise SnapshotError("not a snapshot manifest")
        if [file["path"] for file in manifest["files"]] != list(FILES):
            raise SnapshotError("snapshot must hash exactly its config, registry and leaderboard files")
        for name in (store.MANIFEST_NAME, *FILES):
            if not (directory / name).is_file() or (directory / name).is_symlink():
                raise SnapshotError(f"{name} is not a regular snapshot file")
        failures = store.verify_file_digests(directory, manifest)
        if failures:
            return failures
        config = TournamentConfig.from_json(store.read_json(directory / store.CONFIG_NAME))
        chosen = {}
        seen_sources = set()
        for receipt in manifest["sources"]:
            store.require_keys(receipt, ("run", "manifest_sha256", "matchups"), "snapshot source")
            label = checked_label(receipt["run"])
            if label in seen_sources:
                raise SnapshotError("duplicate source run")
            seen_sources.add(label)
            source = read_source(source_directory(directory, label))
            if source.manifest_sha256 != receipt["manifest_sha256"]:
                raise SnapshotError(f"source {label} manifest digest changed")
            for pair in receipt["matchups"]:
                if not isinstance(pair, list) or len(pair) != 2 or any(type(n) is not str for n in pair):
                    raise SnapshotError("invalid snapshot matchup")
                key = tuple(pair)
                if key not in required_matchups(config) or key in chosen:
                    raise SnapshotError("unexpected or duplicate snapshot matchup")
                chosen[key] = source
        body, entries, board, markdown = materialize(config, chosen,
            benchmark_id=manifest["run"]["benchmark_id"], label=manifest["run"]["label"],
            rated_only=not manifest["allow_unrated"], pending=manifest.get("pending", ()))
        body["files"] = manifest["files"]
        expected = {store.MANIFEST_NAME: store.canonical_bytes(body) + b"\n",
                    store.REGISTRY_NAME: store.canonical_bytes({"schema": store.REGISTRY_SCHEMA,
                        "bots": [entry.to_json() for entry in sorted(entries, key=lambda e: e.bot_id)]}) + b"\n",
                    store.LEADERBOARD_JSON_NAME: store.canonical_bytes(board) + b"\n",
                    store.LEADERBOARD_MD_NAME: markdown.encode("utf-8"),
                    store.CONFIG_NAME: store.canonical_bytes(config.to_json()) + b"\n"}
        for name, data in expected.items():
            if (directory / name).read_bytes() != data:
                failures.append(f"{name} does not recompute from the source runs")
        return failures
    except Exception as exc:
        return [f"snapshot validation: {type(exc).__name__}: {exc}"]
