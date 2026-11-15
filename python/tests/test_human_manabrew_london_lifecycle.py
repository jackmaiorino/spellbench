"""The host's log delivery, typed errors and fatal path at the London pregame prompts (Keep or Mulligan, put back)."""

from __future__ import annotations

import threading

from spellbench.human.manabrew import view
from spellbench.human.server import PUT_BACK_NOTE, Hub

from test_human_manabrew import bridge_in_game
from test_human_manabrew_london import ME, bottom_decision, mulligan_decision, pending_of


def prompt_types(bridge) -> list[str]:
    return [m["state"]["prompt"]["input"]["type"] for m in bridge.host.sent
            if m.get("state", {}).get("kind") == "prompt"]


def log_lines(bridge) -> list[str]:
    return [m["state"]["entry"]["message"] for m in bridge.host.sent if m.get("state", {}).get("kind") == "log"]


def errors(bridge) -> list[dict]:
    return [m["state"]["error"] for m in bridge.host.sent if m.get("state", {}).get("kind") == "error"]


def pregame_bridge():
    hub = Hub(opponent="Basilisk 2", banner="TEST MODE: pregame banner")
    bridge = bridge_in_game(hub)
    bridge.seats = None  # the first view creates the seats and holds the log back
    bridge.dealt = {"human": "Wildfire", "bot": "Rally", "differs": False}
    return bridge


def test_the_pregame_prompts_reach_the_client_and_the_held_log_is_resent_after_the_first_answer() -> None:
    bridge = pregame_bridge()
    hub = bridge.hub
    started = pending_of(hub, mulligan_decision(7, 0))
    bridge._push(hub.state())
    assert prompt_types(bridge) == ["mulligan"]
    assert log_lines(bridge) == []  # the client's log panel is not up yet: the opening lines are held
    # a wrong answer is a typed error to the client, the prompt stays open
    bridge._on_response("human", {"kind": "response", "promptId": bridge.prompt["id"],
                                  "action": {"type": "mulligan", "output": {"type": "mulliganDecision"}}})
    assert errors(bridge)[-1]["code"] == "invalidShape" and hub.pending is not None
    bridge._on_response("human", {"kind": "response", "promptId": bridge.prompt["id"],
                                  "action": {"type": "mulligan", "output": {"type": "mulliganDecision", "keep": False}}})
    started["thread"].join(timeout=5)
    assert started["result"]["answer"] == 0  # the mulligan candidate
    bridge._push(hub.state())
    sent = log_lines(bridge)
    assert sent and sent[0].startswith("TEST MODE: pregame banner")  # every opening line, in order, once
    again = pending_of(hub, bottom_decision(0, 1, hand=list(range(7)), group_id=1))
    bridge._push(hub.state())
    assert prompt_types(bridge)[-1] == "mulliganPutBack"
    assert PUT_BACK_NOTE in log_lines(bridge)
    # a card that is not in the hand and a wrong count: typed codes, no change to the engine's decision
    bridge._on_response("human", {"kind": "response", "promptId": bridge.prompt["id"],
                                  "action": {"type": "mulliganPutBack",
                                             "output": {"type": "mulliganPutBackDecision", "cardIds": ["zzz"]}}})
    bridge._on_response("human", {"kind": "response", "promptId": bridge.prompt["id"],
                                  "action": {"type": "mulliganPutBack",
                                             "output": {"type": "mulliganPutBackDecision", "cardIds": ["c1", "c2"]}}})
    assert [e["code"] for e in errors(bridge)[-2:]] == ["unknownActionId", "invalidShape"]
    hub.answer_with(again["pending"]["seq"], 0)
    again["thread"].join(timeout=5)


def test_a_failure_while_the_keep_or_mulligan_prompt_is_open_is_a_fatal_envelope_and_a_recorded_loss(monkeypatch, capsys) -> None:
    bridge = pregame_bridge()
    hub = bridge.hub
    seen: list[BaseException] = []

    def ask() -> None:
        try:
            hub.choose({"decision": mulligan_decision(7, 0)})
        except BaseException as exc:  # noqa: BLE001 - what the engine side would see
            seen.append(exc)

    thread = threading.Thread(target=ask, daemon=True)
    thread.start()
    with hub.cond:
        while hub.pending is None:
            hub.cond.wait(0.05)

    def broken(*args, **kwargs):
        raise KeyError("zones")

    monkeypatch.setattr(view, "game_view", broken)
    assert bridge._pump_once(-1) >= 0
    fatal = [m["state"] for m in bridge.host.sent if m.get("state", {}).get("kind") == "fatal"]
    assert len(fatal) == 1 and "KeyError" in fatal[0]["message"]
    assert hub.game_over["reason"] == "host_fault" and hub.results[-1]["result"] == "loss"
    thread.join(timeout=5)  # the engine's open decision is refused (Conceded), not left hanging
    assert not thread.is_alive() and seen and type(seen[0]).__name__ == "Conceded"
    assert "internal error" in capsys.readouterr().out
