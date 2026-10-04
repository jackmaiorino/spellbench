"""Re-verify a published tournament directory from its files alone (spec 11.3, 11.6, 11.8, 12.2).

:func:`validate_tournament_dir` sends a protocol v2 run (manifest schema ``spellbench-tournament/v2``) to
:func:`validate_v2_run`, a committed run revealed without a manifest (``REVEAL.json``, spec 11.6) to
:func:`check_reveal` (a revealed run, or a withheld one whose secret was lost), and anything else, the committed
v1 runs included, to the frozen legacy verifier (``legacy_v1``, Decision 1), which also reports a missing or
unreadable manifest. The reveal constants live here, not in ``bench``, because arena code never imports ``bench``
(R3-4).

:func:`validate_v2_run` trusts nothing it can recompute and fails closed: an unreadable, missing, extra or
inconsistent file is a failure line naming the file and the problem, never an exception. Each published file is
read once, so the bytes whose digest is checked are the bytes that are parsed. The checks, in order:

1. ``manifest.json`` is one strict JSON object with exactly ``MANIFEST_KEYS`` and the v2 schema.
2. ``tournament.arena_version`` is this package's version. A run made by another version gets that one line and
   nothing more: its recomputation would only report differences that read like tampering.
3. The directory holds the manifest, ``COMMITMENT.json`` and ``store.DATA_FILE_NAMES`` as regular files (no
   symbolic links), and nothing else but the local, unhashed ``diagnostics.jsonl`` and ``throughput.jsonl``;
   ``files`` lists the commitment, then the data files, and every digest matches.
4. Every JSON file is canonical (spec 4.3). ``config.json`` is a normalized v2 config, ``registry.json`` holds
   exactly the configured bots (every field recomputed, the bot id too unless it hashes a checkpoint, whose bytes
   are not published), and ``matches.jsonl`` holds v2 ledger rows.
5. Secrets (spec 11.6): the revealed ``run_secret`` hashes to ``secrets.commitment``, ``COMMITMENT.json`` is the
   commitment record of that secret, this benchmark and this run label (R3-30), and the proof is null or well
   formed.
6. The ledger is a prefix of ``schedule(config, run_secret)`` (spec 11.6): row ``i`` records game ``i``, with
   ``game_id(i)``, its matchup, pair, slot, format, seats and decks (a decklist deck's ``deck_id`` recomputed,
   every row of one catalog deck with one ``deck_id``). No two games share a digest (spec 11.8: each chain starts
   with its own game's reset), every row carries the manifest engine's provenance (spec 9.3), and no engine
   terminal carries a reason only the host writes (spec 11.5).
7. Live validation (spec 11.3): the violations are the ledger's ``host_validator`` halts, and an invalid run
   stops at its violating game (Decision 6).
8. ``leaderboard.json`` and ``LEADERBOARD.md`` recompute byte for byte from the ledger.
9. The information rules are the ones preflight resolves from the config and the recorded engine profile
   (spec 11.1, 12.2, 14), over the recorded card-name domain (recomputed when every deck is a decklist).
10. ``manifest_body`` rebuilt from the files and the recorded inputs (the engine, its profile, the protocol
    minor, the card-name domain, the benchmark id and run label, the commitment proof, the allocation and the
    engine files) equals the manifest on every key but ``files`` and ``secrets`` (steps 3 and 5): the status
    (R3-13), the rated flag (Decision 3, R3-7), the validator record, the isolation record (spec 11.7, R3-9),
    the information rules and the game counts are recomputed, never read.

What the files cannot show is left to others: each game digest needs the engine and the bots (``bench rerun``),
and whether the commitment was public before the first game needs the repository's history (spec 11.6).
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import re
from pathlib import Path
from typing import Any, Callable, Sequence, TypeVar

from .. import _schema, digests
from ..errors import ValidationError
from ..messages import CardNameDomain, EngineIdentity, EngineProfile, Rules
from ..run_secret import RunSecret
from ..wire import strict_json_loads
from . import leaderboard, legacy_v1, store
from .allocation import Allocation
from .config import BotSpec, TournamentConfig
from .ledger import LedgerDeck, LedgerRow, LedgerSeat, parse_ledger
from .manifest import (
    MANIFEST_KEYS,
    TOURNAMENT_SCHEMA_V2,
    CommitmentProof,
    EngineFile,
    commitment_record,
    information_rules,
    is_rated,
    manifest_body,
    run_status,
)
from .registry import RegistryEntry
from .schedule import GameContext, schedule

_T = TypeVar("_T")

# The files a v2 manifest hashes, in its order: the commitment first (spec 11.6), then the data files.
HASHED_NAMES = (store.COMMITMENT_NAME, *store.DATA_FILE_NAMES)
# Task 43's throughput warnings, beside the runner's per-game diagnostics: local, unhashed, git-ignored files that
# no record cites, so a run directory may hold them.
THROUGHPUT_NAME = "throughput.jsonl"
LOCAL_NAMES = (store.DIAGNOSTICS_NAME, THROUGHPUT_NAME)
# A committed run that stopped before its manifest publishes its secret in this file (spec 11.6, Decision 9).
REVEAL_NAME = "REVEAL.json"
REVEAL_SCHEMA = "spellbench-run-reveal/v1"
# Why such a run stopped: a fixed category, never exception text, which could carry local paths (R3-28).
REVEAL_REASONS = ("preflight", "guard", "interrupted", "error")
# A committed run whose secret was lost after its commitment was pushed: its REVEAL.json holds "run_secret": null
# and this reason. Spec 11.6 publishes every committed run, so such a run is published as withheld, never revealed:
# nothing in it can be checked beyond its commitment and its names, and the site shows it as withheld.
WITHHELD_REASON = "secret_lost"
REVEAL_KEYS = ("schema", "benchmark_id", "run_label", "commitment", "run_secret", "status", "reason")
# The files a revealed run publishes: its commitment and the reveal.
REVEALED_NAMES = (store.COMMITMENT_NAME, REVEAL_NAME)
_SECRETS_KEYS = frozenset({"commitment", "run_secret", "commitment_proof"})
_HEX64 = re.compile(r"[0-9a-f]{64}")
# Reasons only the host writes; host/engine_process.py halts an engine terminal carrying one (spec 11.3, 11.5).
_HOST_REASON_PREFIXES = ("host_validator:", "host_engine_fault:", "forfeit:")
_VIOLATION_PREFIX = "host_validator:"
# Differences reported per manifest key before the rest are only counted.
_MAX_DIFFERENCES = 5
_QUOTE_LIMIT = 64
# A key one side of a comparison lacks.
_MISSING = object()
# A commitment proof that is present but does not parse.
_UNREADABLE = object()
# The schedule's shape does not depend on the run secret: a recorded secret that does not parse is replaced by this
# one, and the game ids are then left unchecked.
_STAND_IN_SECRET = RunSecret(bytes(32))


def validate_tournament_dir(directory: Path) -> list[str]:
    """Re-verify a published tournament; returns the failures (empty means OK).

    A v2 manifest goes to :func:`validate_v2_run`; a directory holding ``REVEAL.json`` and no manifest to
    :func:`check_reveal`; anything else, the committed v1 runs (schema ``spellbench-tournament/v1``) included, to
    the frozen legacy verifier (Decision 1), which reports a missing manifest or an unknown schema.
    """
    directory = Path(directory)
    if _manifest_schema(directory) == "spellbench-snapshot/v1":
        from .snapshot import validate_snapshot
        return validate_snapshot(directory)
    if _manifest_schema(directory) == TOURNAMENT_SCHEMA_V2:
        return validate_v2_run(directory)
    if not os.path.lexists(directory / store.MANIFEST_NAME) and os.path.lexists(directory / REVEAL_NAME):
        return check_reveal(directory)
    return legacy_v1.validate_v1_run(directory)


def _manifest_schema(directory: Path) -> Any:
    """The manifest's ``schema``, or None when no manifest can be read (the legacy verifier then says why)."""
    try:
        return store.read_json(directory / store.MANIFEST_NAME).get("schema")
    except store.StoreError:
        return None


