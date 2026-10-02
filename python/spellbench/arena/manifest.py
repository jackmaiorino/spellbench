"""Manifest v2: information rules, the validator verdict, the secrets, the rated rule (spec 11.3, 11.6, 12.2).

:func:`manifest_body` assembles every section of ``manifest.json`` except
``files`` (the data files' hashes, added when the arena writes them). These
are pure functions over what the arena, and Task 36's validator, already
hold: the tournament config, its registry entries, the engine's identity
and profile, the ledger rows and validator violations, the run secret and
its published proof, and the launch guard's allocation and pinned engine
files.

``EngineFile`` moves here from :mod:`spellbench.bench.pinning` (R3-4): a
manifest lists pinned files and the pinning code hashes and copies them, so
both sides need the type, and arena modules never import ``bench``, so the
dependency has to run the other way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .. import __version__, _schema
from ..errors import ValidationError
from ..host.validator import VALIDATOR_VERSION
from ..messages import EngineIdentity, EngineProfile, Rules
from ..run_secret import RunSecret
from .allocation import Allocation
from .config import BotSpec, TournamentConfig
from .ledger import LedgerRow
from .registry import RegistryEntry

TOURNAMENT_SCHEMA_V2 = "spellbench-tournament/v2"
COMMITMENT_SCHEMA = "spellbench-run-commitment/v1"
FAIRNESS_LABEL = "validator only"
RUN_STATUSES = ("complete", "invalid", "aborted")
MANIFEST_KEYS = (
    "schema", "protocol", "tournament", "engine", "engine_profile", "information_rules", "validator", "isolation",
    "secrets", "run", "allocation", "engine_files", "games", "leaderboard_status", "files",
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")

# Isolation (spec 11.7, 13 F5; R3-9).
ISOLATION_KINDS = ("builtin-in-process", "unsandboxed", "verified-sandbox")
# A subprocess command whose first part is this placeholder runs inside sub-project D's sandbox wrapper, the only
# verified isolation; no v2.0 run has it yet.
SANDBOX_PLACEHOLDER = "${SPELLBENCH_SANDBOX}"
# Owners whose subprocess bots may run unsandboxed: the maintainer's own models, and bots the maintainer builds
# from pinned, reviewed source, like the gorge engine itself. spellbench's own bots are always allowed.
ISOLATION_ALLOWLIST = ("jackmaiorino", "gorge")


# ---------------------------------------------------------------------------
# Engine files: pinned by SHA-256, listed in the manifest (ARTIFACT-LAW.md clause 4; R3-4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EngineFile:
    """One file a launch runs with: part ``index`` of the command, or, from ``len(command)`` on, a declared
    file outside the command line (such as a checkpoint).

    ``path`` locates the file on the machine that hashed it; it is not part
    of the identity (comparison), the repr, or the published record
    (:meth:`to_json`), so a manifest rebuilt from JSON (Task 36) carries it
    as ``None``.
    """

    index: int
    file_name: str
    sha256: str
    bytes: int
    path: Path | None = field(default=None, compare=False, repr=False)

    def to_json(self) -> dict[str, Any]:
        return {"index": self.index, "file_name": self.file_name, "sha256": self.sha256, "bytes": self.bytes}

    @classmethod
    def from_json(cls, value: Any, context: str = "engine_file") -> EngineFile:
        obj = _schema.as_object(value, context)
        _schema.exact_keys(obj, ("index", "file_name", "sha256", "bytes"), context)
        sha256 = _schema.text(obj["sha256"], f"{context}.sha256")
        if not _SHA256_RE.fullmatch(sha256):
            _schema.fail(f"{context}.sha256", "must be 64 lowercase hex digits")
        return cls(
            index=_schema.safe_int(obj["index"], f"{context}.index"),
            file_name=_schema.nonempty(obj["file_name"], f"{context}.file_name"),
            sha256=sha256,
            bytes=_schema.safe_int(obj["bytes"], f"{context}.bytes"),
            path=None,
        )


# ---------------------------------------------------------------------------
# Isolation (spec 11.7, 13 F5; R3-9)
# ---------------------------------------------------------------------------


def _bot_isolation(bot: BotSpec) -> str:
    if bot.type == "builtin":
        return "builtin-in-process"
    if bot.command and bot.command[0] == SANDBOX_PLACEHOLDER:
        return "verified-sandbox"
    return "unsandboxed"


def isolation_record(config: TournamentConfig) -> dict[str, Any]:
    """The manifest's ``isolation`` block: each bot's isolation, in config order, and whether the run is
    self-reported (spec 11.7: true when any entry is unsandboxed)."""
    entries = [{"name": bot.name, "isolation": _bot_isolation(bot)} for bot in config.bots]
    return {"entries": entries, "self_reported": any(entry["isolation"] == "unsandboxed" for entry in entries)}


def isolation_refusals(config: TournamentConfig) -> list[str]:
    """One message per subprocess bot whose owner is neither ``spellbench`` nor on ``ISOLATION_ALLOWLIST`` and
    whose command is not the sandbox wrapper: submitted binaries, checkpoints and pickles need the sandbox."""
    refusals = []
    for index, bot in enumerate(config.bots):
        if bot.type != "subprocess" or _bot_isolation(bot) == "verified-sandbox":
            continue
        if bot.owner == "spellbench" or bot.owner in ISOLATION_ALLOWLIST:
            continue
        refusals.append(
            f"bots[{index}] ({bot.name}): a subprocess bot owned by {bot.owner!r} runs only inside the sub-project D "
            f"sandbox (command starting {SANDBOX_PLACEHOLDER}); unsandboxed bots are limited to spellbench and "
            f"{', '.join(ISOLATION_ALLOWLIST)} (spec 11.7)"
        )
    return refusals


# ---------------------------------------------------------------------------
# The commitment and its published proof (spec 11.6; Decision 9)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommitmentProof:
    """A third-party timestamp reference proving ``COMMITMENT.json`` was public before the first game
    (Decision 9): the pushed commit, and where its timestamp can be checked."""

    commit: str
    timestamp: str

    def __post_init__(self) -> None:
        if type(self.commit) is not str or not _COMMIT_RE.fullmatch(self.commit):
            raise ValueError("a commitment proof's commit must be 40 lowercase hex characters")
        if type(self.timestamp) is not str or not self.timestamp.strip():
            raise ValueError("a commitment proof's timestamp must be a nonempty third-party reference")

    def to_json(self) -> dict[str, Any]:
        return {"commit": self.commit, "timestamp": self.timestamp}

    @classmethod
    def from_json(cls, value: Any, context: str = "commitment_proof") -> CommitmentProof:
        obj = _schema.as_object(value, context)
        _schema.exact_keys(obj, ("commit", "timestamp"), context)
        try:
            return cls(commit=obj["commit"], timestamp=obj["timestamp"])
        except ValueError as exc:
            raise ValidationError(f"{context}: {exc}") from exc


def commitment_record(*, run_secret: RunSecret, benchmark_id: str | None, run_label: str | None) -> dict[str, Any]:
    """The ``COMMITMENT.json`` document (Decision 9): the commitment alone, never the run secret."""
    return {
        "schema": COMMITMENT_SCHEMA,
        "protocol": "spellbench/v2",
        "benchmark_id": benchmark_id,
        "run_label": run_label,
        "commitment": run_secret.commitment(),
    }


# ---------------------------------------------------------------------------
# Information rules (spec 12.2)
# ---------------------------------------------------------------------------


def information_rules(
    rules: Rules, profile: EngineProfile, native_id_extensions: Sequence[Mapping[str, str]]
) -> dict[str, Any]:
    """The manifest's ``information_rules`` block (spec 12.2): the wire rules, the engine facts that affect
    play, which native-id extensions were audited for this rated run, and the fairness label. The reserved
    probe is never enabled in v2.0 (Global Constraints), so the label is always ``FAIRNESS_LABEL``."""
    return {
        "rules": rules.to_json(),
        "engine_defaults": dict(profile.engine_defaults),
        "observation": dict(profile.observation),
        "native_id_extensions": [dict(item) for item in native_id_extensions],
        "fairness_label": FAIRNESS_LABEL,
    }


# ---------------------------------------------------------------------------
# The validator verdict (spec 11.3) and the rated rule (Decision 3)
# ---------------------------------------------------------------------------


def validator_record(rows: Sequence[LedgerRow], violations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The manifest's ``validator`` block: the live validator's version, its verdict, the decisions it
    checked across the whole ledger, and every violation found."""
    return {
        "version": VALIDATOR_VERSION,
        "verdict": "fail" if violations else "pass",
        "decisions_checked": sum(row.decisions_checked for row in rows),
        "violations": list(violations),
    }


