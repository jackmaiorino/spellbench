from __future__ import annotations

import hashlib
import io
import sys
import tracemalloc
from typing import Callable, Iterator

import pytest

from spellbench import wire
from spellbench.errors import LineTooLongError, MalformedJsonError, ValidationError


def test_canonical_dumps_sorts_keys_and_compacts() -> None:
    assert wire.canonical_json_dumps({"b": 1, "a": [True, None]}) == b'{"a":[true,null],"b":1}'


def test_canonical_dumps_unicode_is_byte_exact_utf8() -> None:
    assert wire.canonical_json_dumps({"s": "é"}) == "{\"s\":\"é\"}".encode("utf-8")


def test_strict_loads_accepts_crlf_terminated_payload() -> None:
    line = wire.strip_line_terminator(b'{"a":1}\r\n')
    assert wire.strict_json_loads(line) == {"a": 1}


@pytest.mark.parametrize(
    "line",
    [
        b'{"a":1,"a":2}',  # duplicate key
        b'{"a":1.5}',  # fractional
        b'{"a":1.0}',  # float notation is not an integer literal
        b'{"a":1e3}',  # exponent notation
        b'{"a":-0.0}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b'{"a":-Infinity}',
        b'{"a":9007199254740992}',  # 2^53
        b'{"a":-9007199254740992}',
        b'{"a":10000000000000000}',  # 17 digits
        b'{"a":-10000000000000000}',
        b"[1,2]",  # non-object top level
        b'"hello"',
        b"123",
        b"null",
        b'{"a":1} trailing',
        b'{"a":}',  # syntax error
        b'{"a":"\xff"}',  # invalid UTF-8
        b"",  # empty payload
    ],
)
def test_strict_loads_rejects(line: bytes) -> None:
    with pytest.raises(MalformedJsonError):
        wire.strict_json_loads(line)


@pytest.mark.parametrize(
    ("literal", "expected"),
    [
        (b"9007199254740991", (1 << 53) - 1),
        (b"-9007199254740991", -((1 << 53) - 1)),
        (b"1000000000000000", 10**15),  # 16 digits
        (b"0", 0),
        (b"-0", 0),
    ],
)
def test_strict_loads_accepts_safe_int_bounds(literal: bytes, expected: int) -> None:
    value = wire.strict_json_loads(b'{"a":' + literal + b"}")["a"]
    assert type(value) is int and value == expected


@pytest.mark.parametrize("sign", ["", "-"])
@pytest.mark.parametrize("digits", [4300, 4301, 5000, 100_000])
def test_strict_loads_rejects_a_huge_int_literal_as_malformed(digits: int, sign: str) -> None:
    # Past 4300 digits int() raises a bare ValueError (CPython's integer
    # string-conversion limit), which the arena would not catch as a forfeit.
    literal = sign + "".join(str(index % 10) for index in range(1, digits + 1))
    with pytest.raises(MalformedJsonError) as caught:
        wire.strict_json_loads(b'{"a":' + literal.encode("ascii") + b"}")
    message = str(caught.value)
    assert literal[:32] in message
    assert literal[:33] not in message
    assert len(message) < 128


@pytest.fixture
def strictest_int_conversion_limit() -> Iterator[None]:
    # The limit is process-wide: set the strictest one CPython accepts
    # (640 digits) and restore the previous one afterwards.
    previous = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(sys.int_info.str_digits_check_threshold)
    try:
        yield
    finally:
        sys.set_int_max_str_digits(previous)


@pytest.mark.usefixtures("strictest_int_conversion_limit")
@pytest.mark.parametrize("digits", [641, 4300])
def test_strict_loads_rejects_huge_ints_under_any_interpreter_limit(digits: int) -> None:
    # A host may run with a stricter -X int_max_str_digits; the digit count is
    # checked before any conversion, so the answer is still MalformedJsonError.
    with pytest.raises(MalformedJsonError):
        wire.strict_json_loads(b'{"a":' + b"1" * digits + b"}")


