from __future__ import annotations

import io

from spellbench import wire
from spellbench.agent_server import serve
from spellbench.models import (
    ChooseRequest,
    GameOverRequest,
    GameStartRequest,
    HelloRequest,
    TerminalResult,
)

from conftest import TEST_ENGINE, make_decision

TERMINAL = TerminalResult(
    outcome="p0_win",
    classification="natural",
    winner="p0",
    reason="p1_life_zero",
    step_count=1,
    decision_count=1,
)

def game_start(request_id: str = "h-2", game_id: str = "g-0001") -> bytes:
    from spellbench.models import Deck

    return wire.canonical_json_line(
        GameStartRequest(
            request_id=request_id,
            game_id=game_id,
            seat="p0",
            format="pauper-bo1",
            decks=(Deck(catalog_id="Burn"), Deck(catalog_id="Burn")),
            engine=TEST_ENGINE,
        ).to_json()
    )


def choose(request_id: str = "h-3", game_id: str = "g-0001") -> bytes:
    return wire.canonical_json_line(
        ChooseRequest(request_id=request_id, game_id=game_id, decision=make_decision("h-9", step=0)).to_json()
    )


def game_over(request_id: str = "h-4", game_id: str = "g-0001") -> bytes:
    return wire.canonical_json_line(
        GameOverRequest(request_id=request_id, game_id=game_id, terminal=TERMINAL).to_json()
    )


def hello(request_id: str = "h-1") -> bytes:
    return wire.canonical_json_line(HelloRequest(request_id=request_id).to_json())


def run_server(lines: list[bytes], **kwargs) -> tuple[list[dict], bytes]:
    stdin = io.BytesIO(b"".join(lines))
    stdout = io.BytesIO()
    defaults = dict(bot_name="uniform", bot_version="1.0.0")
    if "handler" not in kwargs and "choose" not in kwargs:
        defaults["choose"] = lambda decision: 0
    defaults.update(kwargs)
    code = serve(stdin=stdin, stdout=stdout, **defaults)
    assert code == 0
    raw = stdout.getvalue()
    responses = [wire.strict_json_loads(line) for line in raw.splitlines()]
    return responses, raw


def response_types(responses: list[dict]) -> list[str]:
    return [r["response_type"] for r in responses]


def codes(responses: list[dict]) -> list[str]:
    return [r["error"]["code"] for r in responses if r["response_type"] == "error"]


def test_happy_path() -> None:
    seen = {}

    class Handler:
        def on_game_start(self, request):
            seen["game_id"] = request.game_id

        def choose(self, decision):
            seen["decision"] = decision
            return 0

        def on_game_over(self, request):
            seen["over"] = request.terminal.outcome

    responses, _ = run_server([hello(), game_start(), choose(), game_over()], handler=Handler())
    assert response_types(responses) == ["hello_ok", "ack", "choice", "ack"]
    assert responses[0]["bot"] == {"name": "uniform", "version": "1.0.0"}
    assert responses[2]["selection"] == {"candidate_id": 0, "semantic_echo": {"kind": "pass"}}
    assert seen == {"game_id": "g-0001", "decision": make_decision("h-9", step=0), "over": "p0_win"}


def test_malformed_json() -> None:
    responses, _ = run_server([b'{"request_type":'])
    assert response_types(responses) == ["error"]
    assert codes(responses) == ["malformed_json"]
    assert responses[0]["request_id"] == ""


def test_protocol_mismatch() -> None:
    responses, _ = run_server([b'{"request_type":"hello","protocol":"spellbench/v2","request_id":"h-1"}\n'])
    assert codes(responses) == ["protocol_mismatch"]
    assert responses[0]["request_id"] == "h-1"


def test_missing_request_id_is_malformed() -> None:
    responses, _ = run_server([b'{"request_type":"hello","protocol":"spellbench/v1"}\n'])
    assert codes(responses) == ["malformed_request"]


def test_unknown_request_type() -> None:
    responses, _ = run_server([b'{"request_type":"reset","protocol":"spellbench/v1","request_id":"h-1"}\n'])
    assert codes(responses) == ["malformed_request"]


