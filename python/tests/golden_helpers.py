"""Golden transcript helpers (protocol v2, spec 16; Decision 7).

A golden transcript is one canonical JSON line per message, exactly ``{"dir", "message"}``, ``dir`` one of
``DIRECTIONS`` (spec 16). ``message`` is the message as parsed JSON, except for a line the host sent that is
not a strict-JSON object (the offending line of a ``malformed_json`` or non-object golden): that row holds
the line itself as a JSON string (Decision 7). The goldens' digests, engine arguments and replay roles live
in the sidecar ``index.json``.

``RecordingPeer`` records what the host writes and reads through a peer, as parsed messages (never raw
bytes, so a child's ``\\r\\n`` line ends never reach a golden); ``InProcessBot`` is a peer served by a
``BotSession``, so agent transcripts need no subprocess. ``tools/generate_goldens_v2.py`` writes the goldens
with both; ``test_goldens_v2.py`` and the replays read them back with ``load_transcript_v2`` and
``golden_index``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from spellbench import wire
from spellbench.bot import BotSession
from spellbench.errors import MalformedJsonError

GOLDENS_V2_DIR = Path(__file__).resolve().parents[2] / "goldens" / "protocol_v2"
DIRECTIONS = ("host_to_engine", "engine_to_host", "host_to_agent", "agent_to_host")


def parse_line(line: bytes) -> Any:
    """A line as a transcript row's ``message``: the strict-parsed object, or the line's text (Decision 7).

    A line that is not a strict-JSON object (``{not json``, the valid but non-object ``[1,2]``) is kept as
    its text. It must be UTF-8: a JSON string cannot carry other bytes faithfully, so they raise.
    """
    try:
        return wire.strict_json_loads(line)
    except MalformedJsonError:
        return line.decode("utf-8")


def load_transcript_v2(name: str) -> list[tuple[str, Any]]:
    """The ``(dir, message)`` rows of one golden; a row that is not exactly ``{"dir", "message"}`` raises."""
    rows = []
    for number, line in enumerate((GOLDENS_V2_DIR / name).read_bytes().splitlines(), 1):
        row = wire.strict_json_loads(line)
        if set(row) != {"dir", "message"} or row["dir"] not in DIRECTIONS:
            raise ValueError(f'{name} line {number}: a row is exactly {{"dir", "message"}} with a known dir (spec 16)')
        rows.append((row["dir"], row["message"]))
    return rows


def golden_index() -> dict[str, dict]:
    """The sidecar's ``transcripts``: each golden's engine, engine arguments, digest and roles (Decision 7)."""
    return wire.strict_json_loads((GOLDENS_V2_DIR / "index.json").read_bytes())["transcripts"]


class RecordingPeer:
    """A peer that appends ``(out_dir, message)`` for each line written and ``(in_dir, message)`` for each line read.

    ``rows`` is anything with ``append``. A write or read that fails records nothing, so a transcript holds
    only what crossed the pipe.
    """

    def __init__(self, inner: Any, rows: Any, out_dir: str, in_dir: str) -> None:
        self.inner, self.rows, self.out_dir, self.in_dir = inner, rows, out_dir, in_dir

    def write_line(self, payload: bytes) -> None:
        self.inner.write_line(payload)
        self.rows.append((self.out_dir, parse_line(payload)))

    def read_line(self) -> bytes:
        line = self.inner.read_line()
        self.rows.append((self.in_dir, parse_line(line)))
        return line

    def set_timeout(self, seconds: float | None) -> None:
        setter = getattr(self.inner, "set_timeout", None)
        if setter is not None:
            setter(seconds)

    def stderr_text(self) -> str:
        reader = getattr(self.inner, "stderr_text", None)
        return reader() if reader is not None else ""

    def close(self) -> None:
        self.inner.close()


class InProcessBot:
    """A peer served by a ``BotSession``: each written line is answered through ``handle_line``, read back in order."""

    def __init__(self, session: BotSession) -> None:
        self.session, self.pending = session, []

    def write_line(self, payload: bytes) -> None:
        self.pending.append(self.session.handle_line(payload))

    def read_line(self) -> bytes:
        return wire.strip_line_terminator(self.pending.pop(0))

    def close(self) -> None:
        pass
