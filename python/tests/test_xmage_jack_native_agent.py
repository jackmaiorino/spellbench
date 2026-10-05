"""Check the original lifecycle without launching XMage or loading weights."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_jack_native_agent as agent
from spellbench import wire
from spellbench.bot import GameStart
from xmage_jack_native_inference import PROFILES
from test_xmage_neural_agent import decision, game, view

CHECKPOINT = "jack-elves-pair"


class Session:
    def __init__(self, start, indices=(), pass_after=False):
        self.start = copy.deepcopy(start)
        self.checkpoint, self.profile, self.seed = CHECKPOINT, PROFILES[0], start["agent_seed"]
        self.indices, self.pass_after = iter(indices), pass_after
        self.requests, self.results, self.closed = [], [], False

    def choose(self, record, *, timeout_s):
        self.requests.append((copy.deepcopy(record), timeout_s))
        candidate = record["decision"]["candidates"][next(self.indices)]
        result = {"decision_sha256": agent.digest(record["decision"]),
                  "game_start_sha256": agent.digest(self.start), "profile": self.profile, "seed": self.seed,
                  "full_original_player_qualified": False, "inference_requests": 1, "world_flags": [],
                  "selection": {"candidate_id": candidate["candidate_id"], "semantic_echo": candidate["semantic"]},
                  "priority_pass_after_activation": self.pass_after,
                  "original_priority_state": {"alternatives": [{"source": {
                      "object_id": "spell", "card_name": "Test spell", "zone": "hand"},
                      "choices": ["alternate"]}], "targets": []}}
        if "anchor" in record and record["decision"].get("context", {}).get("kind") == "priority":
            result.update(original_activation_path=True, original_priority_continuation=True,
                          original_activation_pass_deferred=False,
                          original_dialog_prefix_replayed=len(record["replay"]["earlier"]))
            if record["anchor"]["priority_pass_after_activation"]:
                result["inference_requests"] = 0
            if candidate["semantic"].get("kind") == "pass":
                result["priority_pass_after_activation"] = False
        if "anchor" in record and record["anchor"]["selection"]["semantic_echo"].get("kind") == "pass":
            result.update(original_resolution_path=True, original_activation_path=False,
                          original_priority_passes_replayed=len(record["replay"]["priority_passes"]),
                          original_dialog_prefix_replayed=len(record["replay"]["earlier"]))
            result["original_cleanup_path"] = agent.cleanup_discard(record["anchor"]["decision"], record["decision"], "p0")
            result["original_phase_advance_path"] = agent.phase_advance(record["anchor"]["decision"], record["decision"], "p0")
        self.results.append(result)
        return result

    def close(self):
        self.closed = True


def ready(indices=(0,), **options):
    sessions = []
    def factory(start):
        session = Session(start, indices, **options)
        sessions.append(session)
        return session
    bot = agent.JackNativeAgent(factory, checkpoint=CHECKPOINT, profile=PROFILES[0])
    bot.on_game_start(GameStart.from_request(game()))
    return bot, sessions[0]


def priority(step=0):
    return decision({"kind": "pass"}, {"kind": "cast_spell", "source": {"object_id": "spell"}}, step=step)


@pytest.mark.parametrize("before,after", [("upkeep", "draw"), ("precombat_main", "beginning_of_combat"),
                                       ("end_of_combat", "postcombat_main"), ("postcombat_main", "end_step")])
@pytest.mark.parametrize("already", [False, True])
def test_empty_stack_phase_resume_preserves_original_anchor_state_and_seeds(before, after, already):
    bot, session = ready([0, 1]); root, current = priority(), priority(1)
    for value, phase in ((root, before), (current, after)):
        value["observation"].update(phase_step=phase, priority_seat="p0", active_seat="p0")
    root["observation"]["passed_seats"] = ["p1"] if already else []
    bot.choose(view(root)); bot.choose(view(current))
    first, last = [r for r, _ in session.requests]
    assert last["anchor"]["decision"] == first["decision"]
    assert last["anchor"]["original_priority_state"] == session.results[0]["original_priority_state"]
    assert last["replay"] == {"priority_passes": [] if already else ["p1"], "earlier": []}
    assert (first["world_seed"], first["id_seed"]) == (last["world_seed"], last["id_seed"])
    assert session.results[-1]["original_phase_advance_path"] and not session.closed
    bot.close()


@pytest.mark.parametrize("value", [False, 1, None])
def test_phase_resume_requires_original_engine_path_receipt(value):
    bot, session = ready([0, 0]); root, current = priority(), priority(1)
    for d, phase in ((root, "precombat_main"), (current, "beginning_of_combat")):
        d["observation"].update(phase_step=phase, priority_seat="p0", active_seat="p0")
    bot.choose(view(root)); choose = session.choose
    def corrupted(record, **options):
        result = choose(record, **options); result["original_phase_advance_path"] = value; return result
    session.choose = corrupted
    with pytest.raises(ValueError, match="phase advance"): bot.choose(view(current))
    assert session.closed and bot.failed


def binary(step=1):
    return decision({"kind": "choose_boolean", "value": False},
                    {"kind": "choose_boolean", "value": True}, step=step)


@pytest.mark.parametrize("prefix", [0, 1, 2])
@pytest.mark.parametrize("priority_end", [False, True])
@pytest.mark.parametrize("already", [False, True])
def test_forward_phase_callbacks_keep_saved_root_prefix_and_seeds(prefix, priority_end, already):
    bot, session = ready([0] * (prefix + 2)); root = priority()
    root["observation"].update(phase_step="upkeep", priority_seat="p0", active_seat="p0",
                               passed_seats=["p1"] if already else [])
    bot.choose(view(root))
    for index in range(prefix + 1):
        current = priority(index + 1) if priority_end and index == prefix else binary(index + 1)
        current["observation"].update(phase_step="draw" if index < prefix else "precombat_main",
                                       priority_seat="p0" if current["context"]["kind"] == "priority" else None, active_seat="p0")
        bot.choose(view(current))
    first, last = session.requests[0][0], session.requests[-1][0]
    assert last["anchor"]["decision"] == first["decision"] and len(last["replay"]["earlier"]) == prefix
    assert last["replay"]["priority_passes"] == ([] if already else ["p1"])
    assert all((r["world_seed"], r["id_seed"]) == (first["world_seed"], first["id_seed"]) for r, _ in session.requests)
    assert session.results[-1]["original_phase_advance_path"] and not session.closed
    bot.close()


def amount(step=2):
    return decision({"kind": "choose_number", "purpose": "x_value", "value": 0},
                    {"kind": "choose_number", "purpose": "x_value", "value": 1}, step=step)


@pytest.mark.parametrize("prefix", [False, True])
def test_inherited_amount_callback_retains_original_anchor_and_seeds(prefix):
    bot, session = ready([1, 0, 0] if prefix else [1, 0]); bot.choose(view(priority()))
    values = [binary()] if prefix else []
    current=decision(*[{"kind":"choose_number","purpose":"amount","source":None,
        "minimum":0,"maximum":3,"value":i} for i in range(4)],step=2 if prefix else 1)
    for received in [*values,current]:bot.choose(view(received))
    root,last=session.requests[0][0],session.requests[-1][0]
    assert agent.family(last["decision"]) == "amount" and len(last["replay"]["earlier"]) == int(prefix)
    assert last["anchor"]["decision"] == root["decision"]
    assert (root["world_seed"],root["id_seed"]) == (last["world_seed"],last["id_seed"])
    bot.close()


def test_mixed_x_and_amount_menu_refuses_before_original_session():
    bot,session=ready([1]);bot.choose(view(priority()))
    current=decision({"kind":"choose_number","purpose":"amount","value":0},
                     {"kind":"choose_number","purpose":"x_value","value":1},step=1)
    with pytest.raises(ValueError,match="family is not connected"):bot.choose(view(current))
    assert len(session.requests)==1 and session.closed


@pytest.mark.parametrize("kind", ["choose_pile", "choose_replacement"])
@pytest.mark.parametrize("prefix", [False, True])
def test_inherited_menu_retains_original_anchor_prefix_and_seeds(kind, prefix):
    bot, session = ready([1, 0, 0] if prefix else [1, 0]); bot.choose(view(priority()))
    if prefix: bot.choose(view(binary()))
    semantics = ([{"kind": kind, "source": None, "purpose": "effect", "pile_index": i, "piles": [[], []]}
                  for i in range(2)] if kind == "choose_pile" else
                 [{"kind": kind, "affected": {"player": "p0"}, "event": "other", "replacement_source": None,
                   "replacement_index": i, "replacement_count": 2} for i in range(2)])
    bot.choose(view(decision(*semantics, step=2 if prefix else 1)))
    root, last = session.requests[0][0], session.requests[-1][0]
    assert agent.family(last["decision"]) == "inherited" and len(last["replay"]["earlier"]) == int(prefix)
    assert last["anchor"]["decision"] == root["decision"]
    assert (root["world_seed"], root["id_seed"]) == (last["world_seed"], last["id_seed"])
    bot.close()


def test_mixed_inherited_menu_refuses_before_original_session():
    bot, session = ready([1]); bot.choose(view(priority()))
    current = decision({"kind": "choose_pile", "source": None, "purpose": "effect", "pile_index": 0, "piles": [[], []]},
                       {"kind": "choose_replacement", "affected": {"player": "p0"}, "event": "other",
                        "replacement_source": None, "replacement_index": 0, "replacement_count": 2}, step=1)
    with pytest.raises(ValueError, match="family is not connected"): bot.choose(view(current))
    assert len(session.requests) == 1 and session.closed


@pytest.mark.parametrize("count", [2, 3, 4, 6])
def test_trigger_group_retains_one_anchor_and_all_earlier_ordering_picks(count):
    bot, session = ready([1] + [0] * count); bot.choose(view(priority()))
    for position in range(count - 1):
        current = decision(*[{"kind": "order_pick", "source": None, "purpose": "triggers",
            "position": position, "count": count, "item": {"trigger": {
                "source": None, "source_name": None, "ability_index": None, "event_objects": [],
                "instance": i, "label": None}}} for i in range(count - position)], step=position + 1)
        current["group"] = {"group_id": 700, "substep_index": position, "substep_count": count - 1}
        bot.choose(view(current))
    bot.choose(view(binary(count)))
    records = [r for r, _ in session.requests]; root = records[0]
    assert all(agent.family(r["decision"]) == "trigger" for r in records[1:-1])
    assert [len(r["replay"]["earlier"]) for r in records[1:]] == list(range(count))
    assert all(r["anchor"]["decision"] == root["decision"] for r in records[1:])
    assert all((r["world_seed"], r["id_seed"]) == (root["world_seed"], root["id_seed"]) for r in records)
    bot.close()


def test_mixed_trigger_purposes_refuse_before_original_session():
    bot, session = ready([1]); bot.choose(view(priority()))
    current = decision({"kind": "order_pick", "purpose": "triggers"},
                       {"kind": "order_pick", "purpose": "mulligan_bottom"}, step=1)
    with pytest.raises(ValueError, match="family is not connected"): bot.choose(view(current))
    assert len(session.requests) == 1 and session.closed


@pytest.mark.parametrize("count", [2, 3, 4, 6])
@pytest.mark.parametrize("purpose", ["library_top", "library_bottom"])
def test_library_order_group_keeps_original_root_and_all_picks(count,purpose):
    bot,session=ready([1]+[0]*count);bot.choose(view(priority()))
    for position in range(count-1):
        current=decision(*[{"kind":"order_pick","source":None,"purpose":purpose,"position":position,"count":count,
                           "item":{"object":{"object_id":"card"+str(i),"card_name":"Forest","zone":"hand"}}}
                          for i in range(position,count)],step=position+1)
        current["group"]={"group_id":700,"substep_index":position,"substep_count":count-1};bot.choose(view(current))
    bot.choose(view(binary(count)));records=[r for r,_ in session.requests]
    assert all(agent.family(r["decision"])=="library-order" for r in records[1:-1])
    assert [len(r["replay"]["earlier"]) for r in records[1:]]==list(range(count))
    assert all(r["anchor"]["decision"]==records[0]["decision"] for r in records[1:])
    assert all((r["world_seed"],r["id_seed"])==(records[0]["world_seed"],records[0]["id_seed"]) for r in records)
    bot.close()


def test_mixed_library_order_destinations_refuse_before_original_session():
    bot,session=ready([1]);bot.choose(view(priority()))
    current=decision({"kind":"order_pick","purpose":"library_top"},{"kind":"order_pick","purpose":"library_bottom"},step=1)
    with pytest.raises(ValueError,match="family is not connected"):bot.choose(view(current))
    assert len(session.requests)==1 and session.closed


def cleanup_menu(count, selected=0):
    refs = [{"object_id": "hand" + str(i), "card_name": "Forest" if i % 2 else "Island",
             "owner_seat": "p0", "controller_seat": "p0", "zone": "hand"} for i in range(7 + count)]
    current = decision(*[{"kind": "select_object", "source": None, "purpose": "discard",
        "choice": {"object": copy.deepcopy(ref)}, "selected_count": selected, "minimum": count, "maximum": count}
        for ref in refs[selected:]], step=selected + 1, phase="cleanup")
    current["context"].update(source=None, purpose="discard")
    current["observation"].update(active_seat="p0", priority_seat=None, passed_seats=["p0", "p1"],
                                  players=[{"seat": "p0", "hand": refs}])
    if count > 1: current["group"] = {"group_id": 41, "substep_index": selected, "substep_count": count}
    return current


@pytest.mark.parametrize("count", [1, 2, 3])
@pytest.mark.parametrize("already", [False, True])
def test_cleanup_replays_one_original_group_from_end_step_pass(count, already):
    bot, session = ready([0] * (count + 1)); root = priority()
    root["observation"].update(active_seat="p0", phase_step="end_step", passed_seats=["p1"] if already else [])
    bot.choose(view(root))
    for selected in range(count): bot.choose(view(cleanup_menu(count, selected)))
    records = [r for r, _ in session.requests]
    assert all(r["anchor"]["decision"] == records[0]["decision"] for r in records[1:])
    assert [len(r["replay"]["earlier"]) for r in records[1:]] == list(range(count))
    assert all(r["replay"]["priority_passes"] == ([] if already else ["p1"]) for r in records[1:])
    assert all((r["world_seed"], r["id_seed"]) == (records[0]["world_seed"], records[0]["id_seed"]) for r in records)
    assert session.results[-1]["original_cleanup_path"] and not session.closed
    bot.close()


@pytest.mark.parametrize("fault", ["root-phase", "active", "passed", "stack", "source", "owner", "group", "turn-type", "range-type"])
def test_invalid_cleanup_refuses_before_request(fault):
    bot, session = ready([0]); root = priority(); root["observation"].update(active_seat="p0", phase_step="end_step")
    if fault == "root-phase": root["observation"]["phase_step"] = "postcombat_main"
    bot.choose(view(root)); current = cleanup_menu(2)
    if fault == "active": current["observation"]["active_seat"] = "p1"
    if fault == "passed": current["observation"]["passed_seats"] = ["p0"]
    if fault == "stack": current["observation"]["stack"] = [{"card_name": "Visible spell"}]
    if fault == "source": current["context"]["source"] = {"object_id": "foreign"}
    if fault == "owner": current["candidates"][0]["semantic"]["choice"]["object"]["owner_seat"] = "p1"
    if fault == "group": current["group"]["substep_index"] = 1
    if fault == "turn-type": current["observation"]["turn"] = True
    if fault == "range-type": current["candidates"][0]["semantic"]["maximum"] = True
    with pytest.raises((ValueError, TypeError)): bot.choose(view(current))
    assert session.closed and len(session.requests) == 1


def test_cleanup_requires_original_cleanup_receipt():
    bot, session = ready([0, 0]); root = priority(); root["observation"].update(active_seat="p0", phase_step="end_step")
    bot.choose(view(root)); choose = session.choose
    def corrupted(record, **options):
        result = choose(record, **options); result.pop("original_cleanup_path"); return result
    session.choose = corrupted
    with pytest.raises(ValueError): bot.choose(view(cleanup_menu(1)))
    assert session.closed


@pytest.mark.parametrize("already", [False, True])
@pytest.mark.parametrize("next_priority", [False, True])
def test_pass_anchor_reaches_resolution_or_priority_with_public_pass_order(already, next_priority):
    bot, session = ready([0, 1, 0])
    root = priority(); root["observation"].update(stack=[{"card_name": "Visible spell"}], passed_seats=["p1"] if already else [])
    assert bot.choose(view(root)) == 10
    assert bot.choose(view(binary())) == 11
    current = priority(2) if next_priority else amount()
    bot.choose(view(current))
    first, last = session.requests[0][0], session.requests[-1][0]
    assert last["anchor"]["selection"]["semantic_echo"] == {"kind": "pass"}
    assert last["replay"]["priority_passes"] == ([] if already else ["p1"])
    assert len(last["replay"]["earlier"]) == 1
    assert (first["world_seed"], first["id_seed"]) == (last["world_seed"], last["id_seed"])
    assert session.results[-1]["original_resolution_path"] and not session.closed
    bot.close()


@pytest.mark.parametrize("field,value", [("original_resolution_path", False), ("original_activation_path", True),
                                        ("original_priority_passes_replayed", 0), ("original_priority_passes_replayed", True)])
def test_resolution_receipt_must_preserve_actual_path_and_pass_order(field, value):
    bot, session = ready([0, 0]); root = priority();root["observation"]["stack"] = [{"card_name": "Visible spell"}]
    bot.choose(view(root)); choose = session.choose
    def corrupted(record, *, timeout_s):
        result = choose(record, timeout_s=timeout_s); result[field] = value; return result
    session.choose = corrupted
    with pytest.raises(ValueError): bot.choose(view(binary()))
    assert session.closed and len(session.requests) == 2


@pytest.mark.parametrize("passed", [["p0"], ["p1", "p1"], ["foreign"], None])
def test_invalid_public_pass_facts_refuse_before_resolution_request(passed):
    bot, session = ready([0]); root = priority();root["observation"].update(stack=[{"card_name": "Visible spell"}], passed_seats=passed)
    bot.choose(view(root))
    with pytest.raises(ValueError): bot.choose(view(binary()))
    assert session.closed and len(session.requests) == 1


def test_public_protocol_always_enters_original_mulligan_and_forced_callback_then_closes():
    sessions = []
    def factory(start):
        sessions.append(Session(start, [0, 1, 0]))
        return sessions[-1]
    bot = agent.JackNativeAgent(factory, checkpoint=CHECKPOINT, profile=PROFILES[0])
    public = bot.public_session(name="original-player", version="pinned")
    def exchange(value):
        return json.loads(public.handle_line(wire.canonical_json_dumps(value)))
    hello = exchange({"protocol": "spellbench/v2", "request_id": "hello", "request_type": "hello"})
    assert hello["requires"]["observation"] == ["passed_seats", "keywords"]
    assert exchange(game())["response_type"] == "ack"
    mulligan = decision({"kind": "mulligan", "keep": False}, {"kind": "mulligan", "keep": True}, phase="pregame")
    assert exchange(view(mulligan).raw)["selection"]["candidate_id"] == 10
    assert exchange(view(priority(1)).raw)["selection"]["candidate_id"] == 11
    forced = binary(2); forced["candidates"] = forced["candidates"][:1]
    assert exchange(view(forced).raw)["selection"]["candidate_id"] == 10
    assert len(sessions[0].requests) == 3
    assert exchange({"protocol": "spellbench/v2", "request_id": "end", "request_type": "game_over",
                     "game_id": "opaque", "terminal": {}})["response_type"] == "ack"
    assert sessions[0].closed and bot.game is None
    assert exchange(game())["response_type"] == "ack" and len(sessions) == 2
    bot.close()


def test_callback_chain_retains_actual_priority_state_seeds_and_exact_prefix():
    bot, session = ready([1, 1, 0, 0])
    bot.choose(view(priority()))
    bot.choose(view(binary()))
    bot.choose(view(amount()))
    root, first, second = [entry[0] for entry in session.requests]
    assert first["anchor"]["original_priority_state"] == session.results[0]["original_priority_state"]
    assert first["anchor"]["priority_pass_after_activation"] is False
    assert first["replay"]["earlier"] == [] and first["replay"]["priority_passes"] == []
    assert second["replay"]["earlier"][0]["selection"]["semantic_echo"] == {"kind": "choose_boolean", "value": True}
    assert (root["world_seed"], root["id_seed"]) == (first["world_seed"], first["id_seed"]) == (
        second["world_seed"], second["id_seed"])
    assert root["decision"]["seat_step"] == 0 and second["decision"]["seat_step"] == 2
    bot.choose(view(priority(3)))
    fresh = session.requests[-1][0]
    assert fresh["anchor"]["decision"]["seat_step"] == 0 and len(fresh["replay"]["earlier"]) == 2
    assert (fresh["world_seed"], fresh["id_seed"]) == (root["world_seed"], root["id_seed"])
    assert bot.history.anchor["decision"]["seat_step"] == 3 and bot.history.earlier == []
    bot.close()


def test_frontend_freezes_complete_visible_target_queue_with_its_activation_anchor():
    bot, session = ready([1, 0])
    d = priority()
    ref = {"object_id": "queued", "card_name": "Forest", "owner_seat": "p0", "controller_seat": "p0", "zone": "hand"}
    d["observation"]["players"] = [{"seat": "p0", "hand": [copy.deepcopy(ref)]}]
    original = session.choose
    def choose(record, *, timeout_s):
        result = original(record, timeout_s=timeout_s)
        result["original_priority_state"]["targets"] = [copy.deepcopy(ref), copy.deepcopy(ref)]
        return result
    session.choose = choose
    bot.choose(view(d))
    session.results[0]["original_priority_state"]["targets"][0]["object_id"] = "mutated exported receipt"
    bot.choose(view(binary()))
    saved = session.requests[-1][0]["anchor"]["original_priority_state"]["targets"]
    assert saved == [ref, ref] and len(session.requests) == 2
    bot.close()


@pytest.mark.parametrize("shape", ["multiple", "singleton", "exhausted", "optional-finish"])
def test_modes_use_original_session_and_join_binary_x_replay_prefix(shape):
    bot, session = ready([1, 0, 1, 0])
    bot.choose(view(priority()))
    source = {"object_id": "spell"}
    option = {"kind": "choose_spell_mode", "source": source, "mode_index": 0,
              "mode_count": 2, "selected_count": 0, "minimum": 1, "maximum": 1}
    finish = {"kind": "finish_selection", "source": source, "purpose": "modes", "selected_count": 0}
    semantics = [option]
    if shape == "multiple": semantics.append({**option, "mode_index": 1})
    if shape == "exhausted": semantics = [finish]
    if shape == "optional-finish": semantics.append(finish)
    received = decision(*semantics, step=1)
    bot.choose(view(received))
    bot.choose(view(binary(2)))
    bot.choose(view(amount(3)))
    root, mode, binary_record, x = [row[0] for row in session.requests]
    assert agent.family(mode["decision"]) == "mode"
    assert mode["replay"]["earlier"] == []
    assert binary_record["replay"]["earlier"][0]["selection"]["semantic_echo"] == semantics[0]
    assert len(x["replay"]["earlier"]) == 2
    assert all((r["world_seed"], r["id_seed"]) == (root["world_seed"], root["id_seed"])
               for r in (mode, binary_record, x))
    bot.close()


@pytest.mark.parametrize("semantic", [{"kind": "finish_selection", "purpose": "cards"},
                                     {"kind": "choose_boolean", "value": True}])
def test_mixed_mode_families_refuse_before_original_session(semantic):
    bot, session = ready([1])
    bot.choose(view(priority()))
    received = decision({"kind": "choose_spell_mode", "mode_index": 0}, semantic, step=1)
    with pytest.raises(ValueError, match="family is not connected"):
        bot.choose(view(received))
    assert session.closed and len(session.requests) == 1


@pytest.mark.parametrize("kind", ["choose_option", "choose_color", "choose_name"])
@pytest.mark.parametrize("singleton", [False, True])
def test_named_callbacks_retain_activation_and_join_mode_binary_x_history(kind, singleton):
    bot, session = ready([1, 0, 1, 0])
    bot.choose(view(priority()))
    if kind == "choose_option":
        semantics = [{"kind": kind, "source": None, "purpose": "effect_option", "option_index": i,
                      "option_count": 1 if singleton else 2, "option_label": str(i)} for i in range(1 if singleton else 2)]
    elif kind == "choose_color":
        semantics = [{"kind": kind, "source": None, "purpose": "effect", "color": color}
                     for color in (["blue"] if singleton else ["blue", "green"])]
    else:
        semantics = [{"kind": kind, "source": None, "purpose": "creature_type", "value": value}
                     for value in (["elf"] if singleton else ["elf", "human"])]
    bot.choose(view(decision(*semantics, step=1)))
    bot.choose(view(binary(2)))
    bot.choose(view(amount(3)))
    root, named, binary_record, x = [entry[0] for entry in session.requests]
    assert agent.family(named["decision"]) == "named" and named["replay"]["earlier"] == []
    assert binary_record["replay"]["earlier"][0]["selection"]["semantic_echo"] == semantics[0]
    assert len(x["replay"]["earlier"]) == 2
    assert (named["world_seed"], named["id_seed"]) == (root["world_seed"], root["id_seed"])
    assert not session.closed
    bot.close()


def test_caller_result_and_audit_mutations_cannot_change_saved_priority_state():
    bot, session = ready([1, 0])
    bot.audit = lambda event: event.update(selection={"candidate_id": 999})
    received = priority()
    bot.choose(view(received))
    session.results[0]["original_priority_state"]["alternatives"].clear()
    session.results[0]["selection"]["semantic_echo"].clear()
    received["observation"]["phase_step"] = "postcombat_main"
    bot.choose(view(binary()))
    saved = session.requests[-1][0]["anchor"]
    assert saved["original_priority_state"]["alternatives"][0]["choices"] == ["alternate"]
    assert saved["selection"]["semantic_echo"]["kind"] == "cast_spell"
    bot.close()


def test_opaque_ids_clocks_and_injected_private_fields_do_not_change_original_record():
    records = []
    for opaque, milliseconds in (("one", 1500), ("two", 3000)):
        sessions = []
        def factory(start):
            sessions.append(Session(start, [0]))
            return sessions[-1]
        bot = agent.JackNativeAgent(factory, checkpoint=CHECKPOINT, profile=PROFILES[0])
        start = game(opaque); start["hidden_engine_state"] = {"library_order": "forbidden"}
        bot.on_game_start(GameStart.from_request(start))
        received = priority()
        received.update(hidden_engine_state="forbidden", x_history={"card_origins": "spoofed"},
                        x_observation_flags={"opponent_hand": True})
        bot.choose(view(received, game_id=opaque, clock={"remaining_ms": milliseconds,
                                                       "max_decision_ms": milliseconds}))
        records.append(sessions[0].requests[0][0]); bot.close()
    assert records[0] == records[1]
    assert records[0]["decision"]["x_history"] == {"loyalty_used": [], "card_origins": {}}
    assert "hidden_engine_state" not in records[0]["decision"] and "hidden_engine_state" not in records[0]["game_start"]


@pytest.mark.parametrize("change", ["rewind", "viewer", "game", "step", "clock", "unsupported", "no-anchor"])
def test_invalid_or_unconnected_choice_closes_without_entering_original_session(change):
    bot, session = ready()
    received, kwargs = priority(), {}
    if change == "rewind": received["context"]["rewind"] = True
    if change == "viewer": received["observation"]["viewer"] = "p1"
    if change == "game": kwargs["game_id"] = "foreign"
    if change == "step": received["seat_step"] = True
    if change == "clock": kwargs["clock"] = {"remaining_ms": 0, "max_decision_ms": 1000}
    if change == "unsupported": received = decision({"kind": "choose_key", "key": "a"})
    if change == "no-anchor": received = binary(0)
    with pytest.raises(ValueError): bot.choose(view(received, **kwargs))
    assert bot.failed and session.closed and not session.requests


@pytest.mark.parametrize("change", ["turn", "phase", "stale", "skipped"])
def test_changed_callback_cannot_replay_another_activation(change):
    bot, session = ready([1])
    bot.choose(view(priority()))
    received = binary()
    if change == "turn": received["observation"]["turn"] = 2
    if change == "phase": received["observation"]["phase_step"] = "combat"
    if change == "stale": received["seat_step"] = 0
    if change == "skipped": received["seat_step"] = 2
    with pytest.raises(ValueError): bot.choose(view(received))
    assert session.closed and len(session.requests) == 1


def test_pass_after_activation_is_replayed_to_the_exact_next_priority_boundary():
    bot, session = ready([1, 0, 0], pass_after=True)
    bot.choose(view(priority()))
    bot.choose(view(binary()))
    assert session.requests[-1][0]["anchor"]["priority_pass_after_activation"] is True
    assert bot.choose(view(priority(2))) == 10
    continuation = session.requests[-1][0]
    assert len(continuation["replay"]["earlier"]) == 1
    assert continuation["anchor"]["priority_pass_after_activation"] is True
    assert continuation["world_seed"] == session.requests[0][0]["world_seed"]
    assert len(session.requests) == 3 and not session.closed
    bot.close()


@pytest.mark.parametrize("kind", ["cast_spell", "activate_ability", "play_land", "activate_mana_ability"])
def test_every_original_activation_kind_reuses_its_saved_world_at_next_priority(kind):
    bot, session = ready([1, 0])
    d = priority();d["candidates"][1]["semantic"]["kind"] = kind
    bot.choose(view(d));bot.choose(view(priority(1)))
    root, following = [row[0] for row in session.requests]
    assert following["anchor"]["selection"]["semantic_echo"]["kind"] == kind
    assert following["world_seed"] == root["world_seed"] and following["replay"]["earlier"] == []
    bot.close()


@pytest.mark.parametrize("field", ["turn", "phase_step"])
def test_priority_continuation_refuses_an_unrecorded_transition_before_session_work(field):
    bot, session = ready([1]);bot.choose(view(priority()))
    later = priority(1);later["observation"][field] = 2 if field == "turn" else "postcombat_main"
    with pytest.raises(ValueError):bot.choose(view(later))
    assert session.closed and len(session.requests) == 1


@pytest.mark.parametrize("fault", ["continuation", "activation", "prefix", "deferred", "choice", "inference"])
def test_priority_continuation_requires_the_actual_completed_activation_and_zero_draw_pass(fault):
    bot, session = ready([1, 0], pass_after=True);bot.choose(view(priority()))
    original = session.choose
    def bad(record, *, timeout_s):
        result = original(record, timeout_s=timeout_s)
        if fault == "continuation": result["original_priority_continuation"] = False
        if fault == "activation": result["original_activation_path"] = False
        if fault == "prefix": result["original_dialog_prefix_replayed"] = 1
        if fault == "deferred": result["original_activation_pass_deferred"] = 1
        if fault == "choice":
            candidate = record["decision"]["candidates"][1]
            result["selection"] = {"candidate_id": candidate["candidate_id"], "semantic_echo": candidate["semantic"]}
        if fault == "inference": result["inference_requests"] = 1
        return result
    session.choose = bad
    with pytest.raises(ValueError):bot.choose(view(priority(1)))
    assert session.closed and len(session.requests) == 2


@pytest.mark.parametrize("field,value", [("checkpoint", "foreign"), ("profile", PROFILES[1]),
                                         ("seed", True), ("start", {"seat": "p1"})])
def test_factory_identity_failure_closes_the_created_session(field, value):
    sessions = []
    def factory(start):
        session = Session(start)
        setattr(session, field, value); sessions.append(session)
        return session
    bot = agent.JackNativeAgent(factory, checkpoint=CHECKPOINT, profile=PROFILES[0])
    with pytest.raises(ValueError, match="session differs"):
        bot.on_game_start(GameStart.from_request(game()))
    assert bot.failed and sessions[0].closed


def test_shared_frontend_clock_expires_before_history_can_accept_a_late_result(monkeypatch):
    bot, session = ready()
    clock = [0.0]; monkeypatch.setattr(agent.time, "monotonic", lambda: clock[0])
    choose = session.choose
    def delayed(record, **options):
        assert options["timeout_s"] == pytest.approx(1.9)
        result = choose(record, **options); clock[0] = 2.0
        return result
    session.choose = delayed
    with pytest.raises(TimeoutError): bot.choose(view(priority()))
    assert bot.failed and session.closed and bot.history.anchor is None and bot.step is None


@pytest.mark.parametrize("field,value", [("decision_sha256", "0" * 64), ("seed", True),
    ("priority_pass_after_activation", 1), ("original_priority_state", {"alternatives": "bad"}),
    ("selection", {"candidate_id": 999, "semantic_echo": {}})])
def test_invalid_original_receipt_cannot_be_saved(field, value):
    bot, session = ready()
    choose = session.choose
    def malformed(record, **options):
        result = choose(record, **options); result[field] = value
        return result
    session.choose = malformed
    with pytest.raises(ValueError): bot.choose(view(priority()))
    assert session.closed and bot.history.anchor is None


@pytest.mark.parametrize("kind", ["choose_target", "finish_target_selection", "choose_cost_target", "select_object", "finish_selection"])
def test_target_callbacks_retain_activation_seeds_and_join_exact_prefix(kind):
    bot, session = ready([1, 0, 0])
    bot.choose(view(priority()))
    semantic = {"kind": kind, "source": {"object_id": "spell"}, "selected_count": 0}
    if kind in ("select_object", "finish_selection"):
        semantic["purpose"] = "cards"
    received = decision(semantic, step=1)
    bot.choose(view(received))
    bot.choose(view(amount()))
    root, target, following = [record for record, _ in session.requests]
    assert agent.family(target["decision"]) == "target"
    assert target["anchor"]["original_priority_state"] == session.results[0]["original_priority_state"]
    assert (target["world_seed"], target["id_seed"]) == (root["world_seed"], root["id_seed"])
    assert following["replay"]["earlier"][0]["selection"]["semantic_echo"] == semantic
    assert not session.closed
    bot.close()


@pytest.mark.parametrize("semantic", [{"kind": "finish_selection", "purpose": "modes"}, {"kind": "choose_boolean", "value": True}])
def test_mixed_target_families_refuse_before_original_session(semantic):
    bot, session = ready([1])
    bot.choose(view(priority()))
    with pytest.raises(ValueError, match="family is not connected"):
        bot.choose(view(decision({"kind": "choose_target"}, semantic, step=1)))
    assert session.closed and len(session.requests) == 1


def test_original_error_survives_failed_cleanup():
    bot, session = ready()
    def cleanup(): raise RuntimeError("close failed")
    session.close = cleanup
    with pytest.raises(ValueError, match="rewound") as failure:
        received = priority(); received["context"]["rewind"] = True
        bot.choose(view(received))
    assert "cleanup also failed" in failure.value.__notes__[0]


def test_frontend_and_native_supervisor_share_one_actual_owner_through_callback_chain(tmp_path, monkeypatch):
    from test_xmage_jack_inference import fixture, Peer
    from test_xmage_jack_backend import IMAGE
    from test_xmage_jack_native_inference import packet
    from xmage_jack_native_inference import JackNativeInferenceOwner
    from xmage_jack_native_session import JackNativeSession, SCHEMA, CALLBACK_SHA256

    manifest, context, inference_ready, cleanup = fixture(tmp_path, monkeypatch)
    pair = Peer([inference_ready])
    owned = []
    class ServingPeer(Peer):
        def write_line(self, data):
            super().write_line(data)
            command = json.loads(data)
            if command.get("operation") != "decide":
                return
            record = command
            selection_index = 0 if "anchor" in record else 1
            candidate = record["decision"]["candidates"][selection_index]
            result = {"game_start_sha256": owner.start_sha256,
                      "decision_sha256": agent.digest(record["decision"]), "profile": owner.profile,
                      "seed": owner.seed, "inference_requests": 1, "full_original_player_qualified": False,
                      "world_flags": [], "selection": {"candidate_id": candidate["candidate_id"],
                                                         "semantic_echo": candidate["semantic"]},
                      "priority_pass_after_activation": False, "original_priority_state": {"alternatives": [], "targets": []}}
            if "anchor" in record:
                result.update(original_activation_path=True,
                              original_dialog_prefix_replayed=len(record["replay"]["earlier"]))
            self.rows.extend([json.dumps(packet(owner, "physical_copy", id=owner.sequence + 1, count=1)).encode(),
                json.dumps({"schema": SCHEMA, "id": command["id"], "operation": "decide",
                            "event": "result", "ok": True, "result": result}).encode()])

    def factory(start):
        nonlocal owner
        owner = JackNativeInferenceOwner(manifest, tmp_path, "policy", IMAGE, game_start=start,
            profile=PROFILES[0], seed=start["agent_seed"], peer_factory=lambda *a, **k: pair)
        peer = ServingPeer([{"schema": SCHEMA, "ready": True, "callback_sha256": CALLBACK_SHA256,
            "profile": owner.profile, "seed": owner.seed, "game_start_sha256": owner.start_sha256,
            "operations": ["decide"]}])
        owned.append((owner, peer))
        return JackNativeSession(peer, owner)

    owner = None
    bot = agent.JackNativeAgent(factory, checkpoint="policy", profile=PROFILES[0])
    start = game(); start["own_deck"] = context["own_deck"]
    bot.on_game_start(GameStart.from_request(start))
    assert [bot.choose(view(value)) for value in (priority(), binary(), amount())] == [11, 10, 10]
    assert len(owned) == 1 and owner.sequence == 3 and owner.copy_draws == 0
    commands = [c for c in owned[0][1].writes if c.get("operation") == "decide"]
    assert [c["id"] for c in commands] == ["1", "2", "3"]
    assert commands[-1]["replay"]["earlier"][0]["selection"]["semantic_echo"] == {
        "kind": "choose_boolean", "value": False}
    bot.close()
    assert owner.closed and owned[0][1].closed and pair.closed and len(cleanup) == 1
