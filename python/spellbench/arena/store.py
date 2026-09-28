"""Canonical JSON tournament artifacts and atomic publish (spec section 4.3).

All arena artifacts are canonical JSON: UTF-8, keys sorted by code point,
compact separators, integers only (floats are rejected by
:func:`spellbench.wire.canonical_json_dumps`, so ratings are stored as
fixed-point integers and ratios as ``{"num": ..., "den": ...}`` pairs).

Schema identities:

- ``spellbench-tournament/v1``: ``manifest.json``, the publish boundary.
- ``spellbench-match-ledger/v1``: ``matches.jsonl``, one row per game.
- ``spellbench-bot-registry/v1``: ``registry.json``.
- ``spellbench-leaderboard/v1``: ``leaderboard.json``.
- ``spellbench-tournament-config/v1``: ``config.json``, the normalized
  canonical copy of the run configuration.

Atomic publish: every data file is written (and fsynced) first;
``manifest.json``, which carries the sha256 and byte count of each data
file, is written last. A directory with a manifest is a complete,
verifiable tournament; a directory without one is partial.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .. import models
from ..errors import ValidationError
from ..wire import MAX_JSON_INT, canonical_json_dumps, strict_json_loads

TOURNAMENT_SCHEMA = "spellbench-tournament/v1"
LEDGER_SCHEMA = "spellbench-match-ledger/v1"
REGISTRY_SCHEMA = "spellbench-bot-registry/v1"
LEADERBOARD_SCHEMA = "spellbench-leaderboard/v1"
CONFIG_SCHEMA = "spellbench-tournament-config/v1"

MANIFEST_NAME = "manifest.json"
CONFIG_NAME = "config.json"
REGISTRY_NAME = "registry.json"
LEDGER_NAME = "matches.jsonl"
LEADERBOARD_JSON_NAME = "leaderboard.json"
LEADERBOARD_MD_NAME = "LEADERBOARD.md"
# Raw failure text (peer stderr, OS errors) per adjudicated game. Deliberately
# outside the manifest: it is not deterministic and not part of the result.
DIAGNOSTICS_NAME = "diagnostics.jsonl"

# Data files in publish order; the manifest is always last.
DATA_FILE_NAMES = (
    CONFIG_NAME,
    REGISTRY_NAME,
    LEDGER_NAME,
    LEADERBOARD_JSON_NAME,
    LEADERBOARD_MD_NAME,
)


class StoreError(Exception):
    """A tournament artifact store operation failed."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    """Canonical JSON bytes (spec section 4.3); rejects floats and non-JSON types."""
    return canonical_json_dumps(value)


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically (same-directory tmp + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def write_json_atomic(path: Path, value: Any) -> bytes:
    """Write one canonical JSON document; returns the bytes written."""
    data = canonical_bytes(value) + b"\n"
    write_bytes_atomic(path, data)
    return data


def append_ledger_row(path: Path, row: Any) -> None:
    """Append one canonical JSON line to the match ledger and flush."""
    line = canonical_bytes(row) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def append_diagnostics(path: Path, game_id: str, diagnostics: Iterable[str]) -> None:
    """Append one diagnostics record (ASCII-escaped JSON; never hashed)."""
    line = json.dumps({"game_id": game_id, "diagnostics": list(diagnostics)}, ensure_ascii=True)
    with open(path, "a", encoding="ascii", newline="\n") as handle:
        handle.write(line + "\n")


def file_entry(path: Path, name: str) -> dict[str, Any]:
    """The manifest entry for one data file: name, sha256, byte count."""
    data = path.read_bytes()
    return {"path": name, "sha256": sha256_hex(data), "bytes": len(data)}


def publish_manifest(directory: Path, manifest: dict[str, Any]) -> bytes:
    """Write ``manifest.json``, the publish boundary, always last.

    The caller must have written (and flushed) every data file listed in
    ``manifest["files"]`` before calling this.
    """
    if manifest.get("schema") != TOURNAMENT_SCHEMA:
        raise StoreError(f"manifest schema must be {TOURNAMENT_SCHEMA!r}")
    return write_json_atomic(directory / MANIFEST_NAME, manifest)


def read_json(path: Path, *, schema: str | None = None) -> dict[str, Any]:
    """Read one single-line canonical JSON document, fail closed."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise StoreError(f"cannot read {path}: {exc}") from exc
    lines = raw.split(b"\n")
    if len(lines) > 2 or (len(lines) == 2 and lines[1] != b""):
        raise StoreError(f"{path} is not a single-line canonical JSON document")
    try:
        value = strict_json_loads(lines[0])
    except Exception as exc:
        raise StoreError(f"{path} is not strict JSON: {exc}") from exc
    if schema is not None and value.get("schema") != schema:
        raise StoreError(f"{path} schema must be {schema!r}, got {value.get('schema')!r}")
    return value


