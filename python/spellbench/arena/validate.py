"""Re-verify a published tournament directory from its files alone."""

from __future__ import annotations

from pathlib import Path

from .. import models
from ..errors import ValidationError
from . import leaderboard, registry, runner, store


def validate_tournament_dir(directory: Path) -> list[str]:
    """Re-verify a published tournament; returns a list of failures (empty = OK).

    Checks (fail closed): manifest presence and schema, the sha256/byte count
    of every data file, ledger row schemas, and a byte-exact recomputation of
    ``leaderboard.json`` and ``LEADERBOARD.md`` from the ledger, registry,
    and config.
    """
    failures: list[str] = []
    if not store.is_published(directory):
        return [f"{directory} has no manifest.json (not a published tournament)"]
    try:
        manifest = store.read_json(directory / store.MANIFEST_NAME, schema=store.TOURNAMENT_SCHEMA)
        store.require_keys(
            manifest,
            ["schema", "tournament", "engine", "games", "leaderboard_status", "files"],
            "manifest",
        )
    except (store.StoreError, ValidationError) as exc:
        return [f"manifest: {exc}"]
    files = manifest["files"]
    listed = [entry.get("path") for entry in files if isinstance(entry, dict)] if isinstance(files, list) else None
    if listed != list(store.DATA_FILE_NAMES):
        failures.append(f"manifest files must list exactly {list(store.DATA_FILE_NAMES)}")
    failures.extend(store.verify_file_digests(directory, manifest))
    try:
        # Everything comes from the directory itself: bot ids from the
        # registry (a checkpoint is never re-hashed), the rest re-derived.
        config = runner.TournamentConfig.from_json(
            store.read_json(directory / store.CONFIG_NAME, schema=store.CONFIG_SCHEMA)
        )
        entries = registry.read_registry(directory / store.REGISTRY_NAME)
        rows = store.parse_ledger(store.read_jsonl(directory / store.LEDGER_NAME, schema=store.LEDGER_SCHEMA))
        by_name = {entry.name: entry for entry in entries}
        if sorted(by_name) != sorted(spec.name for spec in config.bots) or len(entries) != len(config.bots):
            return failures + ["registry.json does not hold exactly the configured bots"]
        anchor_bot_id = by_name[config.rating_anchor].bot_id
        failures.extend(runner.schedule_mismatches(config, by_name, rows))
        engine = models.EngineIdentity.from_json(manifest["engine"], "manifest.engine")
        if any(row.engine != engine.provenance() for row in rows):
            failures.append("ledger engine provenance does not match manifest.engine")
        document, markdown = leaderboard.build_leaderboard(
            rows,
            entries,
            anchor_bot_id=anchor_bot_id,
            base_seed=config.base_seed,
            bootstrap_replicates=config.bootstrap_replicates,
            format=config.format,
        )
        expected_json = store.canonical_bytes(document) + b"\n"
        actual_json = (directory / store.LEADERBOARD_JSON_NAME).read_bytes()
        if actual_json != expected_json:
            failures.append("leaderboard.json does not match a recomputation from matches.jsonl")
        actual_md = (directory / store.LEADERBOARD_MD_NAME).read_bytes()
        if actual_md != markdown.encode("utf-8"):
            failures.append("LEADERBOARD.md does not match a recomputation from matches.jsonl")
        expected = runner.manifest_body(
            config,
            [by_name[spec.name] for spec in config.bots],
            anchor_bot_id,
            manifest["engine"],
            rows,
            document["status"],
        )
        for key in ("tournament", "games", "leaderboard_status"):
            if manifest[key] != expected[key]:
                failures.append(f"manifest {key} does not match the tournament data")
    except (store.StoreError, ValidationError, runner.TournamentError, ValueError) as exc:
        failures.append(f"recomputation failed: {exc}")
    return failures
