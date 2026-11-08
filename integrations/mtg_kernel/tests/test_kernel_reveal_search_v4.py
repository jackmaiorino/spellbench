"""Exercise the successor adapter, neutral viewer and entrant together."""
from copy import deepcopy
import hashlib
import json

import pytest

from test_kernel_engine_reveal_v3 import setup
from test_kernel_engine_infoset_v2 import trigger_root
from kernel_engine_reveal_search_v4 import INFOSET, WIRE_SCHEMA, KernelRevealSearchEngineV4
from kernel_engine_v2 import FLAT
from kernel_observation_v2 import legacy_id, ProjectionError
from kernel_search_reveal_v4 import RevealSearchBotV4
from spellbench import wire
from spellbench.bot import Decision, GameStart
from spellbench.host.validator import LiveValidator
from spellbench.messages import Decision as EnvironmentDecision, EnvHelloOk, Rules
from spellbench.reveal_meaning_v3 import SCHEMA


def reply(engine, request):
    return wire.strict_json_loads(engine.handle(wire.canonical_json_dumps(request)))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def configured(first="p0", *, group=False, minimum=1, offset=0):
    previous, peer, request = setup(first, native_offset=offset)
    request["rules"]["extensions"] = [SCHEMA, INFOSET]
    native_request = peer.request

    def native(value):
        result = native_request(value)
        if value["request_type"] != "reset":
            return result
        extensions = result["extensions"]
        payload = {"schema": INFOSET, "sha256": digest("payload"),
                   "state_sha256": digest("state"), "viewer": 0,
                   "reveal_hand": [{"card_name": "Island", "minimum": minimum}]}
        if group:
            root = trigger_root()
            result["candidates"] = root["candidates"]
            for row in result["candidates"]:
                row["semantic"]["pending_sources"] = [{"object_id": f"native-{i}",
                    "zone": "battlefield", "card_name": "Island"} for i in range(3)]
            ids = root["extensions"][FLAT]["row_candidate_ids"]
            keys = [digest(f"key-{row}") for row in ids]
        else:
            observation = json.loads(extensions["x_kernel_v5"]["observation_json"])
            stable = observation["own_hand"][0]["stable"]
            result["candidates"].append({"candidate_id": 1, "semantic": {"kind": "play_land",
                "source": {"object_id": legacy_id(stable), "card_name": "Island", "zone": "hand"}}})
            ids, keys = [1, 0], [digest("land"), digest("pass")]
        extensions[FLAT]["row_candidate_ids"] = ids
        extensions[INFOSET] = {"schema": INFOSET, "payload_json": json.dumps(payload),
                              "live_rows": list(range(len(ids))), "row_keys": keys}
        return result

    peer.request = native
    return KernelRevealSearchEngineV4(peer, previous.catalog), peer, request


class Pool:
    def __init__(self, keys=()):
        self.keys = list(keys)
        self.requests = []

    def request_line(self, line):
        request = json.loads(line)
        self.requests.append(request)
        if request.get("op") == "point":
            return {"ok": True, "point": {"viewer_decision": True, "keys": self.keys, "eligible": True}}
        return {"ok": True, "search": {"root_id": request["root_id"], "units": 1,
            "charge": 1 + request["a_units"], "payload_sha256": request["payload"]["sha256"],
            "incomplete": False, "pick": 0}}


def entrant(pool, request, seat):
    bot = RevealSearchBotV4(pool, budget=4, allowance=20, a_units=1)
    bot.on_game_start(GameStart.from_request({"game_id": request["game_id"], "agent_seed": 6, "seat": seat}))
    return bot


def choose(bot, response):
    return bot.choose(Decision.from_request({"game_id": response["game_id"],
                                             "decision": response["seat_decision"]}))


def step(response, candidate):
    return {"protocol": "spellbench/v2", "request_type": "step", "request_id": f"step-{response['step']}",
            "game_id": response["game_id"], "expected_step": response["step"],
            "selection": {"candidate_id": candidate,
                          "semantic_echo": response["seat_decision"]["candidates"][candidate]["semantic"]}}


@pytest.mark.parametrize("first", ["p0", "p1"])
def test_successor_transports_public_constraints_and_searches_mapped_ordinary_rows(first):
    engine, _, request = configured(first)
    other, _, _ = configured(first, offset=10_000)
    result = reply(engine, request)
    assert result == reply(other, request)
    validator = LiveValidator(EnvHelloOk.from_json(engine.hello), Rules.from_json(request["rules"]),
                              max_steps=8, max_decisions=8)
    sd = validator.check(EnvironmentDecision.from_json(result))
    assert set(sd["extensions"]) == {SCHEMA, INFOSET}
    assert sd["extensions"][INFOSET]["live_candidate_ids"] == [1, 0]
    pool = Pool()
    bot = entrant(pool, request, first)
    assert choose(bot, result) == 1
    assert pool.requests[0]["payload"]["reveal_hand"] == [{"card_name": "Island", "minimum": 1}]
    assert bot.remaining == 18


def test_adapter_and_entrant_refuse_a_disagreement_with_the_public_stream():
    engine, _, request = configured(minimum=2)
    answer = reply(engine, request)
    assert answer["response_type"] == "terminal" and answer["classification"] == "halted"
    assert "extensions" not in answer

    engine, _, request = configured()
    answer = reply(engine, request)
    answer["seat_decision"]["extensions"][SCHEMA]["operations"] = []
    pool = Pool()
    with pytest.raises(ProjectionError, match="minima differ"):
        choose(entrant(pool, request, "p0"), answer)
    assert pool.requests == []


def test_buffered_trigger_search_commits_the_chosen_native_completion_once():
    engine, peer, request = configured(group=True)
    first = reply(engine, request)
    extension = first["seat_decision"]["extensions"][INFOSET]
    assert extension["schema"] == WIRE_SCHEMA
    table = extension["composition"]
    assert len(table["completions"]) == 6
    wanted_key = digest("key-3")
    completion = next(row for row in table["completions"] if table["keys"][row["native"][0]] == wanted_key)
    pool = Pool([wanted_key, digest("unused-key")])
    bot = entrant(pool, request, "p0")

    first_pick = choose(bot, first)
    assert first_pick == completion["wire"][0]
    assert not [call for call in peer.calls if call["request_type"] == "step"]
    second = reply(engine, step(first, first_pick))
    second_pick = choose(bot, second)
    assert second_pick == completion["wire"][1]
    assert INFOSET not in second["seat_decision"]["extensions"]
    next_response = reply(engine, step(second, second_pick))
    assert next_response["response_type"] == "decision"
    native = [call for call in peer.calls if call["request_type"] == "step"]
    assert [call["selection"]["candidate_id"] for call in native] == [3]
    assert len(pool.requests) == 2


def test_successor_cannot_emit_closed_list_payloads_on_a_hidden_decklist_board():
    engine, peer, request = configured()
    request = deepcopy(request)
    request["rules"]["opponent_decklist"] = "hidden"
    assert reply(engine, request)["error"]["code"] == "unsupported_rule"
    assert not [call for call in peer.calls if call["request_type"] == "reset"]