def validate_v2_run(directory: Path) -> list[str]:
    """Re-verify a published protocol v2 run from its files alone; returns the failures (empty means OK).

    Never raises: whatever the files hold, the result is a list of lines, each one line of printable ASCII.
    """
    failures: list[str] = []
    try:
        _validate_v2(Path(directory), failures)
    except Exception as exc:  # noqa: BLE001 - fail closed: a value no check foresaw still fails the run
        failures.append(f"validation stopped: {type(exc).__name__}: {exc}")
    return [_printable(failure) for failure in failures]


def _validate_v2(directory: Path, failures: list[str]) -> None:
    """The checks of the module docstring, in its order; each failure is appended as a line."""
    # 1. The manifest.
    path = directory / store.MANIFEST_NAME
    if not path.is_file():
        failures.append(f"missing file: {store.MANIFEST_NAME}")
        return
    raw_manifest = _parse(store.MANIFEST_NAME, path.read_bytes, failures)
    manifest = None if raw_manifest is None else _parse(store.MANIFEST_NAME, lambda: _json_object(raw_manifest),
                                                        failures)
    if manifest is None:
        return
    # 2. The arena version gate, first: a run made by another arena version may carry fields this one does not
    # know, and the useful message is which arena to validate it with.
    gate = _version_gate(manifest.get("tournament"))
    if gate is not None:
        failures.append(gate)
        return
    missing, extra = sorted(set(MANIFEST_KEYS) - set(manifest)), sorted(set(manifest) - set(MANIFEST_KEYS))
    if missing or extra:
        failures.append(f"{store.MANIFEST_NAME} fields mismatch: missing={missing} extra={extra}")
        return
    if manifest["schema"] != TOURNAMENT_SCHEMA_V2:
        failures.append(f"{store.MANIFEST_NAME} schema must be {TOURNAMENT_SCHEMA_V2!r}")
        return
    if raw_manifest != _canonical_line(manifest):
        failures.append(f"{store.MANIFEST_NAME} is not canonical JSON (spec 4.3)")

    # 3. The directory and the digests.
    blobs = _published_files(directory, failures)
    _check_digests(manifest["files"], blobs, failures)

    # 4. The data files.
    config = _config(blobs.get(store.CONFIG_NAME), failures)
    entries = _registry(blobs.get(store.REGISTRY_NAME), config, failures)
    rows = _ledger(blobs.get(store.LEDGER_NAME), failures)
    committed = _commitment_file(blobs.get(store.COMMITMENT_NAME), failures)

    # 5. The secrets and the commitment.
    names = _parse("manifest", lambda: _run_names(manifest["run"]), failures)
    secret, proof, secret_matches = _secrets(manifest["secrets"], failures)
    if committed is not None and secret is not None and names is not None:
        expected = commitment_record(run_secret=secret, benchmark_id=names[0], run_label=names[1])
        _check_commitment_file(committed, expected, failures)

    # 6 and 7. The ledger against the schedule, the rows, and the violations.
    contexts = None if config is None else schedule(config, _STAND_IN_SECRET if secret is None else secret)
    identity = _parse("manifest", lambda: EngineIdentity.from_json(manifest["engine"], "engine"), failures)
    violations = None
    if rows is not None:
        if contexts is not None and entries is not None:
            _check_schedule(config, contexts, entries, rows, check_ids=secret_matches, failures=failures)
        _check_rows(rows, identity, failures)
        violations = _violations(rows, failures)

    # 8. The leaderboard, recomputed.
    board = None
    if config is not None and entries is not None and rows is not None:
        board = _check_leaderboard(config, entries, rows, blobs, failures)

    # 9. The other recorded inputs, and the information rules they resolve to.
    profile = _parse("manifest", lambda: EngineProfile.from_json(manifest["engine_profile"], "engine_profile"),
                     failures)
    minor = _parse("manifest", lambda: _protocol_minor(manifest["protocol"]), failures)
    allocation = _parse("manifest", lambda: Allocation.from_json(manifest["allocation"], "allocation"), failures)
    engine_files = _parse("manifest", lambda: _engine_files(manifest["engine_files"]), failures)
    domain = _parse("manifest", lambda: _card_name_domain(manifest["information_rules"]), failures)
    info_rules = None
    if config is not None and profile is not None and domain is not None:
        info_rules = _information_rules(config, profile, domain, failures)

    # 10. The manifest, rebuilt.
    inputs = (config, entries, rows, violations, board, identity, profile, minor, allocation, engine_files,
              info_rules, names)
    if any(value is None for value in inputs) or proof is _UNREADABLE:
        if not failures:  # a failure above names what could not be read; never pass a run left unchecked
            failures.append(f"{store.MANIFEST_NAME} cannot be rebuilt from the run's files")
        return
    status = run_status(scheduled=len(contexts), rows=len(rows), violations=len(violations))
    body = manifest_body(
        config=config, entries=[entries[spec.name] for spec in config.bots],
        anchor_bot_id=entries[config.rating_anchor].bot_id, engine=identity, profile=profile, protocol_minor=minor,
        info_rules=info_rules, rows=rows, violations=violations, scheduled=len(contexts),
        leaderboard_status=board["status"], status=status, benchmark_id=names[0], run_label=names[1],
        run_secret=_STAND_IN_SECRET if secret is None else secret, commitment_proof=proof, allocation=allocation,
        engine_files=engine_files,
    )
    notes = {
        "run.status": "R3-13",
        "run.rated": _rated_note(status, body["validator"]["verdict"], proof, allocation, engine_files),
        "validator": "spec 11.3",
        "isolation": "spec 11.7",
        "information_rules": "spec 12.2",
    }
    for key in MANIFEST_KEYS:
        if key not in ("files", "secrets"):  # checked in steps 3 and 5
            _report_differences(key, body[key], manifest[key], notes, failures)


