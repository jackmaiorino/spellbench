"""The advisor's planned line in a human session (``--planned-line``): what the hub and the client get of it.

The engine side (the line played on a clone of the game, where it stops, that it is blind to the opponent's hand) is
tested with the bridge in integrations/mtg_kernel/london_human/tests/test_planned_line_v1.py and in mtg-kernel.
"""

from __future__ import annotations

import json

import pytest

from spellbench.human import relay, session
from spellbench.human.server import LINE, LINE_SCHEMA, LINE_TITLE, UNTRAINED_READ, Hub, planned_line_view

from test_human_advisor import advised, advisor, ask, model_input  # noqa: F401 - the fixture
from test_human_full_priority import BASE
from test_human_stops import BOLT, LAND, ME, decision

PASS = {"kind": "pass"}
WINS = {"schema": LINE_SCHEMA, "steps": [LAND, BOLT, PASS], "stop": "game_end", "result": "win"}


def test_the_panel_gets_the_steps_in_the_clients_words_and_how_the_line_ends() -> None:
    assert planned_line_view(WINS, ME, frozenset()) == {
        "title": LINE_TITLE, "steps": ["Play Island", "Cast Lightning Bolt", "Pass"],
        "end": "wins this turn if the opponent does not respond", "win": True}
    stopped = planned_line_view({**WINS, "stop": "opponent_decision", "result": None}, ME, frozenset())
    assert stopped["end"] == "then the opponent has a choice to make" and "win" not in stopped
    assert planned_line_view({**WINS, "result": "loss"}, ME, frozenset())["win"] is False
    assert planned_line_view({**WINS, "stop": "bound", "result": None}, ME, frozenset())["end"] == "..."
    # Every line says it assumes no response, and it is never called a search or the best line.
    assert "if the opponent does not respond" in LINE_TITLE
    assert not {"search", "best"} & set(LINE_TITLE.lower().replace(",", " ").split())


@pytest.mark.parametrize("payload", [None, {}, {**WINS, "schema": "other/v1"}, {**WINS, "steps": []},
                                     {**WINS, "steps": ["Play Island"]}, [WINS]])
def test_a_payload_of_another_shape_is_not_shown(payload) -> None:
    assert planned_line_view(payload, ME, frozenset()) is None


def lined(candidates: list[dict], line: dict, *, phase: str = "precombat_main") -> dict:
    request = advised(decision(candidates, phase=phase), model_input(list(range(len(candidates)))))
    request["decision"]["extensions"][LINE] = line
    return request


def test_the_line_reaches_the_advice_and_nothing_else_the_person_sees(advisor, tmp_path) -> None:  # noqa: F811
    hub = Hub(log_dir=tmp_path, advisor=advisor("argmax"))
    hub.game_start({"game_id": "g-1", "seat": ME, "own_deck": {"name": "Faeries"}, "opponent_deck": {"name": "Burn"}})
    started = ask(hub, lined([PASS, LAND, BOLT], WINS))
    assert hub.advice["line"]["steps"] == ["Play Island", "Cast Lightning Bolt", "Pass"]
    assert hub.advice["line"]["win"] is True
    assert LINE not in json.dumps(hub.pending) and LINE_SCHEMA not in json.dumps(hub.state())
    hub.answer_with(hub.pending["seq"], 1)
    started["thread"].join(timeout=5)
    assert started["result"]["answer"] == 1


def test_no_line_is_shown_where_the_read_is_not() -> None:
    """A window the model never trained on (full priority's upkeep): no read, so no line either."""
    from test_human_flow import at
    from test_human_full_priority import Reader, full_hub
    from test_human_stops import OPP

    hub = full_hub(advisor=Reader())
    hub._queue_read = lambda *args, **kwargs: pytest.fail("a new window was sent to the advisor")
    request = at([PASS, BOLT], phase="upkeep", active=OPP, turn=4)
    with hub.cond:
        hub._begin(request, {}, line=WINS)
    assert hub.advice["unavailable"] == UNTRAINED_READ and "line" not in hub.advice


def test_a_session_without_an_advisor_never_forwards_the_line() -> None:
    assert LINE in relay.DROPPED_EXTENSIONS


def test_each_picked_game_gives_its_engine_the_persons_seat_and_the_scorer_and_enables_the_line(tmp_path) -> None:
    scorer = ["scorer.exe", "--config", "c.json"]
    doc = session.picked_game_config(BASE, human_deck="Spy", bot_deck="Spy", human_first=False, run_dir=tmp_path,
                                     opponent="bot", line_scorer=scorer)
    assert doc["engine"]["command"][-4:] == ["--line-seat", "p1", "--line-scorer", json.dumps(scorer)]
    assert LINE in doc["extensions"]
    plain = session.picked_game_config(BASE, human_deck="Spy", bot_deck="Spy", human_first=False, run_dir=tmp_path,
                                       opponent="bot")
    assert LINE not in plain.get("extensions", []) and "--line-seat" not in plain["engine"]["command"]


def test_the_planned_line_needs_the_advisor_and_the_manabrew_client(capsys) -> None:
    for argv in (["--local", "x", "--out", "y", "--planned-line"],
                 ["--local", "x", "--out", "y", "--planned-line", "--advisor", "bot"],
                 ["--local", "x", "--out", "y", "--planned-line", "--client", "manabrew"]):
        with pytest.raises(SystemExit):
            session.main(argv)
    assert "--planned-line" in capsys.readouterr().err