@pytest.mark.parametrize(
    "value",
    [
        {"a": 1.5},
        {"a": float("nan")},
        {"a": 9007199254740992},
        {"a": [1, {"b": float("inf")}]},
        {1: "x"},
        {"a": object()},
    ],
)
def test_canonical_dumps_rejects_non_canonical_values(value: object) -> None:
    with pytest.raises(ValidationError):
        wire.canonical_json_dumps(value)


def test_read_line_eof_returns_none() -> None:
    assert wire.read_line(io.BytesIO(b"")) is None


def test_read_line_strips_terminators() -> None:
    assert wire.read_line(io.BytesIO(b'{"a":1}\n')) == b'{"a":1}'
    assert wire.read_line(io.BytesIO(b'{"a":1}\r\n')) == b'{"a":1}'


def test_read_line_rejects_missing_terminator() -> None:
    with pytest.raises(MalformedJsonError):
        wire.read_line(io.BytesIO(b'{"a":1}'))


def test_read_line_enforces_cap() -> None:
    ok = io.BytesIO(b"x" * (wire.MAX_LINE_BYTES - 1) + b"\n")
    assert len(wire.read_line(ok)) == wire.MAX_LINE_BYTES - 1
    too_long = io.BytesIO(b"x" * wire.MAX_LINE_BYTES + b"\n")
    with pytest.raises(LineTooLongError):
        wire.read_line(too_long)


class _ReadlineSizes(io.BytesIO):
    """A stream that records the size argument of every readline call."""

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.sizes: list[int] = []

    def readline(self, size: int | None = -1) -> bytes:
        self.sizes.append(-1 if size is None else size)
        return super().readline(size)


def test_read_line_discards_the_rest_of_an_oversized_line() -> None:
    # Spec 2: one response per request line. An oversized line is rejected once and the
    # next read starts at the next line; the discarding reads are bounded.
    stream = _ReadlineSizes(b"x" * (9 << 20) + b"\n" + b'{"a":1}\n')
    with pytest.raises(LineTooLongError):
        wire.read_line(stream)
    assert wire.read_line(stream) == b'{"a":1}'
    assert wire.read_line(stream) is None
    assert all(0 < size <= wire.MAX_LINE_BYTES + 1 for size in stream.sizes)


def test_read_line_rejects_an_oversized_line_at_eof_once() -> None:
    stream = io.BytesIO(b"x" * (9 << 20))
    with pytest.raises(LineTooLongError):
        wire.read_line(stream)
    assert wire.read_line(stream) is None


def test_strict_loads_rejects_deeply_nested_json_as_malformed() -> None:
    nested = b'{"a":' + b"[" * 100_000 + b"]" * 100_000 + b"}"
    with pytest.raises(MalformedJsonError):
        wire.strict_json_loads(nested)


@pytest.mark.parametrize("escape", [rb"\ud800", rb"\uDFFF", rb"x\udc00y"])
def test_strict_loads_rejects_lone_surrogate_escapes(escape: bytes) -> None:
    # A lone surrogate cannot be encoded as UTF-8, so it could never be
    # written back out canonically.
    with pytest.raises(MalformedJsonError):
        wire.strict_json_loads(b'{"a":"' + escape + b'"}')


@pytest.mark.parametrize(
    ("opening", "innermost", "closing"),
    [(b"[", rb'"\ud800"', b"]"), (b'{"k":', rb'{"\ud800":0}', b"}")],
    ids=["value", "key"],
)
def test_deep_json_fails_on_depth_before_any_string_check(opening: bytes, innermost: bytes, closing: bytes) -> None:
    depth = 1500
    with pytest.raises(MalformedJsonError, match="nesting deeper than 64 levels"):
        wire.strict_json_loads(b'{"a":' + opening * depth + innermost + closing * depth + b"}")


def test_strict_loads_accepts_escaped_surrogate_pairs() -> None:
    assert wire.strict_json_loads(rb'{"a":"\ud83d\ude00"}') == {"a": "\U0001F600"}