# ---------------------------------------------------------------------------
# A committed run revealed without a manifest (spec 11.6; Decision 9)
# ---------------------------------------------------------------------------


def check_reveal(directory: Path) -> list[str]:
    """Re-verify a committed run revealed without a manifest (spec 11.6); returns the failures (empty means OK).

    The directory holds ``COMMITMENT.json`` and ``REVEAL.json`` as regular files and nothing else but the local
    unhashed files and OS metadata. ``REVEAL.json`` is one canonical JSON object with exactly ``REVEAL_KEYS``:
    ``REVEAL_SCHEMA``, a benchmark id and a run label, status ``aborted``, a reason from ``REVEAL_REASONS`` (a
    category, R3-28), and a run secret that hashes to its commitment. ``COMMITMENT.json`` is the commitment record
    of that secret, benchmark id and run label (R3-30).

    A withheld run (its secret lost after the push) holds ``"run_secret": null`` and ``WITHHELD_REASON``: it is a
    valid publication (spec 11.6) whose ``COMMITMENT.json`` is checked for the benchmark id, the run label and the
    commitment the record names, and nothing more, since no secret exists to check. Never raises, like
    :func:`validate_v2_run`.
    """
    failures: list[str] = []
    try:
        _check_reveal(Path(directory), failures)
    except Exception as exc:  # noqa: BLE001 - fail closed: a value no check foresaw still fails the run
        failures.append(f"validation stopped: {type(exc).__name__}: {exc}")
    return [_printable(failure) for failure in failures]


