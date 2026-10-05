"""Public lifecycle for the original Jack player and its game-owned stream.

The factory borrows a JVM from the guarded launcher. Complete games, further
callback families and pass-after-activation continuation remain unqualified.
"""
from __future__ import annotations

import copy
import hmac
import time

from spellbench import wire
from spellbench.bot import BotSession, Decision, GameOver, GameStart
from xmage_jack_native_inference import PROFILES
from xmage_jack_native_session import bound_decision, bound_replay, bound_selection, cleanup_discard, digest, phase_advance, priority_state, resolution_passes
from xmage_jack_london import bound_view as london_view
from xmage_neural_combat import CombatPlan, battlefield, combat_kind, select_candidate, target
from xmage_neural_agent import PublicHistory, _DECISION_FIELDS, _START_FIELDS, game_key

_ACTIVATIONS = {"cast_spell", "activate_ability", "play_land", "activate_mana_ability"}


def family(decision):
    kinds = {c["semantic"].get("kind") for c in decision["candidates"]}
    if decision["observation"].get("phase_step") == "pregame" and kinds == {"mulligan"}:
        return "mulligan"
    if (decision["observation"].get("phase_step") == "pregame" and kinds == {"order_pick"}
            and all(c["semantic"].get("purpose") == "mulligan_bottom" for c in decision["candidates"])):
        return "london"
    if kinds in ({"declare_attack"}, {"declare_block"}):
        return combat_kind(decision)
    if decision.get("context", {}).get("kind") == "priority":
        return "priority"
    if decision.get("context", {}).get("kind") == "choice" and len(kinds) == 1:
        kind = next(iter(kinds))
        if kind in ("choose_boolean", "optional_cost", "choose_cast_method"):
            return "binary"
        if kind == "choose_number" and all(c["semantic"].get("purpose") == "x_value"
                                            for c in decision["candidates"]):
            return "x"
        if kind == "choose_number" and all(c["semantic"].get("purpose") == "amount"
                                            for c in decision["candidates"]):
            return "amount"
        if kind in ("choose_option", "choose_color", "choose_name"):
            return "named"
        if kind in ("choose_pile", "choose_replacement"):
            return "inherited"
    if (decision.get("context", {}).get("kind") == "choice" and kinds
            and (kinds <= {"choose_target", "finish_target_selection"}
                 or kinds == {"choose_cost_target"}
                 or kinds <= {"select_object", "finish_selection"}
                 and all(c["semantic"].get("kind") != "finish_selection"
                         or c["semantic"].get("purpose") != "modes" for c in decision["candidates"]))):
        return "target"
    if (decision.get("context", {}).get("kind") == "choice" and kinds
            and kinds <= {"choose_spell_mode", "finish_selection"}
            and all(c["semantic"].get("kind") != "finish_selection"
                    or c["semantic"].get("purpose") == "modes" for c in decision["candidates"])):
        return "mode"
    raise ValueError("original player callback family is not connected")


class _LondonPlan:
    def __init__(self, start, decision, result):
        objects, offered = london_view(start, decision)
        group = decision["group"]
        own = next(p for p in decision["observation"]["players"] if p["seat"] == start["seat"])
        plan = result.get("london_plan")
        if (group["substep_index"] != 0 or len(objects) > 7
                or type(own.get("mulligans_taken")) is not int or own["mulligans_taken"] != group["substep_count"]
                or result.get("original_london_path") is not True or not isinstance(plan, dict)
                or set(plan) != {"group_id", "count", "bottomed"}
                or type(plan.get("group_id")) is not int or plan["group_id"] != group["group_id"]
                or type(plan.get("count")) is not int or plan["count"] != group["substep_count"]
                or not isinstance(plan.get("bottomed"), list) or len(plan["bottomed"]) != plan["count"]
                or any(not isinstance(ref, str) or ref not in objects for ref in plan["bottomed"])
                or len(set(plan["bottomed"])) != plan["count"]):
            raise ValueError("original London result lost its complete bound bottom sequence")
        bound_selection(result["selection"], offered)
        if result["selection"]["semantic_echo"]["item"]["object"]["object_id"] != plan["bottomed"][0]:
            raise ValueError("original London first selection differs from its bottom sequence")
        self.start, self.initial = copy.deepcopy(start), copy.deepcopy(decision)
        self.bottomed, self.next_index = list(plan["bottomed"]), 0
        self.world_flags = copy.deepcopy(result.get("world_flags", []))

    def select(self, decision):
        objects, offered = london_view(self.start, decision)
        group, initial = decision["group"], self.initial["group"]
        if (group["group_id"] != initial["group_id"] or group["substep_count"] != len(self.bottomed)
                or group["substep_index"] != self.next_index or self.next_index >= len(self.bottomed)
                or decision["seat_step"] != self.initial["seat_step"] + self.next_index
                or wire.canonical_json_dumps(decision["observation"]) != wire.canonical_json_dumps(self.initial["observation"])
                or {s["item"]["object"]["object_id"] for s in offered.values()} != set(objects)-set(self.bottomed[:self.next_index])):
            raise ValueError("original London substep changed its observation, group or remaining hand")
        selected = [(cid, semantic) for cid, semantic in offered.items()
                    if semantic["item"]["object"]["object_id"] == self.bottomed[self.next_index]]
        if len(selected) != 1:
            raise ValueError("original London bottom card is not offered")
        self.next_index += 1
        cid, semantic = selected[0]
        return {"candidate_id": cid, "semantic_echo": copy.deepcopy(semantic)}