def is_rated(
    *,
    status: str,
    verdict: str,
    commitment_proof: CommitmentProof | None,
    allocation: Allocation,
    engine_files: Sequence[EngineFile],
) -> bool:
    """Decision 3: a complete run, a passing verdict, a commitment proven public, a measured allocation, and
    pinned engine files (a non-empty ``engine_files``, so the library path cannot mint a rated run without
    pins, R3-7)."""
    return (
        status == "complete"
        and verdict == "pass"
        and commitment_proof is not None
        and allocation.measured
        and bool(engine_files)
    )


def run_status(*, scheduled: int, rows: int, violations: int) -> str:
    """The run's status from the ledger alone (R3-13): ``invalid`` with a violation, else ``complete`` for a
    full ledger (an interrupt right after the last game still publishes complete), else ``aborted``."""
    if violations:
        return "invalid"
    return "complete" if rows >= scheduled else "aborted"


# ---------------------------------------------------------------------------
# The whole manifest, minus the data files' hashes
# ---------------------------------------------------------------------------


def manifest_body(
    *,
    config: TournamentConfig,
    entries: Sequence[RegistryEntry],
    anchor_bot_id: str,
    engine: EngineIdentity,
    profile: EngineProfile,
    protocol_minor: int,
    info_rules: dict[str, Any],
    rows: Sequence[LedgerRow],
    violations: Sequence[Mapping[str, Any]],
    scheduled: int,
    leaderboard_status: str,
    status: str,
    benchmark_id: str | None,
    run_label: str | None,
    run_secret: RunSecret,
    commitment_proof: CommitmentProof | None,
    allocation: Allocation,
    engine_files: Sequence[EngineFile],
) -> dict[str, Any]:
    """Every section of ``manifest.json`` but ``files`` (the arena adds that when it hashes the published data
    files); ``entries`` in config order. Shared by the run and the validator, so the validator can rebuild it
    from the published data (Task 36)."""
    counts = {"natural": 0, "truncated": 0, "halted": 0, "forfeit": 0}
    for row in rows:
        counts[row.classification] += 1
    validator = validator_record(rows, violations)
    rated = is_rated(
        status=status, verdict=validator["verdict"], commitment_proof=commitment_proof, allocation=allocation,
        engine_files=engine_files,
    )
    return {
        "schema": TOURNAMENT_SCHEMA_V2,
        "protocol": {"name": "spellbench/v2", "minor": protocol_minor},
        "tournament": {
            "format": config.format,
            "stats_seed": config.stats_seed,
            "pairs_per_matchup": config.pairs_per_matchup,
            "include_self_play": config.include_self_play,
            "workers": config.workers,
            "time_control": config.time_control.to_json(),
            "limits": config.limits.to_json(),
            "resources": config.resources.to_json(),
            "bootstrap_replicates": config.bootstrap_replicates,
            "rating_anchor": {"name": config.rating_anchor, "bot_id": anchor_bot_id},
            "arena_version": __version__,
            "bots": [entry.to_json() for entry in entries],
        },
        "engine": engine.to_json(),
        "engine_profile": profile.to_json(),
        "information_rules": info_rules,
        "validator": validator,
        "isolation": isolation_record(config),
        "secrets": {
            "commitment": run_secret.commitment(),
            "run_secret": run_secret.hex(),
            "commitment_proof": None if commitment_proof is None else commitment_proof.to_json(),
        },
        "run": {"benchmark_id": benchmark_id, "label": run_label, "status": status, "rated": rated},
        "allocation": allocation.to_json(),
        "engine_files": [file.to_json() for file in engine_files],
        "games": {"scheduled": scheduled, "total": len(rows), **counts},
        "leaderboard_status": leaderboard_status,
    }