def test_a_lone_surrogate_within_the_depth_limit_is_rejected() -> None:
    with pytest.raises(MalformedJsonError, match="lone surrogate"):
        wire.strict_json_loads(b'{"a":' + b"[" * 10 + rb'"\ud800"' + b"]" * 10 + b"}")


def _nested_objects(levels: int) -> bytes:
    return b'{"a":' * levels + b"0" + b"}" * levels


def test_nesting_of_64_levels_is_accepted_and_65_rejected() -> None:
    assert wire.strict_json_loads(_nested_objects(64))
    with pytest.raises(MalformedJsonError, match="nesting deeper than 64 levels"):
        wire.strict_json_loads(_nested_objects(65))


@pytest.mark.parametrize("line", [b"[1,2]", b'"hello"', b"123", b"null", b"true"])
def test_a_non_object_top_level_raises_not_an_object_error(line: bytes) -> None:
    # Valid JSON with a non-object top level is malformed_request, not malformed_json (spec 9.8).
    with pytest.raises(wire.NotAnObjectError, match="not an object"):
        wire.strict_json_loads(line)


@pytest.mark.parametrize("line", [b"[" * 65 + b"]" * 65, rb'["\ud800"]'], ids=["depth", "lone-surrogate"])
def test_a_line_breaking_strict_json_is_malformed_json_whatever_its_top_level(line: bytes) -> None:
    with pytest.raises(MalformedJsonError) as caught:
        wire.strict_json_loads(line)
    assert not isinstance(caught.value, wire.NotAnObjectError)


def test_canonical_escapes_follow_rfc_8785() -> None:
    value = {"s": "\x00\x08\x0c\n\r\t\x1f\x7f\u2028\"\\"}
    assert wire.canonical_json_dumps(value) == b'{"s":"\\u0000\\b\\f\\n\\r\\t\\u001f\x7f\xe2\x80\xa8\\"\\\\"}'


def test_canonical_keys_sort_by_utf16_code_units() -> None:
    # U+1F600 is the surrogate pair D83D DE00, which sorts before U+FFFD in UTF-16
    # (RFC 8785 section 3.2.3), although its code point is larger.
    assert wire.canonical_json_dumps({"\ufffd": 1, "\U0001F600": 2}) == b'{"\xf0\x9f\x98\x80":2,"\xef\xbf\xbd":1}'
    assert wire.canonical_json_dumps({"b": 1, "a": {"d": 1, "c": 2}}) == b'{"a":{"c":2,"d":1},"b":1}'


def test_canonical_dumps_matches_the_spec_16_vector() -> None:
    value = {"b": "Chainer's Edict", "a": "Lim-D\u00fbl's Vault", "c": "tab\there"}
    assert hashlib.sha256(wire.canonical_json_dumps(value)).hexdigest() == (
        "041575311eb1deb02f63f70361e14159034faf0d2a31e57edf8b4cf037680377"
    )


def test_canonical_dumps_rejects_a_lone_surrogate_string() -> None:
    with pytest.raises(ValidationError, match="lone surrogate"):
        wire.canonical_json_dumps({"a": "x\ud800"})


def _nested_lists(levels: int) -> list:
    value: list = []
    for _ in range(levels - 1):
        value = [value]
    return value


def test_canonical_dumps_bounds_nesting_like_strict_loads() -> None:
    # Canonical output is always strict JSON, and a cyclic structure fails instead of looping.
    assert wire.canonical_json_dumps(_nested_lists(64)) == b"[" * 64 + b"]" * 64
    with pytest.raises(ValidationError, match="nesting deeper than 64 levels"):
        wire.canonical_json_dumps(_nested_lists(65))
    cycle: list = []
    cycle.append(cycle)
    with pytest.raises(ValidationError, match="nesting deeper than 64 levels"):
        wire.canonical_json_dumps({"a": cycle})