def _check_reveal(directory: Path, failures: list[str]) -> None:
    blobs = _published_files(directory, failures, names=REVEALED_NAMES, others=LOCAL_NAMES)
    committed = _commitment_file(blobs.get(store.COMMITMENT_NAME), failures)
    data = blobs.get(REVEAL_NAME)
    record = None if data is None else _parse(REVEAL_NAME, lambda: _json_object(data), failures)
    if record is None:
        return
    if data != _canonical_line(record):
        failures.append(f"{REVEAL_NAME} is not canonical JSON (spec 4.3)")
    if set(record) != set(REVEAL_KEYS):
        missing, extra = sorted(set(REVEAL_KEYS) - set(record)), sorted(set(record) - set(REVEAL_KEYS))
        failures.append(f"{REVEAL_NAME} fields mismatch: missing={missing} extra={extra}")
        return
    if not _same(record["schema"], REVEAL_SCHEMA):
        failures.append(f"{REVEAL_NAME} schema must be {REVEAL_SCHEMA!r}")
    if not _same(record["status"], "aborted"):
        failures.append(f"{REVEAL_NAME} status must be \"aborted\": a run revealed without a manifest did not finish")
    withheld = record["run_secret"] is None  # its secret was lost after the push (spec 11.6)
    if withheld and not _same(record["reason"], WITHHELD_REASON):
        failures.append(f"{REVEAL_NAME} withholds its run secret (run_secret null), so its reason must be "
                        f"{WITHHELD_REASON!r}")
    elif not withheld and not any(_same(record["reason"], reason) for reason in REVEAL_REASONS):
        failures.append(f"{REVEAL_NAME} reason must be one of {', '.join(REVEAL_REASONS)}: a category, never "
                        "exception text (R3-28)")
    named = True
    for key in ("benchmark_id", "run_label"):
        if type(record[key]) is not str or not record[key]:
            failures.append(f"{REVEAL_NAME} {key} must be a nonempty string")
            named = False
    secret = None
    if not withheld:
        try:
            secret = RunSecret.from_hex(record["run_secret"])
        except ValueError:
            failures.append(f"{REVEAL_NAME} run_secret is not a revealed run secret: 64 lowercase hex characters "
                            "(spec 11.6)")
    commitment = record["commitment"]
    well_formed = type(commitment) is str and _HEX64.fullmatch(commitment) is not None
    if not well_formed:
        failures.append(f"{REVEAL_NAME} commitment is not 64 lowercase hex characters (spec 11.6)")
    elif secret is not None and secret.commitment() != commitment:
        failures.append(f"the run secret in {REVEAL_NAME} does not hash to its commitment (spec 11.6)")
    if committed is not None and secret is not None and named:
        expected = commitment_record(run_secret=secret, benchmark_id=record["benchmark_id"],
                                     run_label=record["run_label"])
        _check_commitment_file(committed, expected, failures)
    elif committed is not None and withheld and named and well_formed:
        # No secret to hash: the record must name the commitment published before the run (spec 11.6).
        expected = {**commitment_record(run_secret=_STAND_IN_SECRET, benchmark_id=record["benchmark_id"],
                                        run_label=record["run_label"]), "commitment": commitment}
        _check_commitment_file(committed, expected, failures, source=f"the commitment named in {REVEAL_NAME}")


# ---------------------------------------------------------------------------
# Reading the published files
# ---------------------------------------------------------------------------


def _parse(name: str, parse: Callable[[], _T], failures: list[str]) -> _T | None:
    """``parse()``, or None after a failure naming ``name`` and the problem.

    Any exception is a failure: parsers raise ``ValidationError`` for a malformed record, but a value of an
    unforeseen type can surface as a ``TypeError`` deep inside one, and a validator reports, never raises.
    """
    try:
        return parse()
    except Exception as exc:  # noqa: BLE001 - fail closed, naming the file
        failures.append(f"{name}: {exc}")
        return None


def _json_object(data: bytes) -> dict[str, Any]:
    """One strict JSON object (spec 2), its final newline aside; canonical form is checked separately."""
    return strict_json_loads(data[:-1] if data.endswith(b"\n") else data)


def _canonical_line(value: Any) -> bytes:
    """A document as ``store.write_json_atomic`` writes it (spec 4.3)."""
    return store.canonical_bytes(value) + b"\n"


def _same(first: Any, second: Any) -> bool:
    """JSON equality: ``true`` is not ``1``, as Python's ``==`` would have it."""
    return store.canonical_bytes(first) == store.canonical_bytes(second)


def _package_version() -> str:
    """The running package version, read at call time."""
    from .. import __version__

    return __version__


def _version_gate(tournament: Any) -> str | None:
    """The single failure of a run made by another arena version, or None (a missing or malformed version fails
    the rebuilt manifest's comparison instead)."""
    made_by = tournament.get("arena_version") if isinstance(tournament, dict) else None
    current = _package_version()
    if type(made_by) is not str or made_by == current:
        return None
    shown = made_by if made_by.isprintable() else repr(made_by)
    return (
        f"this run was made by spellbench arena {shown}; this is {current}: "
        f"rerun the benchmark, or validate with arena {shown}"
    )


def _regular(path: Path) -> bool:
    """A regular file in the run directory itself: a symbolic link would publish bytes kept elsewhere."""
    return path.is_file() and not path.is_symlink()


# Names a desktop writes into any folder it shows (Finder, Dolphin, Explorer). They are never read, so ignoring them
# opens no path for tampering, and a run someone merely browsed still validates.
_OS_METADATA_NAMES = frozenset({"thumbs.db", "desktop.ini"})


def _os_metadata(name: str) -> bool:
    """A hidden entry (``.DS_Store``, ``.directory``, ...) or a Windows folder file, compared without case."""
    return name.startswith(".") or name.lower() in _OS_METADATA_NAMES


