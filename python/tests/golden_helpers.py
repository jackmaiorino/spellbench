"""Golden transcript helpers (protocol v2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from spellbench import wire
from spellbench.bot import BotSession

GOLDENS_V2_DIR = Path(__file__).resolve().parents[2] / "goldens" / "protocol_v2"


def _parse(line: bytes) -> Any:
    try:
        return wire.strict_json_loads(line)
    except Exception:
        return line.decode("utf-8", errors="replace")      # a malformed_json probe is kept as text


def load_transcript_v2(name: str) -> list[tuple[str, Any]]:
    rows = [wire.strict_json_loads(line) for line in (GOLDENS_V2_DIR / name).read_bytes().splitlines()]
    return [(row["dir"], row["message"]) for row in rows]


def golden_index() -> dict[str, dict]:
    return json.loads((GOLDENS_V2_DIR / "index.json").read_bytes())["transcripts"]


class RecordingPeer:
    def __init__(self, inner, rows: list, out_dir: str, in_dir: str) -> None:
        self.inner, self.rows, self.out_dir, self.in_dir = inner, rows, out_dir, in_dir

    def write_line(self, payload: bytes) -> None:
        self.rows.append((self.out_dir, _parse(payload)))
        self.inner.write_line(payload)

    def read_line(self) -> bytes:
        line = self.inner.read_line()
        self.rows.append((self.in_dir, _parse(line)))
        return line

    def set_timeout(self, seconds) -> None:
        setter = getattr(self.inner, "set_timeout", None)
        if setter is not None:
            setter(seconds)

    def close(self) -> None:
        self.inner.close()


class InProcessBot:
    """A Peer served by a BotSession, so agent transcripts need no subprocess."""

    def __init__(self, session: BotSession) -> None:
        self.session, self.pending = session, []

    def write_line(self, payload: bytes) -> None:
        self.pending.append(self.session.handle_line(payload))

    def read_line(self) -> bytes:
        return wire.strip_line_terminator(self.pending.pop(0))

    def close(self) -> None:
        pass