@pytest.mark.parametrize("line", ['{"a":"\ud800"}', '{"\udc00":1}'], ids=["value", "key"])
def test_strict_loads_rejects_a_raw_lone_surrogate_in_str_input(line: str) -> None:
    # UTF-8 bytes cannot carry one (decoding rejects it), but a str can.
    with pytest.raises(MalformedJsonError, match="lone surrogate"):
        wire.strict_json_loads(line)


@pytest.mark.parametrize("value", [{"\ud800": 1}, "x\udfff", [{"a": ["\udc00"]}]], ids=["key", "top-level", "nested"])
def test_canonical_dumps_rejects_a_raw_lone_surrogate_anywhere(value: object) -> None:
    with pytest.raises(ValidationError, match="lone surrogate"):
        wire.canonical_json_dumps(value)


def test_canonical_keys_sort_by_utf16_code_units_when_the_astral_key_is_nested() -> None:
    value = [{"b": {"\ufffd": 1, "\U0001F600": 2}, "a": 0}]
    assert wire.canonical_json_dumps(value) == b'[{"a":0,"b":{"\xf0\x9f\x98\x80":2,"\xef\xbf\xbd":1}}]'


def _peak_traced_bytes(call: Callable[[], object]) -> int:
    """Peak memory traced while ``call`` runs, above what was allocated before it."""
    tracing = tracemalloc.is_tracing()
    if not tracing:
        tracemalloc.start()
    try:
        base = tracemalloc.get_traced_memory()[0]
        tracemalloc.reset_peak()
        call()
        return tracemalloc.get_traced_memory()[1] - base
    finally:
        if not tracing:
            tracemalloc.stop()


def test_wide_values_cost_memory_by_depth_not_width() -> None:
    # The walks keep one iterator per open container, not one entry per element; the
    # parse peak includes the parsed list itself (8 bytes per element).
    count = 250_000
    line = b'{"a":[' + b",".join([b"0"] * count) + b"]}"
    assert _peak_traced_bytes(lambda: wire.strict_json_loads(line)) < 6 << 20
    value = {"a": [0] * count}
    assert _peak_traced_bytes(lambda: wire.canonical_json_dumps(value)) < 4 << 20


def _peer_running(code: str, **kwargs) -> wire.SubprocessPeer:
    import sys

    return wire.SubprocessPeer([sys.executable, "-c", code], **kwargs)


def test_peer_rejects_an_oversized_line_before_it_ends() -> None:
    # The child writes more than the cap and never finishes the line; the
    # peer must fail on the cap, not buffer until a newline that never comes.
    code = "import sys, time; sys.stdout.buffer.write(b'x' * 4096); sys.stdout.flush(); time.sleep(30)"
    peer = _peer_running(code, timeout_s=5, max_line_bytes=1024)
    try:
        with pytest.raises(LineTooLongError):
            peer.read_line()
    finally:
        peer.close()


def test_peer_reads_the_next_line_after_an_oversized_one() -> None:
    # Spec 2: a line is one message. The peer rejects the oversized line, skips the rest of it, and reads the next,
    # so a bot that flooded one answer is still heard when it acks game_over, instead of costing its whole budget.
    code = ("import sys, time; sys.stdout.buffer.write(b'x' * 4096 + bytes([10]) + b'{}' + bytes([10]));"
            " sys.stdout.flush(); time.sleep(30)")
    peer = _peer_running(code, timeout_s=5, max_line_bytes=1024)
    try:
        with pytest.raises(LineTooLongError):
            peer.read_line()
        assert peer.read_line() == b"{}"
    finally:
        peer.close()


def test_peer_caps_captured_stderr() -> None:
    code = (
        "import sys; sys.stderr.buffer.write(b'e' * (1 << 20)); sys.stderr.flush();"
        " sys.stdout.buffer.write(b'{}' + bytes([10])); sys.stdout.flush()"
    )
    peer = _peer_running(code, timeout_s=10)
    try:
        assert peer.read_line() == b"{}"
        peer.close()
        assert len(peer.stderr_text()) <= wire.STDERR_CAPTURE_BYTES + 64
    finally:
        peer.close()