def _published_files(
    directory: Path,
    failures: list[str],
    *,
    names: Sequence[str] = HASHED_NAMES,
    others: Sequence[str] = (store.MANIFEST_NAME, *LOCAL_NAMES),
) -> dict[str, bytes]:
    """The bytes of each published file of ``names`` (a run's hashed files); any entry but those, ``others`` (the
    manifest and the local files) and OS metadata is a failure."""
    try:
        listed = {path.name: path for path in directory.iterdir() if not _os_metadata(path.name)}
    except OSError as exc:
        failures.append(f"cannot list the run directory: {exc.strerror or exc}")
        return {}
    for name in sorted(listed):
        if name not in (*others, *names):
            failures.append(f"unexpected file in the run directory: {name}")
        elif not _regular(listed[name]):
            failures.append(f"{name} is not a regular file")
    blobs: dict[str, bytes] = {}
    for name in names:
        if name not in listed:
            failures.append(f"missing file: {name}")
        elif _regular(listed[name]):
            data = _parse(f"cannot read {name}", listed[name].read_bytes, failures)
            if data is not None:
                blobs[name] = data
                if b"\r\n" in data:  # canonical JSON escapes CR, and the arena writes LF, so a CR LF is a conversion
                    failures.append(f"{name} has CR LF line endings: published files use LF, so a copy or an edit "
                                    "outside git changed its bytes")
    return blobs


