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
from typing import Any, Sequence

from . import leaderboard, registry, store
from .config import BotSpec, TournamentConfig
from .ledger import LedgerRow, parse_ledger
from .manifest import EngineFile

SCHEMA = "spellbench-snapshot/v1"
FILES = (store.CONFIG_NAME, store.REGISTRY_NAME, store.LEADERBOARD_JSON_NAME, store.LEADERBOARD_MD_NAME)
CAVEAT = (
    "Reference-panel rating: entrants are compared through shared local opponents. Unplayed head-to-head "
    "matchups are not measured; matchup-specific strengths can differ from the ranking. Compatible earlier "
    "evaluations are reused, so this is a dated model measurement. Elo and its interval can change when the "
    "combined results are refitted without replaying earlier games."
)


class SnapshotError(ValueError):
    pass


def files_identity(files: Sequence[EngineFile]) -> str:
    return store.sha256_hex(store.canonical_bytes([file.to_json() for file in files]))


def checked_label(label: Any) -> str:
    if type(label) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:-[1-9][0-9]*)?", label):
        raise SnapshotError("source and snapshot labels must be dated run names")
    datetime.date.fromisoformat(label[:10])
    return label


def bot_inputs(spec: BotSpec) -> dict[str, Any]:
    doc = spec.to_json()
    for key in ("training_style_tags", "registered_at"):
        doc.pop(key)
    return doc


def contract(config: TournamentConfig) -> dict[str, Any]:
    if not config.opponent_panel or config.evaluation_engine_identity is None:
        raise SnapshotError("a reference-panel snapshot needs fingerprinted inputs; run bench prepare first")
    by_name = {bot.name: bot for bot in config.bots}
    if any(bot.evaluation_identity is None for bot in config.bots):
        raise SnapshotError("every entrant needs an evaluation_identity; run bench prepare first")
    doc = config.to_json()
    keys = ("format", "engine", "deck_pool", "decks", "pairs_per_matchup", "rules", "extensions",
            "native_id_audits", "time_control", "limits", "resources", "rating_anchor",
            "evaluation_version", "evaluation_engine_identity", "evaluation_engine_inputs")
    return {**{key: doc[key] for key in keys if key in doc},
            "references": {name: bot_inputs(by_name[name]) for name in sorted(config.opponent_panel)}}


def required_matchups(config: TournamentConfig) -> tuple[tuple[str, str], ...]:
    names = sorted(bot.name for bot in config.bots)
    panel = set(config.opponent_panel)
    return tuple((a, b) for i, a in enumerate(names) for b in names[i + 1:] if a in panel or b in panel)


def without_entrants(config: TournamentConfig, names: tuple[str, ...]) -> TournamentConfig:
    """The same evaluation without the named roster entries."""
    if not names:
        return config
    left = replace(config, bots=tuple(bot for bot in config.bots if bot.name not in names),
                   matchups=None if config.matchups is None else
                   tuple(pair for pair in config.matchups if not set(pair) & set(names)))
    return TournamentConfig.from_json(left.to_json())


@dataclass(frozen=True)
class Source:
    path: Path
    config: TournamentConfig
    manifest: dict[str, Any]
    entries: tuple[registry.RegistryEntry, ...]
    rows: tuple[LedgerRow, ...]
    manifest_sha256: str

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


def select_blocks(config: TournamentConfig, sources: Sequence[Source], *, rated_only: bool = True
                  ) -> dict[tuple[str, str], Source]:
    """Latest compatible whole block per matchup; outcomes never influence the selection."""
    expected = contract(config)
    current = {bot.name: bot for bot in config.bots}
    wanted = set(required_matchups(config))
    selected = {}
    for source in sorted(sources, key=lambda s: (s.path.name[:10], int(s.path.name[11:] or "1"))):
        if rated_only and source.manifest["run"]["rated"] is not True:
            continue
        try:
            compatible = contract(source.config) == expected
        except SnapshotError:
            compatible = False
        if not compatible:
            continue
        by_name = {bot.name: bot for bot in source.config.bots}
        for pair in wanted & source.blocks().keys():
            if all(bot_inputs(by_name[name]) == bot_inputs(current[name]) for name in pair):
                selected[pair] = source
    return selected


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
    expected = contract(config)
    rows = []
    entries_by_name = {}
    specs = {bot.name: bot for bot in config.bots}
    receipts: dict[str, dict[str, Any]] = {}
    sources = {}
    next_pair = 0
    facts = None
    for pair in sorted(chosen):
        source = chosen[pair]
        if source.manifest["run"]["benchmark_id"] != benchmark_id:
            raise SnapshotError(f"source {source.path.name} belongs to another benchmark")
        if contract(source.config) != expected:
            raise SnapshotError(f"source {source.path.name} has incompatible evaluation conditions")
        by_name = {bot.name: bot for bot in source.config.bots}
        if any(bot_inputs(by_name[name]) != bot_inputs(specs[name]) for name in pair):
            raise SnapshotError(f"source {source.path.name} has incompatible entrant inputs")
        if rated_only and not source.manifest["run"]["rated"]:
            raise SnapshotError(f"source {source.path.name} is not rated")
        source_facts = {key: source.manifest[key] for key in
                        ("protocol", "engine", "engine_profile", "information_rules", "engine_files")}
        source_facts["resolved_decks"] = sorted(
            {store.canonical_bytes(deck.to_json()) for row in source.rows for deck in row.decks})
        source_facts["resolved_decks"] = [json.loads(item) for item in source_facts["resolved_decks"]]
        if facts is not None and facts != source_facts:
            raise SnapshotError("source runs disagree on engine, deck domain, profile or information rules")
        facts = source_facts
        sources[source.path.name] = source
        receipt = receipts.setdefault(source.path.name, {"run": source.path.name,
            "manifest_sha256": source.manifest_sha256, "matchups": []})
        receipt["matchups"].append(list(pair))
        block = source.blocks().get(pair)
        if block is None:
            raise SnapshotError(f"source {source.path.name} lacks a complete {pair} matchup")
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
    document, _ = leaderboard.build_leaderboard(rows, entries,
        anchor_bot_id=entries_by_name[config.rating_anchor].bot_id, base_seed=config.stats_seed,
        bootstrap_replicates=config.bootstrap_replicates, format=config.format, schema=store.LEADERBOARD_SCHEMA)
    if document["status"] != "ok" or any(not row["rated"] for row in document["rows"]):
        raise SnapshotError("panel results do not connect every entrant to the rating anchor")
    document["evaluation"] = {"mode": "reference_panel", "version": config.evaluation_version,
        "opponents": list(config.opponent_panel), "sources": sorted(sources), "caveat": CAVEAT,
        "observed_matchups": len(document["matchups"]), "possible_matchups": len(entries) * (len(entries) - 1) // 2}
    document["notes"] = [*document["notes"], CAVEAT]
    if pending:
        # Listed, not rated: these roster entries have no compatible panel block yet.
        document["evaluation"]["pending"] = sorted(pending)
        document["notes"].append("Pending, no panel results yet: " + ", ".join(sorted(pending)))
    assert facts is not None
    manifest = {"schema": SCHEMA, **facts, "contract": expected,
        "sources": [receipts[name] for name in sorted(receipts)],
        "allow_unrated": not rated_only,
        **({"pending": sorted(pending)} if pending else {}),
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
        manifest = store.read_json(directory / store.MANIFEST_NAME, schema=SCHEMA)
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
