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


def row_key(value):
    return digest(value)[:16]


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
            keys = [row_key(f"key-{row}") for row in ids]
        else:
            observation = json.loads(extensions["x_kernel_v5"]["observation_json"])
            stable = observation["own_hand"][0]["stable"]
            result["candidates"].append({"candidate_id": 1, "semantic": {"kind": "play_land",
                "source": {"object_id": legacy_id(stable), "card_name": "Island", "zone": "hand"}}})
            ids, keys = [1, 0], [row_key("land"), row_key("pass")]
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
    wanted_key = row_key("key-3")
    completion = next(row for row in table["completions"] if table["keys"][row["native"][0]] == wanted_key)
    pool = Pool([wanted_key, row_key("unused-key")])
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


@pytest.mark.parametrize("changed", ["preview_key", "live_key", "other_candidate", "observation"])
def test_buffered_commit_rejects_a_changed_key_or_point_before_native_step(changed):
    engine, peer, request = configured(group=True)
    first = reply(engine, request)
    table = first["seat_decision"]["extensions"][INFOSET]["composition"]
    selected = next(row for row in table["completions"]
                    if table["keys"][row["native"][0]] == row_key("key-3"))
    first_pick, last_pick = selected["wire"]
    second = reply(engine, step(first, first_pick))
    assert second["response_type"] == "decision"
    if changed == "preview_key":
        trajectory = engine.trajectory

        def altered(plan):
            return [(view, candidate, row_key("changed-key")) for view, candidate, _ in trajectory(plan)]

        engine.trajectory = altered
    elif changed == "live_key":
        row = engine.current["extensions"][FLAT]["row_candidate_ids"].index(3)
        engine.current["extensions"][INFOSET]["row_keys"][row] = row_key("changed-key")
    elif changed == "other_candidate":
        engine.current["candidates"][0]["semantic"]["order"] = [0, 1, 2]
    else:
        ext = engine.current["extensions"]["x_kernel_v5"]
        observation = json.loads(ext["observation_json"])
        observation["projection"]["life_totals"][0] = 19
        ext["observation_json"] = json.dumps(observation)

    assert engine.current["candidates"][3] == engine.root["candidates"][3]
    halted = reply(engine, step(second, last_pick))
    assert halted["response_type"] == "terminal" and halted["classification"] == "halted"
    assert not [call for call in peer.calls if call["request_type"] == "step"]


def test_later_live_rows_use_the_group_root_key_map():
    engine, _, request = configured(group=True)
    reply(engine, request)
    later = deepcopy(engine.root)
    later["step"] += 1
    row_keys = later["extensions"][INFOSET]["row_keys"]
    later["extensions"][INFOSET]["row_keys"] = [row_key("new-point-map")] * len(row_keys)
    proof = {"root_step": engine.root["step"], "row_keys": row_keys}
    later["extensions"]["x_kernel_v2_support"]["reveal_v4_group_rows"] = proof
    assert engine._live_key(later, 3) == row_key("key-3")
    proof["root_step"] += 1
    with pytest.raises(ProjectionError, match="published root"):
        engine._live_key(later, 3)


def test_successor_cannot_emit_closed_list_payloads_on_a_hidden_decklist_board():
    engine, peer, request = configured()
    request = deepcopy(request)
    request["rules"]["opponent_decklist"] = "hidden"
    assert reply(engine, request)["error"]["code"] == "unsupported_rule"
    assert not [call for call in peer.calls if call["request_type"] == "reset"]


@pytest.mark.parametrize("bad", ["a" * 15, "a" * 17, "a" * 64, "g" * 16, 7])
def test_native_row_keys_have_their_own_fixed_width_contract(bad):
    from kernel_engine_reveal_search_v4 import is_digest, is_row_key
    from kernel_search_reveal_v4 import group_completions

    assert is_row_key(row_key("native"))
    assert not is_digest(row_key("native"))
    assert is_digest(digest("payload"))
    assert not is_row_key(digest("payload"))
    view = {"extensions": {FLAT: {"row_candidate_ids": [0]}}}
    with pytest.raises(ProjectionError, match="row keys"):
        KernelRevealSearchEngineV4._checked_row_keys(view, [bad])
    with pytest.raises(ProjectionError, match="completion table"):
        group_completions({"keys": [bad], "completions": [{"wire": [0], "native": [0]}]}, {0})