def _check_digests(files: Any, blobs: dict[str, bytes], failures: list[str]) -> None:
    """``files`` lists the commitment, then the data files, each with the SHA-256 and size of its bytes."""
    entries = files if isinstance(files, list) else []
    paths = [entry.get("path") if isinstance(entry, dict) else None for entry in entries]
    if not isinstance(files, list) or paths != list(HASHED_NAMES):
        failures.append(f"manifest files must list exactly {list(HASHED_NAMES)}, in that order")
    listed = {entry["path"]: entry for entry in entries if isinstance(entry, dict) and type(entry.get("path")) is str}
    for name in HASHED_NAMES:
        if name in listed and name in blobs:
            data = blobs[name]
            expected = {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            if not _same(listed[name], expected):
                failures.append(f"digest mismatch: {name}")


def _config(data: bytes | None, failures: list[str]) -> TournamentConfig | None:
    """``config.json``: a v2 config, recorded as the arena writes it (normalized, canonical)."""
    if data is None:
        return None
    config = _parse(store.CONFIG_NAME, lambda: TournamentConfig.from_json(_json_object(data)), failures)
    if config is not None and data != _canonical_line(config.to_json()):
        failures.append(f"{store.CONFIG_NAME} is not its config in the normalized canonical form the arena writes")
    return config


def _registry_document(data: bytes) -> list[RegistryEntry]:
    document = _json_object(data)
    store.require_keys(document, ("schema", "bots"), "registry")
    if document["schema"] != store.REGISTRY_SCHEMA:
        raise ValidationError(f"registry.schema: must be {store.REGISTRY_SCHEMA!r}")
    bots = _schema.array(document["bots"], "registry.bots")
    return [RegistryEntry.from_json(item, f"registry.bots[{index}]") for index, item in enumerate(bots)]


def _registry_entry(spec: BotSpec, recorded_bot_id: str) -> RegistryEntry:
    """The entry the arena registers for ``spec``. A checkpoint's bytes are not published, so a bot with one keeps
    its recorded id; its other fields are still recomputed."""
    if spec.checkpoint is None:
        return spec.registry_entry()
    return dataclasses.replace(dataclasses.replace(spec, checkpoint=None).registry_entry(), bot_id=recorded_bot_id)


def _registry(
    data: bytes | None, config: TournamentConfig | None, failures: list[str]
) -> dict[str, RegistryEntry] | None:
    """The configured bots' entries by name: ``registry.json`` holds exactly those, each as its config entry
    registers it, sorted by bot id in canonical form."""
    if data is None:
        return None
    recorded = _parse(store.REGISTRY_NAME, lambda: _registry_document(data), failures)
    if recorded is None or config is None:
        return None
    by_name = {entry.name: entry for entry in recorded}
    if len(by_name) != len(recorded) or set(by_name) != {spec.name for spec in config.bots}:
        failures.append(f"{store.REGISTRY_NAME} does not hold exactly the bots of {store.CONFIG_NAME}")
        return None
    for spec in config.bots:
        if _registry_entry(spec, by_name[spec.name].bot_id) != by_name[spec.name]:
            failures.append(f"{store.REGISTRY_NAME} entry {spec.name!r} does not match its bot in {store.CONFIG_NAME}")
    document = {
        "schema": store.REGISTRY_SCHEMA,
        "bots": [entry.to_json() for entry in sorted(recorded, key=lambda entry: entry.bot_id)],
    }
    if data != _canonical_line(document):
        failures.append(f"{store.REGISTRY_NAME} is not its entries in canonical form, sorted by bot id (spec 4.3)")
    return by_name


def _ledger_rows(data: bytes) -> tuple[LedgerRow, ...]:
    if data == b"":
        return ()  # a run aborted before its first game
    if not data.endswith(b"\n"):
        raise ValidationError("the last row does not end with a newline")
    values = []
    for number, line in enumerate(data[:-1].split(b"\n"), 1):
        try:
            values.append(strict_json_loads(line))
        except Exception as exc:  # noqa: BLE001 - named with its line
            raise ValidationError(f"line {number} is not a strict JSON object: {exc}") from None
    return parse_ledger(values)


def _ledger(data: bytes | None, failures: list[str]) -> tuple[LedgerRow, ...] | None:
    """``matches.jsonl``: v2 ledger rows, one canonical line each (spec 4.3)."""
    if data is None:
        return None
    rows = _parse(store.LEDGER_NAME, lambda: _ledger_rows(data), failures)
    if rows is not None:
        for number, (line, row) in enumerate(zip(data.split(b"\n"), rows), 1):
            if line != store.canonical_bytes(row.to_json()):
                failures.append(f"{store.LEDGER_NAME} line {number} is not its row in canonical form (spec 4.3)")
                break
    return rows


def _commitment_file(data: bytes | None, failures: list[str]) -> dict[str, Any] | None:
    """``COMMITMENT.json`` as published before the first game (spec 11.6)."""
    if data is None:
        return None
    record = _parse(store.COMMITMENT_NAME, lambda: _json_object(data), failures)
    if record is not None and data != _canonical_line(record):
        failures.append(f"{store.COMMITMENT_NAME} is not canonical JSON (spec 4.3)")
    return record


# ---------------------------------------------------------------------------
# Recorded inputs: what only the manifest holds
# ---------------------------------------------------------------------------


def _run_names(run: Any) -> tuple[str | None, str | None]:
    """The run's benchmark id and label, each null or a string (its status and rated flag are recomputed)."""
    _schema.as_object(run, "run")
    return (_schema.nullable(run.get("benchmark_id"), _schema.text, "run.benchmark_id"),
            _schema.nullable(run.get("label"), _schema.text, "run.label"))


def _protocol_minor(protocol: Any) -> int:
    """The engine's ``hello_ok.protocol_minor`` (spec 9.1); the rest of the block is recomputed."""
    return _schema.u32(_schema.as_object(protocol, "protocol").get("minor"), "protocol.minor")


def _engine_files(value: Any) -> tuple[EngineFile, ...]:
    items = _schema.array(value, "engine_files")
    return tuple(EngineFile.from_json(item, f"engine_files[{index}]") for index, item in enumerate(items))


def _card_name_domain(info: Any) -> CardNameDomain:
    """The recorded ``rules.card_name_domain``, its ``domain_id`` checked against its names (spec 4.3, 12.2)."""
    rules = _schema.as_object(_schema.as_object(info, "information_rules").get("rules"), "information_rules.rules")
    return CardNameDomain.from_json(rules.get("card_name_domain"), "information_rules.rules.card_name_domain")


def _secrets(secrets: Any, failures: list[str]) -> tuple[RunSecret | None, Any, bool]:
    """The revealed run secret, the commitment proof (``_UNREADABLE`` when malformed), and whether the secret hashes
    to the manifest's commitment (spec 11.6)."""
    if not isinstance(secrets, dict) or set(secrets) != _SECRETS_KEYS:
        failures.append("manifest secrets must hold exactly commitment, run_secret and commitment_proof (spec 11.6)")
        return None, _UNREADABLE, False
    secret = None
    try:
        secret = RunSecret.from_hex(secrets["run_secret"])
    except ValueError:
        failures.append("manifest secrets.run_secret is not a revealed run secret: 64 lowercase hex characters "
                        "(spec 11.6)")
    commitment = secrets["commitment"]
    if type(commitment) is not str or not _HEX64.fullmatch(commitment):
        failures.append("manifest secrets.commitment is not 64 lowercase hex characters (spec 11.6)")
    matches = secret is not None and secret.commitment() == commitment
    if secret is not None and not matches:
        failures.append("the revealed run secret does not hash to the commitment in secrets.commitment (spec 11.6)")
    proof = None
    if secrets["commitment_proof"] is not None:
        proof = _parse("manifest", lambda: CommitmentProof.from_json(secrets["commitment_proof"],
                                                                     "secrets.commitment_proof"), failures)
        proof = _UNREADABLE if proof is None else proof
    return secret, proof, matches


def _check_commitment_file(
    record: dict[str, Any],
    expected: dict[str, Any],
    failures: list[str],
    *,
    source: str = "the SHA-256 of the revealed run secret",
) -> None:
    """``COMMITMENT.json`` is the commitment record of the revealed secret, this benchmark and this run label
    (spec 11.6, R3-30): a commitment made for another run proves nothing about this one. ``source`` says where the
    expected commitment comes from (a withheld run names it instead of revealing its secret)."""
    if set(record) != set(expected):
        failures.append(f"the commitment file {store.COMMITMENT_NAME} has fields {sorted(record)}; a commitment "
                        f"record has {sorted(expected)}")
        return
    for key in ("schema", "protocol"):
        if not _same(record[key], expected[key]):
            failures.append(f"the commitment file {store.COMMITMENT_NAME} has {key} {_shown(record[key])}; "
                            f"expected {_shown(expected[key])}")
    for key, field in (("benchmark_id", "benchmark_id"), ("run_label", "label")):
        if not _same(record[key], expected[key]):
            failures.append(f"the commitment in {store.COMMITMENT_NAME} was made for another run: its {key} is "
                            f"{_shown(record[key])}, this run's {field} is {_shown(expected[key])} (spec 11.6, R3-30)")
    if not _same(record["commitment"], expected["commitment"]):
        failures.append(f"the commitment in {store.COMMITMENT_NAME} is not {source} (spec 11.6)")


# ---------------------------------------------------------------------------
# The ledger against the schedule, and the violations
# ---------------------------------------------------------------------------


def _check_schedule(
    config: TournamentConfig,
    contexts: Sequence[GameContext],
    entries: dict[str, RegistryEntry],
    rows: Sequence[LedgerRow],
    *,
    check_ids: bool,
    failures: list[str],
) -> None:
    """The ledger is a prefix of the schedule (spec 11.6; all of it for a complete run): row ``i`` records game
    ``i``, its id, matchup, pair, slot, format, seats and decks. ``check_ids`` is false when the revealed secret
    does not hash to its commitment, a failure already reported: that secret's ids prove nothing."""
    if len(rows) > len(contexts):
        failures.append(f"the ledger has {len(rows)} games but the schedule has {len(contexts)}")
    decklist_ids = {spec: digests.deck_id([row.to_json() for row in spec.decklist or ()])
                    for spec in config.deck_specs() if spec.catalog_id is None}
    catalog: dict[str, set[tuple[str, str]]] = {}
    for index, (context, row) in enumerate(zip(contexts, rows)):
        differ = ["game_index"] if row.game_index != context.game_index else []
        if check_ids and row.game_id != context.game_id:
            differ.append("game_id")
        differ += [field for field in ("matchup_index", "pair_index", "pair_slot")
                   if getattr(row, field) != getattr(context, field)]
        if row.format != config.format:
            differ.append("format")
        seats = tuple(LedgerSeat(seat, entries[spec.name].bot_id, entries[spec.name].name, entries[spec.name].version)
                      for seat, spec in context.seat_specs)
        if row.seats != seats:
            differ.append("seats")
        decks_match = True
        for spec, deck in zip(context.decks, row.decks):
            if spec.catalog_id is None:
                decks_match = decks_match and deck == LedgerDeck(decklist_ids[spec], spec.name, None)
            else:
                decks_match = decks_match and deck.catalog_id == spec.catalog_id
                catalog.setdefault(spec.catalog_id, set()).add((deck.deck_id, deck.name))
        if not decks_match:
            differ.append("decks")
        if differ:
            verb = "differs" if len(differ) == 1 else "differ"
            failures.append(f"ledger row {index} does not match the schedule: {', '.join(differ)} {verb}")
    for catalog_id in sorted(catalog):
        if len(catalog[catalog_id]) > 1:
            failures.append(f"the ledger gives catalog deck {catalog_id!r} {len(catalog[catalog_id])} deck_id and "
                            "name pairs; one deck has one deck_id (spec 4.3, 12.1)")


def _check_rows(rows: Sequence[LedgerRow], identity: EngineIdentity | None, failures: list[str]) -> None:
    """What the schedule does not fix: distinct digests, host-only reasons, and the engine's provenance."""
    first_with: dict[str, int] = {}
    for index, row in enumerate(rows):
        first = first_with.setdefault(row.game_digest, index)
        if first != index:
            failures.append(f"ledger rows {first} and {index} have the same game_digest; each game's digest chains "
                            "its own reset (spec 11.8)")
        if row.adjudication is None and row.reason.startswith(_HOST_REASON_PREFIXES):
            failures.append(f"ledger row {index} is an engine terminal with the host's reason {row.reason!r} "
                            "(spec 11.5)")
    if identity is not None:
        provenance = identity.provenance().to_json()
        drifted = [index for index, row in enumerate(rows) if row.engine != provenance]
        if drifted:
            failures.append(f"{len(drifted)} ledger rows (the first is row {drifted[0]}) do not carry the provenance "
                            "of the manifest's engine (spec 9.3)")


def _violations(rows: Sequence[LedgerRow], failures: list[str]) -> list[dict[str, Any]]:
    """The live-validation violations, recomputed: each ``host_validator:<rule>`` halt of the ledger with its halt's
    detail (spec 11.3). An invalid run stops at its violating game (Decision 6), so that is the last row."""
    violations = []
    positions = []
    for index, row in enumerate(rows):
        if row.adjudication is not None and row.reason.startswith(_VIOLATION_PREFIX):
            violations.append({"game_index": row.game_index, "game_id": row.game_id,
                               "rule": row.reason[len(_VIOLATION_PREFIX):], "detail": row.adjudication.detail})
            positions.append(index)
    if positions and positions[0] != len(rows) - 1:
        failures.append(f"the ledger goes on after the violation in row {positions[0]}; an invalid run stops at its "
                        "violating game (spec 11.3, Decision 6)")
    return violations


# ---------------------------------------------------------------------------
# The leaderboard, the information rules and the rebuilt manifest
# ---------------------------------------------------------------------------


def _check_leaderboard(
    config: TournamentConfig, entries: dict[str, RegistryEntry], rows: Sequence[LedgerRow],
    blobs: dict[str, bytes], failures: list[str],
) -> dict[str, Any] | None:
    """Both leaderboard files recomputed from the ledger and compared byte for byte; returns the document."""
    try:
        document, markdown = leaderboard.build_leaderboard(
            rows, [entries[spec.name] for spec in config.bots], anchor_bot_id=entries[config.rating_anchor].bot_id,
            base_seed=config.stats_seed, bootstrap_replicates=config.bootstrap_replicates, format=config.format,
            schema=leaderboard.LEADERBOARD_SCHEMA_V2,
        )
    except Exception as exc:  # noqa: BLE001 - fail closed
        failures.append(f"the leaderboard cannot be recomputed from {store.LEDGER_NAME}: {exc}")
        return None
    recomputed = {store.LEADERBOARD_JSON_NAME: _canonical_line(document),
                  store.LEADERBOARD_MD_NAME: markdown.encode("utf-8")}
    for name, data in recomputed.items():
        if name in blobs and blobs[name] != data:
            failures.append(f"{name} does not match a recomputation from {store.LEDGER_NAME}")
    return document


def _information_rules(
    config: TournamentConfig, profile: EngineProfile, domain: CardNameDomain, failures: list[str]
) -> dict[str, Any] | None:
    """The ``information_rules`` block preflight records for ``config`` under the recorded profile (spec 11.1,
    12.2, 14): ``mulligan: auto`` resolved, the recorded card-name domain (recomputed when every deck is a
    decklist), and each enabled extension carrying native ids, with its audit. A rule preflight refuses fails."""
    supported = profile.rules_supported
    mulligan = config.rules.mulligan
    if mulligan == "auto":
        mulligan = "london" if "london" in supported["mulligan"] else "none"
    refused = []
    if mulligan not in supported["mulligan"] and config.rules.mulligan != "auto":
        refused.append(f"mulligan {mulligan!r}")
    if config.rules.starting_player not in supported["starting_player"]:
        refused.append(f"starting_player {config.rules.starting_player!r}")
    declared = {extension.name: extension.native_ids for extension in profile.extensions}
    refused += [f"extension {name!r}" for name in config.extensions if name not in declared]
    refused += [f"extension {name!r} without an audit" for name in config.extensions
                if declared.get(name) and name not in config.native_id_audits]
    if refused:
        failures.append(f"preflight refuses {store.CONFIG_NAME} under the manifest's engine_profile: "
                        f"{', '.join(refused)} (spec 11.1, 14)")
        return None
    native = [{"name": name, "audit": config.native_id_audits[name]} for name in config.extensions if declared[name]]
    decklists = [spec for spec in config.deck_specs() if spec.catalog_id is None]
    decklist_names = {row.name for spec in decklists for row in spec.decklist or ()}
    if len(decklists) == len(config.deck_specs()):
        domain = CardNameDomain.from_json(digests.card_name_domain(decklist_names))
    elif not decklist_names <= set(domain.names):
        failures.append("manifest information_rules.rules.card_name_domain lacks names of the decklist decks "
                        "(spec 12.2)")
    rules = Rules(opponent_decklist=config.rules.opponent_decklist, mulligan=mulligan,
                  starting_player=config.rules.starting_player, starting_seat=config.rules.starting_seat,
                  card_name_domain=domain, extensions=config.extensions, probe=False)
    return information_rules(rules, profile, native)


def _rated_note(status: str, verdict: str, proof: Any, allocation: Allocation, engine_files: Sequence[Any]) -> str:
    """Decision 3, and what a run the rule does not rate lacks."""
    if is_rated(status=status, verdict=verdict, commitment_proof=proof, allocation=allocation,
                engine_files=engine_files):
        return "Decision 3"
    lacking = [f"the run is {status}"] if status != "complete" else []
    lacking += ["the verdict is fail"] if verdict != "pass" else []
    lacking += ["no commitment proof"] if proof is None else []
    lacking += [f"the allocation is {allocation.label}"] if not allocation.measured else []
    lacking += ["no pinned engine files"] if not engine_files else []
    return f"Decision 3: {', '.join(lacking)}"


def _differences(expected: Any, actual: Any, path: str) -> list[tuple[str, Any, Any]]:
    """Where JSON value ``actual`` differs from ``expected``: ``(path, actual, expected)`` for each."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        return [
            difference
            for key in sorted(expected.keys() | actual.keys())
            for difference in _differences(expected.get(key, _MISSING), actual.get(key, _MISSING), f"{path}.{key}")
        ]
    if isinstance(expected, list) and isinstance(actual, list) and len(expected) == len(actual):
        return [
            difference
            for index, (item, recorded) in enumerate(zip(expected, actual))
            for difference in _differences(item, recorded, f"{path}[{index}]")
        ]
    if expected is not _MISSING and actual is not _MISSING and _same(expected, actual):
        return []
    return [(path, actual, expected)]


def _report_differences(key: str, expected: Any, actual: Any, notes: dict[str, str], failures: list[str]) -> None:
    """One line per differing value of manifest key ``key``, up to ``_MAX_DIFFERENCES``, then their count."""
    found = _differences(expected, actual, key)
    for path, recorded, recomputed in found[:_MAX_DIFFERENCES]:
        note = notes.get(path, notes.get(key))
        suffix = f" ({note})" if note else ""
        failures.append(f"manifest {path} is {_shown(recorded)}; recomputed: {_shown(recomputed)}{suffix}")
    if len(found) > _MAX_DIFFERENCES:
        failures.append(f"manifest {key}: {len(found) - _MAX_DIFFERENCES} more differences")


def _shown(value: Any) -> str:
    """A JSON value in a failure line: a scalar as canonical JSON, cut short; a container by its kind."""
    if value is _MISSING:
        return "missing"
    if isinstance(value, dict):
        return "an object"
    if isinstance(value, list):
        return f"a list of {len(value)} items"
    text = store.canonical_bytes(value).decode("utf-8")
    return text if len(text) <= _QUOTE_LIMIT else text[:_QUOTE_LIMIT - 3] + "..."


def _printable(line: str) -> str:
    """A failure as one line of printable ASCII: a forged value could otherwise carry a newline and a CI workflow
    command, or text a Windows console cannot encode."""
    return line if line.isascii() and line.isprintable() else line.encode("unicode_escape").decode("ascii")
