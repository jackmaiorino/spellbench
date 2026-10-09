"""Verify operator transcripts against published rows, then replay every complete engine answer.

This proves the engine's behavior for recorded selections. It makes no claim
that a clock-sensitive policy chooses those selections again.
"""
from __future__ import annotations

import gzip
import hashlib
from pathlib import Path

from .. import wire
from ..conformance import _engine_exchanges, replay_engine_transcript
from ..digests import GameDigest, deck_id
from ..messages import EngineIdentity
from ..run_secret import RunSecret
from . import engine_records
from .ledger import LedgerRow


def _checked(path: Path, digest: str) -> bytes:
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError(f"recorded replay input changed: {path.name}")
    return payload


def check_exchanges(path: Path, row: LedgerRow, secret: RunSecret) -> int:
    """Bind a complete game's reset, selections, responses and digest to its published row."""
    exchanges = _engine_exchanges(path)
    if len(exchanges) < 2:
        raise ValueError("recorded replay needs hello and reset exchanges")
    hello_request, hello_answer = exchanges[0][1], exchanges[0][3]
    if (not isinstance(hello_request, dict) or hello_request.get("request_type") != "hello"
            or not isinstance(hello_answer, dict) or hello_answer.get("response_type") != "hello_ok"
            or EngineIdentity.from_json(hello_answer.get("engine")).provenance().to_json() != row.engine):
        raise ValueError("recorded hello differs from the ledger engine")
    reset, answer = exchanges[1][1], exchanges[1][3]
    if (not isinstance(reset, dict) or reset.get("request_type") != "reset"
            or reset.get("game_id") != row.game_id or reset.get("format") != row.format
            or reset.get("game_secret") != secret.game_secret(row.game_index).hex()):
        raise ValueError("recorded reset differs from the revealed game")
    seats = reset.get("seats")
    if not isinstance(seats, list) or len(seats) != 2:
        raise ValueError("recorded reset has no two deck bindings")
    for index, (seat, recorded) in enumerate(zip(seats, row.decks)):
        if not isinstance(seat, dict) or seat.get("seat") != f"p{index}" or not isinstance(seat.get("deck"), dict):
            raise ValueError("recorded reset deck is malformed")
        deck = seat["deck"]
        if deck.get("deck_id") != recorded.deck_id:
            raise ValueError("recorded reset deck identity differs from ledger")
        if "decklist" in deck:
            if deck_id(deck["decklist"]) != recorded.deck_id:
                raise ValueError("recorded reset deck differs from ledger")
        elif deck.get("catalog_id") != recorded.catalog_id:
            raise ValueError("recorded reset catalog differs from ledger")
    digest = GameDigest(reset)
    digest.add_response(answer)
    steps, last = 0, None
    for _, request, _, response in exchanges[2:]:
        if (not isinstance(request, dict) or request.get("request_type") != "step"
                or request.get("game_id") != row.game_id):
            raise ValueError("recorded game contains an unexpected request")
        digest.add_step(request, response)
        key = wire.canonical_json_dumps(request)
        if key != last:
            steps += 1
        last = key
    if row.adjudication is not None:
        digest.add_adjudication(classification=row.classification, outcome=row.outcome,
                                reason=row.reason, winner=row.winner)
    else:
        terminal = exchanges[-1][3]
        if not isinstance(terminal, dict) or terminal.get("response_type") != "terminal":
            raise ValueError("recorded game lacks its ledger terminal")
        for name in ("game_id", "classification", "outcome", "winner", "reason", "step_count", "decision_count"):
            if wire.canonical_json_dumps(terminal.get(name)) != wire.canonical_json_dumps(getattr(row, name)):
                raise ValueError(f"recorded terminal differs at {name}")
        if terminal.get("provenance") != row.engine:
            raise ValueError("recorded terminal engine differs from ledger")
    if steps != row.step_count or digest.value() != row.game_digest:
        raise ValueError("recorded selections/responses differ from ledger count or game_digest")
    return len(exchanges)


