from __future__ import annotations

import hashlib
import io

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


@pytest.mark.parametrize("line", [b'{"a":9007199254740992}', b'{"a":-9007199254740992}', b'{"a":0}'])
def test_strict_loads_accepts_safe_int_bounds(line: bytes) -> None:
    assert "a" in wire.strict_json_loads(line)


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