def test_hello_rejects_extra_fields() -> None:
    responses, _ = run_server([b'{"request_type":"hello","protocol":"spellbench/v1","request_id":"h-1","z":1}\n'])
    assert codes(responses) == ["malformed_request"]


def test_choose_before_game_start_is_unknown_game() -> None:
    responses, _ = run_server([hello(), choose()])
    assert codes(responses) == ["unknown_game"]


def test_choose_wrong_game_id_is_unknown_game() -> None:
    responses, _ = run_server([hello(), game_start(), choose(game_id="g-other")])
    assert codes(responses) == ["unknown_game"]


def test_double_game_start() -> None:
    responses, _ = run_server([hello(), game_start(), game_start(request_id="h-3")])
    assert codes(responses) == ["game_already_active"]


def test_new_game_allowed_after_game_over() -> None:
    responses, _ = run_server([hello(), game_start(), game_over(), game_start(request_id="h-5")])
    assert response_types(responses) == ["hello_ok", "ack", "ack", "ack"]


def test_idempotent_choose_retransmit() -> None:
    calls = []

    def pick(decision):
        calls.append(1)
        return 0

    responses, _ = run_server([hello(), game_start(), choose(), choose()], choose=pick)
    assert response_types(responses) == ["hello_ok", "ack", "choice", "choice"]
    assert len(calls) == 1  # cached response replayed without side effects
    assert responses[2] == responses[3]


def test_request_id_reuse_mismatch() -> None:
    responses, _ = run_server([hello(), game_start(request_id="h-1")])
    assert codes(responses) == ["request_id_reuse_mismatch"]


def test_decision_pending_blocks_other_requests() -> None:
    def boom(decision):
        raise RuntimeError("bot exploded")

    responses, _ = run_server(
        [hello(), game_start(), choose(), hello("h-9"), game_over(request_id="h-10")],
        choose=boom,
    )
    assert response_types(responses) == ["hello_ok", "ack", "error", "error", "error"]
    assert codes(responses) == ["internal_error", "decision_pending", "decision_pending"]


def test_handler_candidate_out_of_range_is_internal_error() -> None:
    responses, _ = run_server([hello(), game_start(), choose()], choose=lambda decision: 7)
    assert codes(responses) == ["internal_error"]


def test_handler_returning_non_int_is_internal_error() -> None:
    responses, _ = run_server([hello(), game_start(), choose()], choose=lambda decision: True)
    assert codes(responses) == ["internal_error"]


def test_choose_with_malformed_decision() -> None:
    line = choose()
    bad = wire.strict_json_loads(line)
    bad["decision"]["candidates"] = []
    responses, _ = run_server([hello(), game_start(), wire.canonical_json_line(bad)])
    assert codes(responses) == ["malformed_request"]


def test_game_over_wrong_game_id() -> None:
    responses, _ = run_server([hello(), game_start(), game_over(game_id="g-other")])
    assert codes(responses) == ["unknown_game"]


def test_error_responses_validate_against_model() -> None:
    from spellbench.errors import AGENT_ERROR_CODES
    from spellbench.models import ErrorResponse

    responses, _ = run_server([b"garbage\n", hello(), choose(), game_start(request_id="h-1")])
    for response in responses:
        if response["response_type"] == "error":
            ErrorResponse.from_json(response, codes=AGENT_ERROR_CODES)


def test_second_choose_while_pending_is_decision_pending() -> None:
    def boom(decision):
        raise RuntimeError("bot exploded")

    responses, _ = run_server(
        [hello(), game_start(), choose(), choose("h-9")],
        choose=boom,
    )
    assert response_types(responses) == ["hello_ok", "ack", "error", "error"]
    assert codes(responses) == ["internal_error", "decision_pending"]


def test_whitespace_skewed_retransmit_is_a_different_payload() -> None:
    line = choose()
    skewed = line.replace(b'"candidate_id":0', b'"candidate_id": 0')
    assert skewed != line
    responses, _ = run_server([hello(), game_start(), line, skewed])
    assert codes(responses) == ["request_id_reuse_mismatch"]
