"""Strict NDJSON framing for the spellbench wire protocol (spec sections 2 and 4.3).

Strict JSON (spec 2): receivers reject duplicate object keys, fractional or
non-finite numbers (protocol numbers are integers with ``|x| <= 2^53 - 1``),
nesting deeper than 64 levels, unpaired surrogate escapes, non-object
top-level values, and lines longer than 8 MiB. Canonical JSON is RFC 8785
(spec 4.3): UTF-8 with keys sorted by UTF-16 code units, separators ``,``
and ``:``, and no insignificant whitespace.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import threading
from typing import Any, Iterator, Mapping, Sequence

from .errors import (
    LineTooLongError,
    MalformedJsonError,
    PeerTimeoutError,
    TransportError,
    ValidationError,
)

MAX_LINE_BYTES = 8 * 1024 * 1024
MAX_JSON_INT = (1 << 53) - 1
MAX_NESTING = 64
# A JSON integer literal has no leading zeros, so one with more digits than
# MAX_JSON_INT is out of range whatever its value.
_MAX_JSON_INT_DIGITS = len(str(MAX_JSON_INT))
# How much of an out-of-range integer literal an error message quotes.
_QUOTED_INT_CHARS = 32
# read_line discards the rest of an oversized line in reads of at most this many bytes.
_DISCARD_CHUNK_BYTES = 64 * 1024
# A peer's stderr is diagnostics only; keep a bounded prefix of it.
STDERR_CAPTURE_BYTES = 64 * 1024


class NotAnObjectError(MalformedJsonError):
    """A strict-JSON line whose top-level value is not an object.

    Spec 9.8 answers it with ``malformed_request``, not ``malformed_json``: the
    line is valid JSON. A subclass, so callers catching MalformedJsonError keep working.
    """


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
    # Count the digits before converting: int() raises a bare ValueError past
    # CPython's integer string-conversion limit (4300 digits by default), and
    # a long literal is out of range anyway.
    digits = len(value) - 1 if value.startswith("-") else len(value)
    if digits <= _MAX_JSON_INT_DIGITS:
        parsed = int(value)
        if abs(parsed) <= MAX_JSON_INT:
            return parsed
    quoted = value
    if len(value) > _QUOTED_INT_CHARS:
        quoted = f"{value[:_QUOTED_INT_CHARS]}... ({digits} digits)"
    raise MalformedJsonError(f"JSON integer outside |x| <= 2^53 - 1: {quoted}")


_SURROGATE_ESCAPE = re.compile(r"\\u[dD][89a-fA-F]")
# A str holding a surrogate code point cannot be encoded as UTF-8.
_LONE_SURROGATE = re.compile(r"[\ud800-\udfff]")


def _encodable(value: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise MalformedJsonError("string contains a lone surrogate escape") from exc


def _check_tree(value: Any, *, check_strings: bool) -> None:
    """Nesting at most MAX_NESTING levels (the top-level object is level 1); strings encodable.

    Iterative: json accepts nesting deeper than the interpreter's recursion limit. The
    stack holds one iterator per open container, so memory grows with depth, not width;
    a container met while the stack holds d iterators is at level d.
    """
    stack: list[Iterator[Any]] = [iter((value,))]
    while stack:
        for item in stack[-1]:
            if isinstance(item, (dict, list)):
                if len(stack) > MAX_NESTING:
                    raise MalformedJsonError(f"JSON nesting deeper than {MAX_NESTING} levels")
                if check_strings and isinstance(item, dict):
                    for key in item:
                        _encodable(key)
                if item:
                    stack.append(iter(item.values() if isinstance(item, dict) else item))
                    break
            elif check_strings and isinstance(item, str):
                _encodable(item)
        else:
            stack.pop()


def strict_json_loads(line: bytes | str) -> dict[str, Any]:
    """Parse one line of strict JSON (spec 2); the top level must be an object.

    Raises MalformedJsonError (``malformed_json``), or its subclass
    NotAnObjectError (``malformed_request``, spec 9.8) for a line that passes
    every strict-JSON check but whose top level is not an object. The
    strict-JSON checks run first, so a line that breaks them is
    ``malformed_json`` whatever its top level and whichever layer finds it.
    """
    if isinstance(line, bytes):
        try:
            line = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MalformedJsonError(f"line is not valid UTF-8: {exc}") from exc
    elif isinstance(line, str) and _LONE_SURROGATE.search(line):
        # UTF-8 bytes cannot carry a lone surrogate (decoding rejects it), but a str can.
        raise MalformedJsonError("line contains a lone surrogate, which UTF-8 cannot encode")
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
    except RecursionError as exc:
        # json stops at the interpreter's recursion limit; same message as the walk below.
        raise MalformedJsonError(f"JSON nesting deeper than {MAX_NESTING} levels") from exc
    _check_tree(value, check_strings=bool(_SURROGATE_ESCAPE.search(line)))
    if not isinstance(value, dict):
        raise NotAnObjectError("top-level JSON value is not an object")
    return value


def _context(path: list[Any], step: Any) -> str:
    """The error context of an item, as ``$.key[index]``; ``None`` marks the root."""
    return "$" + "".join(f"[{part}]" if type(part) is int else f".{part}" for part in (*path, step) if part is not None)


def _assert_canonical_tree(value: Any) -> bool:
    """Validate a tree for canonical output; True when some key holds a non-BMP character.

    Nesting is bounded as in strict_json_loads, so canonical output is always strict
    JSON, and a cyclic structure fails here instead of looping. The stack holds one
    iterator per open container and error contexts are built only when raising, so
    memory grows with depth, not width.
    """
    astral = False
    path: list[Any] = []  # the step (index or key) of each open container; None for the root
    stack: list[Iterator[tuple[Any, Any]]] = [iter(((None, value),))]
    while stack:
        for step, item in stack[-1]:
            if item is None or type(item) is bool:
                continue
            if type(item) is int:
                if abs(item) > MAX_JSON_INT:
                    raise ValidationError(f"{_context(path, step)} integer outside |x| <= 2^53 - 1: {item}")
            elif type(item) is str:
                # isascii() is O(1): only non-ASCII strings pay for the scan.
                if not item.isascii() and _LONE_SURROGATE.search(item):
                    raise ValidationError(f"{_context(path, step)} string contains a lone surrogate")
            elif isinstance(item, (list, dict)):
                if len(stack) > MAX_NESTING:
                    raise ValidationError(f"{_context(path, step)} nesting deeper than {MAX_NESTING} levels")
                if isinstance(item, dict):
                    for key in item:
                        if type(key) is not str:
                            raise ValidationError(f"{_context(path, step)} has a non-string key: {key!r}")
                        if not key.isascii():
                            if _LONE_SURROGATE.search(key):
                                raise ValidationError(f"{_context(path, step)} key string contains a lone surrogate")
                            astral = astral or max(map(ord, key)) > 0xFFFF
                    children: Iterator[tuple[Any, Any]] = iter(item.items())
                else:
                    children = enumerate(item)
                if item:
                    path.append(step)
                    stack.append(children)
                    break
            else:
                raise ValidationError(f"{_context(path, step)} is not canonical JSON: {type(item).__name__}")
        else:
            stack.pop()
            if path:
                path.pop()
    return astral


def _dumps_utf16(value: Any) -> str:
    if isinstance(value, dict):
        keys = sorted(value, key=lambda key: key.encode("utf-16-be"))
        return "{" + ",".join(json.dumps(key, ensure_ascii=False) + ":" + _dumps_utf16(value[key]) for key in keys) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_dumps_utf16(child) for child in value) + "]"
    return json.dumps(value, ensure_ascii=False)


def canonical_json_dumps(value: Any) -> bytes:
    """RFC 8785 (spec 4.3): keys by UTF-16 code units, compact, integers only, raw UTF-8.

    json's escaping already matches RFC 8785 (``\\"`` and ``\\\\``, short escapes for
    \\b \\f \\n \\r \\t, lowercase \\u00xx for other control characters, nothing else
    escaped). Code point order equals UTF-16 order unless a key holds a non-BMP character.
    """
    if _assert_canonical_tree(value):
        return _dumps_utf16(value).encode("utf-8")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


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

    The returned payload excludes the terminator. A line missing its terminator at
    EOF is rejected. A line longer than ``max_line_bytes`` is rejected once, after the
    rest of it (through its terminator, or to EOF) is discarded in bounded reads, so
    the next call starts at the next line (spec 2: one response per request line).
    """
    line = stream.readline(max_line_bytes + 1)
    if line == b"":
        return None
    if len(line) > max_line_bytes:
        while line and not line.endswith(b"\n"):
            line = stream.readline(min(_DISCARD_CHUNK_BYTES, max_line_bytes))
        raise LineTooLongError(f"line exceeds {max_line_bytes} bytes")
    if not line.endswith(b"\n"):
        raise MalformedJsonError("line missing \\n terminator before EOF")
    return strip_line_terminator(line)


