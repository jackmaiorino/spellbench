"""Strict NDJSON framing for the spellbench wire protocol (spec sections 2 and 4.3).

Strict JSON: receivers reject duplicate object keys, fractional or non-finite
numbers (protocol numbers are integers with ``|x| <= 2^53``), non-object
top-level values, and lines longer than 8 MiB. Canonical JSON is UTF-8 with
keys sorted by code point, separators ``,`` and ``:``, and no insignificant
whitespace.
"""

from __future__ import annotations

import hashlib
import json
import queue
import subprocess
import threading
from typing import Any, Mapping, Sequence

from .errors import LineTooLongError, MalformedJsonError, TransportError, ValidationError

MAX_LINE_BYTES = 8 * 1024 * 1024
MAX_JSON_INT = 1 << 53


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise MalformedJsonError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def _reject_constant(value: str) -> None:
    raise MalformedJsonError(f"non-finite JSON constant rejected: {value}")


def _reject_float(value: str) -> None:
    raise MalformedJsonError(f"fractional JSON number rejected: {value}")


def _parse_int(value: str) -> int:
    parsed = int(value)
    if abs(parsed) > MAX_JSON_INT:
        raise MalformedJsonError(f"JSON integer outside |x| <= 2^53: {value}")
    return parsed


def strict_json_loads(line: bytes | str) -> dict[str, Any]:
    """Parse one line of strict JSON; the top level must be an object."""
    if isinstance(line, bytes):
        try:
            line = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MalformedJsonError(f"line is not valid UTF-8: {exc}") from exc
    try:
        value = json.loads(
            line,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
            parse_float=_reject_float,
            parse_int=_parse_int,
        )
    except MalformedJsonError:
        raise
    except json.JSONDecodeError as exc:
        raise MalformedJsonError(f"line is not strict JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise MalformedJsonError("top-level JSON value is not an object")
    return value


def _assert_canonical_tree(value: Any, context: str = "$") -> None:
    if value is None or type(value) is bool or type(value) is str:
        return
    if type(value) is int:
        if abs(value) > MAX_JSON_INT:
            raise ValidationError(f"{context} integer outside |x| <= 2^53: {value}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _assert_canonical_tree(child, f"{context}[{index}]")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if type(key) is not str:
                raise ValidationError(f"{context} has a non-string key: {key!r}")
            _assert_canonical_tree(child, f"{context}.{key}")
        return
    raise ValidationError(f"{context} is not canonical JSON: {type(value).__name__}")


def canonical_json_dumps(value: Any) -> bytes:
    """Canonical JSON (spec section 4.3): sorted keys, compact separators, UTF-8."""
    _assert_canonical_tree(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_line(value: Any) -> bytes:
    """One framed NDJSON line: canonical JSON plus the ``\\n`` terminator."""
    return canonical_json_dumps(value) + b"\n"


def candidates_sha256(candidates: Sequence[Mapping[str, Any]]) -> str:
    """SHA-256 over the candidates reduced to semantic content (spec section 4.3).

    ``display_text`` is excluded; the reduction is an array of
    ``{"candidate_id": <id>, "semantic": {...}}`` in decision order.
    """
    reduced = [
        {"candidate_id": candidate["candidate_id"], "semantic": candidate["semantic"]}
        for candidate in candidates
    ]
    return hashlib.sha256(canonical_json_dumps(reduced)).hexdigest()


def strip_line_terminator(line: bytes) -> bytes:
    """Remove the ``\\n`` terminator (a single trailing ``\\r`` is tolerated)."""
    if line.endswith(b"\n"):
        line = line[:-1]
        if line.endswith(b"\r"):
            line = line[:-1]
    return line


def read_line(stream: Any, *, max_line_bytes: int = MAX_LINE_BYTES) -> bytes | None:
    """Read one framed line from a binary stream; ``None`` at clean EOF.

    The returned payload excludes the terminator. A line longer than
    ``max_line_bytes`` or missing its terminator at EOF is rejected.
    """
    line = stream.readline(max_line_bytes + 1)
    if line == b"":
        return None
    if len(line) > max_line_bytes:
        raise LineTooLongError(f"line exceeds {max_line_bytes} bytes")
    if not line.endswith(b"\n"):
        raise MalformedJsonError("line missing \\n terminator before EOF")
    return strip_line_terminator(line)


def _stdout_reader(stream: Any, output: "queue.Queue[bytes | BaseException]", max_line_bytes: int) -> None:
    try:
        while True:
            line = stream.readline()
            if line == b"":
                output.put(b"")
                return
            if len(line) > max_line_bytes:
                output.put(LineTooLongError(f"stdout line exceeds {max_line_bytes} bytes"))
                return
            output.put(strip_line_terminator(line))
    except BaseException as exc:
        output.put(exc)


def _stderr_reader(stream: Any, chunks: list[bytes]) -> None:
    while True:
        chunk = stream.readline()
        if chunk == b"":
            return
        chunks.append(chunk)


class SubprocessPeer:
    """A child-process peer with framed stdin/stdout (spec section 2).

    Implements the ``Peer`` protocol used by the role clients:
    ``write_line(payload)``, ``read_line() -> bytes``, ``close()``.
    """

    def __init__(
        self,
        argv: Sequence[str],
        *,
        timeout_s: float | None = None,
        max_line_bytes: int = MAX_LINE_BYTES,
    ) -> None:
        if not argv:
            raise ValueError("argv must be nonempty")
        self._proc = subprocess.Popen(
            list(argv),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
        assert self._proc.stdin is not None
        assert self._proc.stdout is not None
        assert self._proc.stderr is not None
        self._timeout_s = timeout_s
        self._stdout: "queue.Queue[bytes | BaseException]" = queue.Queue()
        self._stderr_chunks: list[bytes] = []
        self._stdout_thread = threading.Thread(
            target=_stdout_reader,
            args=(self._proc.stdout, self._stdout, max_line_bytes),
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=_stderr_reader,
            args=(self._proc.stderr, self._stderr_chunks),
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()
        self._closed = False

    def stderr_text(self) -> str:
        return b"".join(self._stderr_chunks).decode("utf-8", errors="replace")

    def write_line(self, payload: bytes) -> None:
        if self._closed:
            raise TransportError("peer is closed")
        if self._proc.poll() is not None:
            raise TransportError(
                f"peer exited before request: code={self._proc.returncode} stderr={self.stderr_text()!r}"
            )
        assert self._proc.stdin is not None
        try:
            self._proc.stdin.write(payload + b"\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise TransportError(f"peer stdin write failed: {exc}; stderr={self.stderr_text()!r}") from exc

    def read_line(self) -> bytes:
        if self._closed:
            raise TransportError("peer is closed")
        try:
            item = self._stdout.get(timeout=self._timeout_s) if self._timeout_s is not None else self._stdout.get()
        except queue.Empty as exc:
            raise TransportError(f"timeout waiting for peer stdout; stderr={self.stderr_text()!r}") from exc
        if isinstance(item, BaseException):
            raise item
        if item == b"":
            raise TransportError(
                f"peer EOF; code={self._proc.poll()} stderr={self.stderr_text()!r}"
            )
        return item

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        proc = self._proc
        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except OSError:
            pass
        if proc.poll() is None:
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
        self._stdout_thread.join(timeout=1)
        self._stderr_thread.join(timeout=1)
        for stream in (proc.stdout, proc.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass

    def __enter__(self) -> "SubprocessPeer":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()
