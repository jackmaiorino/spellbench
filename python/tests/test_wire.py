from __future__ import annotations

import hashlib
import io
import sys
from typing import Iterator

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
        b'{"a":9007199254740993}',  # 2^53 + 1
        b'{"a":-9007199254740993}',
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
        (b"9007199254740992", 1 << 53),
        (b"-9007199254740992", -(1 << 53)),
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
        {"a": 9007199254740993},
        {"a": [1, {"b": float("inf")}]},
        {1: "x"},
        {"a": object()},
    ],
)
def test_canonical_dumps_rejects_non_canonical_values(value: object) -> None:
    with pytest.raises(ValidationError):
        wire.canonical_json_dumps(value)


def test_candidates_sha256_matches_spec_reduction() -> None:
    candidates = [
        {"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": "Pass priority"},
        {
            "candidate_id": 1,
            "semantic": {"kind": "choose_boolean", "source": None, "value": True},
            "display_text": "Yes",
        },
    ]
    reduced = b'[{"candidate_id":0,"semantic":{"kind":"pass"}},' b'{"candidate_id":1,"semantic":{"kind":"choose_boolean","source":null,"value":true}}]'
    assert wire.candidates_sha256(candidates) == hashlib.sha256(reduced).hexdigest()


def test_candidates_sha256_ignores_display_text() -> None:
    base = [{"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": "Pass"}]
    other = [{"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": "different text"}]
    assert wire.candidates_sha256(base) == wire.candidates_sha256(other)


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
def test_strict_loads_rejects_a_lone_surrogate_nested_past_the_recursion_limit(
    opening: bytes, innermost: bytes, closing: bytes
) -> None:
    # 1500 levels exceed Python's recursion limit (1000) but stay within
    # json's own nesting limit, so the surrogate check must not recurse.
    depth = 1500
    with pytest.raises(MalformedJsonError):
        wire.strict_json_loads(b'{"a":' + opening * depth + innermost + closing * depth + b"}")


def test_strict_loads_accepts_escaped_surrogate_pairs() -> None:
    assert wire.strict_json_loads(rb'{"a":"\ud83d\ude00"}') == {"a": "\U0001F600"}


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