class _CombatPlan(CombatPlan):
    def __init__(self, decision, result):
        viewer, objects = battlefield(decision)
        family = combat_kind(decision)
        if result.get("original_combat_path") is not True or result.get("combat") != family or not isinstance(result.get("pairs"), list):
            raise ValueError("original combat result lost its callback path or complete plan")
        name, reference = ("attacker", "defender") if family == "attack" else ("blocker", "attacker")
        seen = set()
        for pair in result["pairs"]:
            if not isinstance(pair, dict) or set(pair) != {name, reference}:
                raise ValueError("original combat pair has another schema")
            oid = pair[name]
            if (not isinstance(oid, str) or oid not in objects or oid in seen
                    or objects[oid].get("controller_seat") != viewer):
                raise ValueError("original combat pair repeats or changes its own creature")
            seen.add(oid)
            if family == "attack":
                defender = target(pair[reference])
                if (defender is None or defender.get("player") == viewer
                        or "object_id" in defender and (defender["object_id"] not in objects
                            or objects[defender["object_id"]].get("controller_seat") == viewer)):
                    raise ValueError("original combat plan has an unbound defender")
            else:
                opposing = pair[reference]
                if (not isinstance(opposing, str) or opposing not in objects
                        or objects[opposing].get("controller_seat") == viewer
                        or objects[opposing].get("permanent", {}).get("attacking") is not True):
                    raise ValueError("original combat plan has an unbound attacker")
        self._initialize(decision, result)
        slots = result.get("combat_slots")
        if (not isinstance(slots, list) or not 1 <= len(slots) <= 4096
                or len(slots) != self.group["substep_count"]
                or any(not isinstance(oid, str) or oid not in objects
                       or objects[oid].get("controller_seat") != viewer for oid in slots)
                or not seen <= set(slots)):
            raise ValueError("original combat result lost its complete engine slot schedule")
        runs = [oid for i, oid in enumerate(slots) if i == 0 or oid != slots[i - 1]]
        if len(set(runs)) != len(runs) or family == "attack" and len(runs) != len(slots):
            raise ValueError("original combat slot schedule revisits a creature")
        self.slots = list(slots)
        self.world_flags = copy.deepcopy(result.get("world_flags", []))

    def select(self, decision):
        if self.failed or self.complete:
            raise ValueError("original combat plan is complete or failed")
        try:
            group = self._group(decision)
            if (combat_kind(decision) != self.family or group["group_id"] != self.group["group_id"]
                    or group["substep_count"] != len(self.slots) or group["substep_index"] != self.next_index
                    or type(decision.get("seat_step")) is not int
                    or decision["seat_step"] != self.first_step + self.next_index
                    or decision.get("acting_seat") != self.viewer
                    or decision.get("context", {}).get("rewind") is not False):
                raise ValueError("original combat declaration group is stale, skipped or rewound")
            self._state(decision)
            candidates = decision["candidates"]
            ids = [candidate.get("candidate_id") for candidate in candidates]
            if (any(type(cid) is not int or not 0 <= cid <= wire.MAX_JSON_INT for cid in ids)
                    or len(set(ids)) != len(ids)):
                raise ValueError("original combat candidate ids are invalid or aliased")
            name, reference = ("attacker", "defender") if self.family == "attack" else ("blocker", "attacker")
            oid = self.slots[self.next_index]
            if any(candidate.get("semantic", {}).get(name, {}).get("object_id") != oid for candidate in candidates):
                raise ValueError("original combat declaration changed its scheduled creature")
            # The original blocker pool removes a creature after assigning it once.
            # Extra engine slots for that blocker therefore decline, preserving
            # both its original assignment and the observation bound to it.
            pairs = self.result["pairs"] if oid not in self.picks else [
                pair for pair in self.result["pairs"] if pair[name] != oid]
            selection = select_candidate(decision, {**self.result, "pairs": pairs, "decision_sha256": digest(decision)})
            chosen = selection["semantic_echo"][reference]
            if oid not in self.picks:
                self.picks[oid] = target(chosen) if self.family == "attack" else None if chosen is None else chosen["object_id"]
            self.next_index += 1
            return selection
        except BaseException:
            self.failed = True
            raise