def read_jsonl(path: Path, *, schema: str | None = None) -> list[dict[str, Any]]:
    """Read an NDJSON artifact, validating the schema tag of every row."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise StoreError(f"cannot read {path}: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(raw.split(b"\n")):
        if line == b"":
            continue
        try:
            value = strict_json_loads(line)
        except Exception as exc:
            raise StoreError(f"{path} line {index + 1} is not strict JSON: {exc}") from exc
        if schema is not None and value.get("schema") != schema:
            raise StoreError(
                f"{path} line {index + 1} schema must be {schema!r}, got {value.get('schema')!r}"
            )
        rows.append(value)
    return rows


def prepare_tournament_dir(directory: Path) -> None:
    """Fail closed unless ``directory`` is absent or empty (no overwrite of runs)."""
    if directory.exists():
        if not directory.is_dir():
            raise StoreError(f"tournament dir path is not a directory: {directory}")
        if any(directory.iterdir()):
            raise StoreError(f"tournament dir is not empty (refusing to overwrite): {directory}")
    else:
        directory.mkdir(parents=True)


def is_published(directory: Path) -> bool:
    return (directory / MANIFEST_NAME).is_file()


def verify_file_digests(directory: Path, manifest: dict[str, Any]) -> list[str]:
    """Recompute every manifest file digest; returns a list of mismatches."""
    failures: list[str] = []
    files = manifest.get("files")
    if not isinstance(files, list):
        return ["manifest.files is missing or not a list"]
    seen: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "bytes"}:
            failures.append(f"invalid manifest file entry: {entry!r}")
            continue
        name = entry["path"]
        if type(name) is not str or name in seen:
            failures.append(f"invalid or duplicate manifest path: {name!r}")
            continue
        seen.add(name)
        path = directory / name
        if not path.is_file():
            failures.append(f"missing file: {name}")
            continue
        actual = file_entry(path, name)
        if actual["sha256"] != entry["sha256"] or actual["bytes"] != entry["bytes"]:
            failures.append(f"digest mismatch: {name}")
    return failures


def require_keys(value: dict[str, Any], expected: Iterable[str], context: str) -> None:
    """Exact-key-set validation for arena artifact objects (fail closed)."""
    expected_set = set(expected)
    actual = set(value)
    if actual != expected_set:
        raise ValidationError(
            f"{context}: fields mismatch: missing={sorted(expected_set - actual)} "
            f"extra={sorted(actual - expected_set)}"
        )


# ---------------------------------------------------------------------------
# Match ledger rows (matches.jsonl, schema spellbench-match-ledger/v1)
# ---------------------------------------------------------------------------

LEDGER_OUTCOMES = frozenset({"p0_win", "p1_win", "draw", "truncated", "halted"})
LEDGER_CLASSIFICATIONS = frozenset({"natural", "truncated", "halted", "forfeit"})
FORFEIT_CAUSES = frozenset(
    {"timeout", "malformed_response", "invalid_selection", "agent_error", "transport_error"}
)

_NATURAL_WINNERS = {"p0_win": "p0", "p1_win": "p1", "draw": None}


def _req_str(value: Any, context: str) -> str:
    if type(value) is not str or not value:
        raise ValidationError(f"{context}: must be a nonempty string")
    return value


def _req_uint(value: Any, context: str) -> int:
    if type(value) is not int or value < 0 or value > MAX_JSON_INT:
        raise ValidationError(f"{context}: must be an integer in [0, 2^53]")
    return value


def _req_seat(value: Any, context: str) -> str:
    seat = _req_str(value, context)
    if seat not in models.SEATS:
        raise ValidationError(f"{context}: must be p0 or p1")
    return seat


@dataclass(frozen=True)
class LedgerSeat:
    seat: str
    bot_id: str
    name: str
    version: str

    def to_json(self) -> dict[str, Any]:
        return {"seat": self.seat, "bot_id": self.bot_id, "name": self.name, "version": self.version}

    @classmethod
    def from_json(cls, value: Any, context: str) -> "LedgerSeat":
        if not isinstance(value, dict):
            raise ValidationError(f"{context}: must be an object")
        require_keys(value, ["seat", "bot_id", "name", "version"], context)
        return cls(
            seat=_req_seat(value["seat"], f"{context}.seat"),
            bot_id=_req_str(value["bot_id"], f"{context}.bot_id"),
            name=_req_str(value["name"], f"{context}.name"),
            version=_req_str(value["version"], f"{context}.version"),
        )


@dataclass(frozen=True)
class Adjudication:
    """A host-adjudicated result (the engine produced no terminal for it).

    ``kind == "forfeit"`` carries ``cause`` (one of FORFEIT_CAUSES) and
    ``loser_seat``; ``kind == "engine_halt"`` records a host-detected engine
    contract failure with a ``detail`` message only.
    """

    kind: str
    detail: str
    cause: str | None = None
    loser_seat: str | None = None

    def to_json(self) -> dict[str, Any]:
        if self.kind == "forfeit":
            return {
                "kind": "forfeit",
                "cause": self.cause,
                "loser_seat": self.loser_seat,
                "detail": self.detail,
            }
        return {"kind": self.kind, "detail": self.detail}

    @classmethod
    def from_json(cls, value: Any, context: str) -> "Adjudication":
        if not isinstance(value, dict):
            raise ValidationError(f"{context}: must be an object")
        kind = value.get("kind")
        if kind == "forfeit":
            require_keys(value, ["kind", "cause", "loser_seat", "detail"], context)
            cause = _req_str(value["cause"], f"{context}.cause")
            if cause not in FORFEIT_CAUSES:
                raise ValidationError(f"{context}.cause: must be one of {sorted(FORFEIT_CAUSES)}")
            return cls(
                kind="forfeit",
                cause=cause,
                loser_seat=_req_seat(value["loser_seat"], f"{context}.loser_seat"),
                detail=_req_str(value["detail"], f"{context}.detail"),
            )
        if kind == "engine_halt":
            require_keys(value, ["kind", "detail"], context)
            return cls(kind="engine_halt", detail=_req_str(value["detail"], f"{context}.detail"))
        raise ValidationError(f"{context}.kind: must be forfeit or engine_halt")


@dataclass(frozen=True)
class LedgerRow:
    """One completed (or adjudicated) game in the match ledger.

    Natural rows (spec section 7.5) and forfeit rows are rated: a forfeit is
    a loss for the seat that forfeited, or a losing bot could erase its
    losses by hanging or answering garbage. Truncated and halted rows are
    recorded and excluded from the rating fit.
    """

    game_id: str
    matchup_index: int
    pair_index: int
    game_index: int
    format: str
    game_seed: int
    seats: tuple[LedgerSeat, LedgerSeat]
    decks: tuple[dict[str, Any], dict[str, Any]]
    outcome: str
    classification: str
    winner: str | None
    winner_bot_id: str | None
    reason: str
    adjudication: Adjudication | None
    step_count: int
    decision_count: int
    engine: models.Provenance

    def __post_init__(self) -> None:
        _req_str(self.game_id, "ledger.game_id")
        _req_uint(self.matchup_index, "ledger.matchup_index")
        _req_uint(self.pair_index, "ledger.pair_index")
        if self.game_index not in (0, 1):
            raise ValidationError("ledger.game_index: must be 0 or 1")
        _req_str(self.format, "ledger.format")
        _req_uint(self.game_seed, "ledger.game_seed")
        if len(self.seats) != 2 or {seat.seat for seat in self.seats} != set(models.SEATS):
            raise ValidationError("ledger.seats: must cover exactly p0 and p1")
        for index, deck in enumerate(self.decks):
            models.Deck.from_json(deck, f"ledger.decks[{index}]")
        if self.outcome not in LEDGER_OUTCOMES:
            raise ValidationError(f"ledger.outcome: must be one of {sorted(LEDGER_OUTCOMES)}")
        if self.classification not in LEDGER_CLASSIFICATIONS:
            raise ValidationError(
                f"ledger.classification: must be one of {sorted(LEDGER_CLASSIFICATIONS)}"
            )
        _req_str(self.reason, "ledger.reason")
        _req_uint(self.step_count, "ledger.step_count")
        _req_uint(self.decision_count, "ledger.decision_count")
        seat_of = {seat.seat: seat for seat in self.seats}
        if self.classification == "natural":
            if self.outcome not in _NATURAL_WINNERS:
                raise ValidationError("ledger: a natural row has outcome p0_win, p1_win, or draw")
            if self.winner != _NATURAL_WINNERS[self.outcome]:
                raise ValidationError("ledger: natural outcome/winner mismatch")
            if self.adjudication is not None:
                raise ValidationError("ledger: a natural row carries no adjudication")
        elif self.classification in ("truncated", "halted"):
            # Spec 7.5: winner is null "when unassigned by rule"; an engine may
            # name one at a cap. Recorded as reported, never rated.
            if self.outcome != self.classification:
                raise ValidationError("ledger: truncated/halted rows carry the matching outcome")
            if self.classification == "truncated" and self.adjudication is not None:
                raise ValidationError("ledger: a truncated row carries no adjudication")
            if self.classification == "halted" and self.adjudication is not None and self.adjudication.kind != "engine_halt":
                raise ValidationError("ledger: a halted row carries at most an engine_halt adjudication")
        else:  # forfeit
            if self.outcome not in ("p0_win", "p1_win"):
                raise ValidationError("ledger: a forfeit row has outcome p0_win or p1_win")
            if self.winner != _NATURAL_WINNERS[self.outcome]:
                raise ValidationError("ledger: forfeit outcome/winner mismatch")
            if self.adjudication is None or self.adjudication.kind != "forfeit":
                raise ValidationError("ledger: a forfeit row requires a forfeit adjudication")
            expected_loser = "p1" if self.winner == "p0" else "p0"
            if self.adjudication.loser_seat != expected_loser:
                raise ValidationError("ledger: forfeit loser_seat must be the non-winning seat")
        if self.winner is None:
            if self.winner_bot_id is not None:
                raise ValidationError("ledger: winner_bot_id requires a winner")
        else:
            expected_bot = seat_of[self.winner].bot_id
            if self.winner_bot_id != expected_bot:
                raise ValidationError("ledger: winner_bot_id does not match the winning seat")

    @property
    def rated(self) -> bool:
        """Natural terminals and forfeits enter ratings."""
        return self.classification in ("natural", "forfeit")

    @property
    def pair_slot(self) -> int:
        """The game's slot in its seat-swapped pair; v1 records it as ``game_index``."""
        return self.game_index

    def bot_id_at(self, seat: str) -> str:
        for entry in self.seats:
            if entry.seat == seat:
                return entry.bot_id
        raise KeyError(seat)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": LEDGER_SCHEMA,
            "game_id": self.game_id,
            "matchup_index": self.matchup_index,
            "pair_index": self.pair_index,
            "game_index": self.game_index,
            "format": self.format,
            "game_seed": self.game_seed,
            "seats": [seat.to_json() for seat in sorted(self.seats, key=lambda seat: seat.seat)],
            "decks": [self.decks[0], self.decks[1]],
            "outcome": self.outcome,
            "classification": self.classification,
            "winner": self.winner,
            "winner_bot_id": self.winner_bot_id,
            "reason": self.reason,
            "adjudication": None if self.adjudication is None else self.adjudication.to_json(),
            "step_count": self.step_count,
            "decision_count": self.decision_count,
            "engine": self.engine.to_json(),
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "ledger") -> "LedgerRow":
        if not isinstance(value, dict):
            raise ValidationError(f"{context}: must be an object")
        require_keys(
            value,
            [
                "schema",
                "game_id",
                "matchup_index",
                "pair_index",
                "game_index",
                "format",
                "game_seed",
                "seats",
                "decks",
                "outcome",
                "classification",
                "winner",
                "winner_bot_id",
                "reason",
                "adjudication",
                "step_count",
                "decision_count",
                "engine",
            ],
            context,
        )
        if value["schema"] != LEDGER_SCHEMA:
            raise ValidationError(f'{context}.schema: must be "{LEDGER_SCHEMA}"')
        raw_seats = value["seats"]
        if not isinstance(raw_seats, list) or len(raw_seats) != 2:
            raise ValidationError(f"{context}.seats: must be a list of two")
        seats = tuple(
            sorted(
                (LedgerSeat.from_json(item, f"{context}.seats[{i}]") for i, item in enumerate(raw_seats)),
                key=lambda seat: seat.seat,
            )
        )
        raw_decks = value["decks"]
        if not isinstance(raw_decks, list) or len(raw_decks) != 2:
            raise ValidationError(f"{context}.decks: must be a list of two (p0 first)")
        winner = value["winner"]
        adjudication = value["adjudication"]
        return cls(
            game_id=value["game_id"],
            matchup_index=value["matchup_index"],
            pair_index=value["pair_index"],
            game_index=value["game_index"],
            format=value["format"],
            game_seed=value["game_seed"],
            seats=(seats[0], seats[1]),
            decks=(raw_decks[0], raw_decks[1]),
            outcome=value["outcome"],
            classification=value["classification"],
            winner=None if winner is None else _req_seat(winner, f"{context}.winner"),
            winner_bot_id=value["winner_bot_id"],
            reason=value["reason"],
            adjudication=None if adjudication is None else Adjudication.from_json(adjudication, f"{context}.adjudication"),
            step_count=value["step_count"],
            decision_count=value["decision_count"],
            engine=models.Provenance.from_json(value["engine"], f"{context}.engine"),
        )


def parse_ledger(rows: Iterable[dict[str, Any]]) -> tuple[LedgerRow, ...]:
    return tuple(LedgerRow.from_json(row, f"ledger[{index}]") for index, row in enumerate(rows))
