"""The reference bot server: lenient reading, the minimal contract, the agent error codes."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys

import pytest

from spellbench import wire
from spellbench.bot import BotSession, Decision, serve

PASS = {"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None}
LAND = {"candidate_id": 1, "semantic": {"kind": "play_land", "face": 0, "source": {}}, "display_text": "Play Mountain"}


def _request(kind: str, request_id: str, **fields) -> bytes:
    return wire.canonical_json_dumps({"request_type": kind, "protocol": "spellbench/v2", "request_id": request_id, **fields})


def _answer(session: BotSession, line: bytes) -> dict:
    out = session.handle_line(line)
    assert out.endswith(b"\n")
    return json.loads(out)


def _session(choose=lambda decision: decision.candidates[-1].candidate_id) -> BotSession:
    return BotSession(choose=choose, name="t", version="1", requires_observation=("keywords",))


def _started(session: BotSession) -> None:
    assert _answer(session, _request("game_start", "r-1", game_id="g-1", seat="p0", agent_seed=7))["response_type"] == "ack"


def test_hello_declares_the_bot_and_its_requirements() -> None:
    answer = _answer(_session(), _request("hello", "r-0", protocol_minor=0, x_future=1))
    assert answer == {"response_type": "hello_ok", "protocol": "spellbench/v2", "request_id": "r-0",
                      "bot": {"name": "t", "version": "1"},
                      "requires": {"observation": ["keywords"], "extensions": []}, "extensions_accepted": []}


def test_choose_reads_leniently_and_answers_only_the_candidate_id() -> None:
    session = _session()
    _started(session)
    decision = {"acting_seat": "p0", "candidates": [PASS, LAND], "x_unknown": {"a": 1}}
    answer = _answer(session, _request("choose", "r-2", game_id="g-1", decision=decision, clock={}, extra=[1]))
    assert answer == {"response_type": "choice", "protocol": "spellbench/v2", "request_id": "r-2",
                      "selection": {"candidate_id": 1}}


@pytest.mark.parametrize(
    ("line", "code", "request_id"),
    [
        (b"{not json", "malformed_json", ""),
        (b'{"request_type":"hello","protocol":"spellbench/v2"}', "malformed_request", ""),
        (b'{"request_type":"hello","request_id":"r-0"}', "malformed_request", "r-0"),
        (b'{"request_type":"hello","protocol":"spellbench/v1","request_id":"r-0"}', "protocol_mismatch", "r-0"),
        (b'{"request_type":"dance","protocol":"spellbench/v2","request_id":"r-0"}', "malformed_request", "r-0"),
        # An unhashable request_type must not escape handle_line and end serve.
        (b'{"request_type":["hello"],"protocol":"spellbench/v2","request_id":"r-0"}', "malformed_request", "r-0"),
        (b'{"request_type":{"a":1},"protocol":"spellbench/v2","request_id":"r-0"}', "malformed_request", "r-0"),
        # The parser's message quotes the duplicate key; its lone surrogate must not break the answer.
        (b'{"\\ud800":1,"\\ud800":2}', "malformed_json", ""),
    ],
)
def test_envelope_errors(line: bytes, code: str, request_id: str) -> None:
    answer = _answer(_session(), line)
    assert (answer["response_type"], answer["error"]["code"], answer["request_id"]) == ("error", code, request_id)


def test_game_state_errors() -> None:
    session = _session()
    assert _answer(session, _request("choose", "r-1", game_id="g-1", decision={"candidates": [PASS]}))["error"]["code"] == "unknown_game"
    _started(session)
    assert _answer(session, _request("game_start", "r-2", game_id="g-2"))["error"]["code"] == "game_already_active"
    assert _answer(session, _request("choose", "r-3", game_id="g-9", decision={"candidates": [PASS]}))["error"]["code"] == "unknown_game"
    assert _answer(session, _request("choose", "r-4", game_id="g-1", decision={"candidates": []}))["error"]["code"] == "malformed_request"
    assert _answer(session, _request("game_over", "r-5", game_id="g-1", terminal={}))["response_type"] == "ack"
    assert _answer(session, _request("choose", "r-6", game_id="g-1", decision={"candidates": [PASS]}))["error"]["code"] == "unknown_game"


@pytest.mark.parametrize("choose", [lambda d: 5, lambda d: "0", lambda d: 1 / 0])
def test_a_bad_handler_answer_is_an_internal_error(choose) -> None:
    session = _session(choose)
    _started(session)
    answer = _answer(session, _request("choose", "r-2", game_id="g-1", decision={"candidates": [PASS]}))
    assert answer["error"]["code"] == "internal_error"


def test_serve_accepts_crlf_and_utf8_names() -> None:
    decision = {"candidates": [{"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": "Lim-D\u00fbl's Vault \u014d"}]}
    lines = [_request("hello", "r-0"), _request("game_start", "r-1", game_id="g-1"),
             _request("choose", "r-2", game_id="g-1", decision=decision), _request("game_over", "r-3", game_id="g-1", terminal={})]
    stdout = io.BytesIO()
    assert serve(choose=lambda d: 0, stdin=io.BytesIO(b"".join(line + b"\r\n" for line in lines)), stdout=stdout) == 0
    kinds = [json.loads(line)["response_type"] for line in stdout.getvalue().splitlines()]
    assert kinds == ["hello_ok", "ack", "choice", "ack"]


def test_serve_reads_the_real_stdin_as_bytes_under_a_legacy_code_page() -> None:
    # The default streams are the binary buffers: U+014D (c5 8d) would crash a cp1252 text reader.
    decision = {"candidates": [{"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": "Lim-D\u00fbl's Vault \u014d"}]}
    lines = [_request("hello", "r-0"), _request("game_start", "r-1", game_id="g-1"),
             _request("choose", "r-2", game_id="g-1", decision=decision), _request("game_over", "r-3", game_id="g-1", terminal={})]
    code = "import sys\nfrom spellbench.bot import serve\nsys.exit(serve(choose=lambda d: 0))\n"
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
    result = subprocess.run([sys.executable, "-c", code], input=b"".join(line + b"\r\n" for line in lines),
                            capture_output=True, env=env, timeout=30)
    assert result.returncode == 0, result.stderr
    assert b"\r" not in result.stdout  # canonical lines with "\n" terminators, even on Windows
    assert [json.loads(line)["response_type"] for line in result.stdout.splitlines()] == ["hello_ok", "ack", "choice", "ack"]


def test_the_decision_view_exposes_what_bots_read() -> None:
    view = Decision.from_request({"game_id": "g-1", "decision": {"seat_step": 3, "candidates": [PASS, LAND]}, "clock": {"remaining_ms": 5}})
    assert [c.candidate_id for c in view.candidates] == [0, 1] and view.seat_step == 3 and view.clock == {"remaining_ms": 5}


def test_a_request_without_a_string_game_id_lacks_what_the_agent_needs() -> None:
    # Spec 10.5: unknown_game is for a game the request names; naming none is malformed_request.
    session = _session()
    for kind in ("game_start", "choose", "game_over"):
        answer = _answer(session, _request(kind, "r-1", game_id=None, decision={"candidates": [PASS]}))
        assert answer["error"]["code"] == "malformed_request", kind


def test_a_failing_hook_is_an_internal_error_and_never_leaves_a_game_stuck() -> None:
    def fail(view) -> None:
        raise RuntimeError("hook failed")

    session = BotSession(choose=lambda d: 0, on_game_start=fail, name="t", version="1")
    assert _answer(session, _request("game_start", "r-1", game_id="g-1"))["error"]["code"] == "internal_error"
    assert _answer(session, _request("choose", "r-2", game_id="g-1", decision={"candidates": [PASS]}))["error"]["code"] == "unknown_game"
    session = BotSession(choose=lambda d: 0, on_game_over=fail, name="t", version="1")
    _started(session)
    assert _answer(session, _request("game_over", "r-2", game_id="g-1", terminal={}))["error"]["code"] == "internal_error"
    assert _answer(session, _request("choose", "r-3", game_id="g-1", decision={"candidates": [PASS]}))["error"]["code"] == "unknown_game"
    assert _answer(session, _request("game_start", "r-4", game_id="g-2"))["response_type"] == "ack"


def test_serve_hands_the_views_to_a_handler_object() -> None:
    seen: list = []

    class Bot:
        def on_game_start(self, game) -> None:
            seen.append((game.game_id, game.seat, game.agent_seed, game.rules, game.opponent_deck))

        def choose(self, decision) -> int:
            seen.append((decision.acting_seat, decision.seat_step, decision.candidates[1].display_text))
            return decision.candidates[1].candidate_id

        def on_game_over(self, game_over) -> None:
            seen.append(game_over.terminal)

    lines = [_request("hello", "r-0"), _request("game_start", "r-1", game_id="g-1", seat="p1", agent_seed=9, opponent_deck=None),
             _request("choose", "r-2", game_id="g-1", decision={"acting_seat": "p1", "seat_step": 0, "candidates": [PASS, LAND]}),
             _request("game_over", "r-3", game_id="g-1", terminal={"outcome": "draw"})]
    stdout = io.BytesIO()
    assert serve(Bot(), name="b", version="2", stdin=io.BytesIO(b"".join(line + b"\n" for line in lines)), stdout=stdout) == 0
    answers = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert answers[0]["bot"] == {"name": "b", "version": "2"} and answers[2]["selection"] == {"candidate_id": 1}
    assert seen == [("g-1", "p1", 9, {}, None), ("p1", 0, "Play Mountain"), {"outcome": "draw"}]


@pytest.mark.parametrize("fields", [{"name": ""}, {"version": 1}, {"requires_observation": "keywords"},
                                    {"extensions_accepted": ("x_a", 2)}])
def test_a_session_refuses_an_identity_hello_ok_could_not_carry(fields: dict) -> None:
    with pytest.raises(ValueError):
        BotSession(**{"choose": lambda d: 0, "name": "t", "version": "1", **fields})