class JackNativeAgent:
    """Always enter the actual original callback, including forced choices."""
    def __init__(self, factory, *, checkpoint, profile, audit=None):
        if not isinstance(checkpoint, str) or not checkpoint or profile not in PROFILES:
            raise ValueError("original frontend needs its checkpoint and declared profile")
        self.factory, self.checkpoint, self.profile = factory, checkpoint, profile
        self.audit = audit or (lambda event: None)
        self.session = self.game = self.history = self.key = self.start = self.step = None
        self.anchor_seeds = None
        self.london = None
        self.combat = None
        self.failed = False

    def on_game_start(self, game: GameStart):
        if self.failed or self.game is not None:
            raise ValueError("original frontend already has a game or has failed")
        try:
            if game.seat not in ("p0", "p1") or not isinstance(game.rules, dict):
                raise ValueError("original frontend needs a playing seat and declared rules")
            if game.rules.get("opponent_decklist") != "visible" and game.opponent_deck is not None:
                raise ValueError("hidden opponent deck was supplied to the original frontend")
            if game.engine_profile.get("observation", {}).get("passed_seats") is not True:
                raise ValueError("original replay requires public passed-seat observations")
            self.key = game_key(game.agent_seed)
            self.start = {key: copy.deepcopy(game.raw[key]) for key in _START_FIELDS if key in game.raw}
            wire.canonical_json_dumps(self.start)
            self.game, self.history = copy.deepcopy(game), PublicHistory(game.seat)
            self.session = self.factory(copy.deepcopy(self.start))
            if (self.session.checkpoint != self.checkpoint or self.session.profile != self.profile
                    or type(self.session.seed) is not int or self.session.seed != game.agent_seed
                    or digest(self.session.start) != digest(self.start)):
                raise ValueError("original frontend session differs from its checkpoint, profile or game")
            self.audit({"event": "jack_original_game_start", "checkpoint": self.checkpoint,
                        "profile": self.profile, "full_original_player_qualified": False})
        except BaseException as failure:
            self._fail(failure)
            raise

    def _record(self, decision):
        received = {key: copy.deepcopy(decision.raw["decision"][key]) for key in _DECISION_FIELDS
                    if key in decision.raw["decision"]}
        received["x_history"] = self.history.fields(received["observation"])
        received["x_observation_flags"] = copy.deepcopy(self.game.engine_profile["observation"])
        return {"game_start": copy.deepcopy(self.start), "decision": received,
                "world_seed": hmac.digest(self.key, f"world:{decision.seat_step}:0".encode(), "sha256").hex(),
                "id_seed": hmac.digest(self.key, b"ids", "sha256").hex()}

    def choose(self, decision: Decision):
        if self.failed or self.game is None or self.session is None:
            raise ValueError("original frontend is inactive or has failed")
        started = time.monotonic()
        try:
            if decision.game_id != self.game.game_id or decision.acting_seat != self.game.seat:
                raise ValueError("original decision belongs to another game or viewer")
            if (type(decision.seat_step) is not int or not 0 <= decision.seat_step <= wire.MAX_JSON_INT
                    or self.step is not None and decision.seat_step != self.step + 1):
                raise ValueError("original decision seat step is stale or skipped")
            if decision.context.get("rewind") is not False:
                raise ValueError("original frontend does not support a rewound action")
            clocks = [decision.clock.get(key) for key in ("remaining_ms", "max_decision_ms")]
            if any(type(value) is not int or value <= 0 for value in clocks):
                raise ValueError("original decision needs positive remaining and maximum clocks")
            budget = min(clocks) / 1000
            deadline = started + budget - min(0.1, budget / 20)

            def remaining():
                seconds = deadline - time.monotonic()
                if seconds <= 0:
                    raise TimeoutError("original frontend exhausted its shared decision clock")
                return seconds

            bound_decision(decision.raw["decision"], self.game.seat)
            self.history.observe(decision.observation)
            record = self._record(decision)
            current, kind = record["decision"], family(record["decision"])
            if self.london is not None and kind != "london":
                raise ValueError("original London group ended before its bottom sequence completed")
            if self.combat is not None and kind not in ("attack", "block"):
                raise ValueError("original combat group ended before its declarations completed")
            if kind in ("attack", "block"):
                group = CombatPlan._group(current)
                if self.combat is None and group["substep_index"] != 0:
                    raise ValueError("original combat needs its initial declaration group")
            if kind == "london":
                objects, _ = london_view(self.start, current)
                own = next(p for p in current["observation"]["players"] if p["seat"] == self.game.seat)
                if (len(objects) > 7 or type(own.get("mulligans_taken")) is not int
                        or own["mulligans_taken"] != current["group"]["substep_count"]
                        or self.london is None and current["group"]["substep_index"] != 0):
                    raise ValueError("original London needs its initial observed bottom group")
            resolving = (self.history.anchor is not None
                         and self.history.anchor["selection"]["semantic_echo"].get("kind") == "pass")
            continuing = (kind == "priority" and self.history.anchor is not None
                          and (self.history.anchor["selection"]["semantic_echo"].get("kind") in _ACTIVATIONS
                               or resolving and (self.history.anchor["decision"]["observation"].get("stack")
                                    or phase_advance(self.history.anchor["decision"], current, self.game.seat))))
            if kind in ("binary", "x", "amount", "inherited", "mode", "named", "target") or continuing:
                if (self.history.anchor is None or self.history.anchor["selection"]["semantic_echo"].get("kind")
                        not in _ACTIVATIONS | {"pass"}):
                    raise ValueError("original callback has no recorded activation anchor")
                if resolving:
                    record.update(anchor=copy.deepcopy(self.history.anchor), replay={
                        "priority_passes": resolution_passes(self.history.anchor["decision"], current, self.game.seat),
                        "earlier": copy.deepcopy(self.history.earlier)})
                else:
                    record.update(anchor=copy.deepcopy(self.history.anchor),
                                  replay={"priority_passes": [], "earlier": copy.deepcopy(self.history.earlier)})
                # Reconstruct the saved priority world throughout this activation.
                # Replaying prior choices must not resample its hidden world.
                record.update(self.anchor_seeds)
                bound_replay(record, self.game.seat)
            wire.canonical_json_dumps(record)
            if kind in ("attack", "block") and self.combat is not None:
                selection = self.combat.select(current)
                result = {"selection": selection, "decision_sha256": digest(current), "game_start_sha256": digest(self.start),
                          "profile": self.profile, "seed": self.game.agent_seed, "full_original_player_qualified": False,
                          "inference_requests": 0, "world_flags": copy.deepcopy(self.combat.world_flags), "original_combat_path": True}
            elif kind == "london" and self.london is not None:
                selection = self.london.select(current)
                result = {"selection": selection, "decision_sha256": digest(current), "game_start_sha256": digest(self.start),
                          "profile": self.profile, "seed": self.game.agent_seed, "full_original_player_qualified": False,
                          "inference_requests": 0, "world_flags": copy.deepcopy(self.london.world_flags), "original_london_path": True}
            else:
                result = self.session.choose(record, timeout_s=remaining())
                if kind in ("attack", "block"):
                    self.combat = _CombatPlan(current, result)
                    if digest(self.combat.select(current)) != digest(result["selection"]):
                        raise ValueError("original combat first bound choice changed")
                if kind == "london":
                    self.london = _LondonPlan(self.start, current, result)
                    selection = self.london.select(current)
                    if digest(selection) != digest(result["selection"]):
                        raise ValueError("original London first bound choice changed")
            remaining()
            if (not isinstance(result, dict) or result.get("decision_sha256") != digest(current)
                    or result.get("game_start_sha256") != digest(self.start)
                    or result.get("profile") != self.profile or type(result.get("seed")) is not int
                    or result["seed"] != self.game.agent_seed
                    or result.get("full_original_player_qualified") is not False):
                raise ValueError("original frontend result lost its bound game or decision")
            selection = result.get("selection")
            bound_selection(selection, bound_decision(current, self.game.seat))
            if kind == "priority":
                if type(result.get("priority_pass_after_activation")) is not bool:
                    raise ValueError("original frontend lost its priority continuation")
                priority_state(result.get("original_priority_state"), current)
                if continuing:
                    deferred = result.get("original_activation_pass_deferred")
                    if (result.get("original_priority_continuation") is not True or type(deferred) is not bool
                            or (result.get("original_resolution_path") is not True if resolving else result.get("original_activation_path") is not True)
                            or type(result.get("original_dialog_prefix_replayed")) is not int
                            or result["original_dialog_prefix_replayed"] != len(record["replay"]["earlier"])
                            or (deferred or record["anchor"]["priority_pass_after_activation"])
                            and (selection["semantic_echo"].get("kind") != "pass" or result.get("inference_requests") != 0)):
                        raise ValueError("original priority continuation lost its completed activation or automatic pass")
            if resolving and "anchor" in record:
                if (result.get("original_resolution_path") is not True or result.get("original_activation_path") is not False
                        or type(result.get("original_priority_passes_replayed")) is not int
                        or result["original_priority_passes_replayed"] != len(record["replay"]["priority_passes"])):
                    raise ValueError("original resolution lost its actual path or recorded pass order")
                if cleanup_discard(record["anchor"]["decision"], current, self.game.seat) and result.get("original_cleanup_path") is not True:
                    raise ValueError("original cleanup lost its actual end-step transition")
                if phase_advance(record["anchor"]["decision"], current, self.game.seat) and result.get("original_phase_advance_path") is not True:
                    raise ValueError("original phase advance lost its actual engine resume")
            if kind not in ("mulligan", "london", "attack", "block"):
                self.history.selected(current, selection)
            if kind == "priority":
                self.history.anchor.update({key: copy.deepcopy(result[key]) for key in (
                    "priority_pass_after_activation", "original_priority_state")})
                self.anchor_seeds = {key: record[key] for key in ("world_seed", "id_seed")}
            self.step = decision.seat_step
            if self.london is not None and self.london.next_index == len(self.london.bottomed):
                self.london = None
            if self.combat is not None and self.combat.complete:
                self.combat = None
            self.audit({"event": "jack_original_choice", "seat_step": self.step, "family": kind,
                        "selection": copy.deepcopy(selection), "inference_requests": result.get("inference_requests"),
                        "world_flags": copy.deepcopy(result.get("world_flags", []))})
            remaining()
            return selection["candidate_id"]
        except BaseException as failure:
            self._fail(failure)
            raise

    def _fail(self, failure):
        self.failed = True
        try:
            self.close()
        except BaseException as cleanup:
            if hasattr(failure, "add_note"):
                failure.add_note("Original frontend cleanup also failed: " + str(cleanup))

    def on_game_over(self, game: GameOver):
        try:
            if self.game is None or game.game_id != self.game.game_id:
                raise ValueError("original terminal belongs to another game")
            self.close()
            self.game = self.history = self.key = self.start = self.step = self.anchor_seeds = self.london = self.combat = None
        except BaseException as failure:
            self._fail(failure)
            raise

    def close(self):
        session, self.session = self.session, None
        if session is not None:
            session.close()

    def public_session(self, *, name, version):
        return BotSession(choose=self.choose, on_game_start=self.on_game_start,
                          on_game_over=self.on_game_over, name=name, version=version,
                          requires_observation=("passed_seats", "keywords"))