def _stdout_reader(stream: Any, output: "queue.Queue[bytes | BaseException]", max_line_bytes: int) -> None:
    try:
        while True:
            # Bounded: a line past the cap fails without buffering the rest.
            line = stream.readline(max_line_bytes + 1)
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
    """Drain stderr (so the child never blocks on it), keeping a bounded prefix."""
    kept = 0
    while True:
        chunk = stream.read1(65536)
        if chunk == b"":
            return
        if kept < STDERR_CAPTURE_BYTES:
            chunk = chunk[: STDERR_CAPTURE_BYTES - kept]
            chunks.append(chunk)
            kept += len(chunk)


def _kill_process_tree(proc: "subprocess.Popen[bytes]") -> None:
    """Kill ``proc`` and every process it started (best effort)."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


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
        env: Mapping[str, str] | None = None,
    ) -> None:
        if not argv:
            raise ValueError("argv must be nonempty")
        argv = list(argv)
        # A bare program name resolves on PATH, as a POSIX shell would. On
        # Windows, CreateProcess would first look in the running interpreter's
        # own directory, so a bare "python" could start a different Python.
        if os.path.basename(argv[0]) == argv[0]:
            argv[0] = shutil.which(argv[0]) or argv[0]
        try:
            self._proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                # POSIX: its own process group, so close() can kill the tree.
                start_new_session=os.name != "nt",
                # None inherits the host's own environment, as subprocess.Popen does by default.
                env=None if env is None else dict(env),
            )
        except OSError as exc:
            raise TransportError(f"cannot start {argv[0]!r}: {exc}") from exc
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

    def set_timeout(self, timeout_s: float | None) -> None:
        """Change the read budget, e.g. from a startup budget to a per-decision one."""
        self._timeout_s = timeout_s

    def stderr_text(self) -> str:
        return b"".join(self._stderr_chunks).decode("utf-8", errors="replace")

    def write_line(self, payload: bytes) -> None:
        """Write one framed line, bounded by the current read budget (R2-5).

        Windows pipes buffer about 4 KiB, Linux about 64 KiB, and do not support
        ``select``; a child that stops reading its stdin blocks the write once that
        buffer fills. The write runs on a daemon helper thread so it can be bounded:
        on expiry, the child is killed first (a dead reader makes the blocked write
        fail and release the buffered stream's internal lock), then this joins the
        helper thread briefly, then closes the pipes. ``close()`` is never called
        here while the helper thread may still hold that lock: closing stdin while a
        write is stuck inside it would itself block on the same lock.
        """
        if self._closed:
            raise TransportError("peer is closed")
        if self._proc.poll() is not None:
            raise TransportError(
                f"peer exited before request: code={self._proc.returncode} stderr={self.stderr_text()!r}"
            )
        assert self._proc.stdin is not None
        outcome: list[BaseException | None] = [None]
        done = threading.Event()

        def target() -> None:
            try:
                self._proc.stdin.write(payload + b"\n")
                self._proc.stdin.flush()
            except BaseException as exc:  # noqa: BLE001 - reported back to this call, once it is done
                outcome[0] = exc
            finally:
                done.set()

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        if done.wait(self._timeout_s):  # Event.wait(None) blocks until set, same as an unset budget
            exc = outcome[0]
            if isinstance(exc, (BrokenPipeError, OSError)):
                raise TransportError(f"peer stdin write failed: {exc}; stderr={self.stderr_text()!r}") from exc
            if exc is not None:
                raise exc
            return
        self._closed = True
        _kill_process_tree(self._proc)
        thread.join(2)
        try:
            if not thread.is_alive() and self._proc.stdin is not None:
                self._proc.stdin.close()
        except OSError:
            pass
        self._finish_close()
        raise PeerTimeoutError(f"timeout writing to peer stdin; stderr={self.stderr_text()!r}")

    def read_line(self) -> bytes:
        if self._closed:
            raise TransportError("peer is closed")
        try:
            item = self._stdout.get(timeout=self._timeout_s) if self._timeout_s is not None else self._stdout.get()
        except queue.Empty as exc:
            raise PeerTimeoutError(f"timeout waiting for peer stdout; stderr={self.stderr_text()!r}") from exc
        if isinstance(item, BaseException):
            raise item
        if item == b"":
            raise TransportError(
                f"peer EOF; code={self._proc.poll()} stderr={self.stderr_text()!r}"
            )
        return item

    def _finish_close(self) -> None:
        """Wait for the child to exit, then release the reader threads and their streams.

        Shared by :meth:`close` and :meth:`write_line`'s timeout path, which reaches this
        only once its own writer thread is confirmed done, so stdin is no longer held.
        """
        proc = self._proc
        if proc.poll() is None:
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                # A wrapper (.bat, sh without exec) may hold the real peer as
                # a grandchild with the pipes open: kill the whole tree.
                _kill_process_tree(proc)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        self._stdout_thread.join(timeout=1)
        self._stderr_thread.join(timeout=1)
        # Never close a pipe a reader thread is still blocked on: the close
        # would wait for that read, i.e. for whatever still holds the pipe.
        for stream, reader in ((proc.stdout, self._stdout_thread), (proc.stderr, self._stderr_thread)):
            if stream is None or reader.is_alive():
                continue
            try:
                stream.close()
            except OSError:
                pass

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
        self._finish_close()

    def __enter__(self) -> "SubprocessPeer":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()