def materialize(record: dict, row: LedgerRow, recording_identity: dict, scratch: Path,
                *, cap_bytes: int, guard=None) -> Path:
    """Read one hash-bound durable record, keeping decompression within its declared byte ceiling."""
    if guard:
        guard()
    directory = Path(record["directory"])
    ready_bytes = _checked(directory / "READY.json", record["ready_sha256"])
    ready = wire.strict_json_loads(ready_bytes)
    row_bytes = _checked(directory / "ROW.json", record["row_sha256"])
    if row_bytes != wire.canonical_json_dumps(row.to_json()):
        raise ValueError("durable record differs from the exact published ledger row")
    if (ready.get("schema") != "spellbench-engine-record-ready/v1" or ready.get("operator_only") is not True
            or ready.get("config") != recording_identity or ready.get("game_id") != row.game_id
            or ready.get("game_index") != row.game_index or ready.get("row_sha256") != record["row_sha256"]
            or ready.get("row_bytes") != len(row_bytes)):
        raise ValueError("durable READY differs from ledger or declared recording configuration")
    ack = wire.strict_json_loads(_checked(directory / "COLLECTED.json", record["collected_sha256"]))
    expected = engine_records.acknowledgement(ready, directory.name, record["ready_sha256"])
    if any(ack.get(key) != value for key, value in expected.items()):
        raise ValueError("durable collection acknowledgment differs from READY")
    size = ready.get("transcript_bytes")
    if type(size) is not int or not 0 < size <= cap_bytes:
        raise ValueError("recorded replay trace exceeds its declared byte cap")
    compressed = recording_identity["settings"].get("transport", {}).get("compression") == "gzip"
    trace = directory / ("engine.jsonl.gz" if compressed else "engine.jsonl")
    expected_hash = ack.get("compressed_sha256") if compressed else ready["transcript_sha256"]
    if engine_records.sha(trace) != expected_hash or (compressed and trace.stat().st_size != ack.get("compressed_bytes")):
        raise ValueError("durable trace differs from collection acknowledgment")
    scratch.mkdir(parents=True, exist_ok=False)
    target = scratch / "engine.jsonl"
    total, digest = 0, hashlib.sha256()
    # Stop before writing a byte beyond the bound, including malformed gzip streams.
    with (gzip.open(trace, "rb") if compressed else trace.open("rb")) as source, target.open("xb") as output:
        while block := source.read(min(1024 * 1024, size - total + 1)):
            if guard:
                guard()
            total += len(block)
            if total > size:
                raise ValueError("durable trace expands beyond READY byte count")
            output.write(block)
            digest.update(block)
    if total != size or digest.hexdigest() != ready["transcript_sha256"]:
        raise ValueError("durable trace does not reconstruct the complete recorded bytes")
    return target


def replay_record(record: dict, row: LedgerRow, secret: RunSecret, recording_identity: dict,
                  command, scratch: Path, *, cap_bytes: int, timeout_s: float, guard=None) -> dict:
    path = materialize(record, row, recording_identity, scratch, cap_bytes=cap_bytes, guard=guard)
    count = check_exchanges(path, row, secret)
    if guard:
        guard()
    mismatches = replay_engine_transcript(engine_records.work_command(list(command), scratch / "engine-work"),
                                         path, timeout_s=timeout_s)
    if mismatches:
        raise ValueError("complete engine response replay differs: " + "; ".join(mismatches))
    work = scratch / "engine-work"
    if work.exists() and any(work.iterdir()):
        raise ValueError("replay private engine database remains after cleanup")
    if guard:
        guard()
    return {"game_index": row.game_index, "game_id": row.game_id,
            "row_sha256": record["row_sha256"], "transcript_sha256": engine_records.sha(path),
            "engine_exchanges_replayed": count, "engine_replay_identical": True,
            "policy_repeat_identical": None, "model_requests": 0}
