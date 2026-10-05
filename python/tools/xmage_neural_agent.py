"""Public v2 frontend for the declared fair Exp1 search port.

Complete-game qualification is still required. Unsupported callbacks, rewinds
and reconstruction failures end this agent's session without a substitute bot.
"""
from __future__ import annotations

import copy
import hmac
import time

from spellbench import wire
from spellbench.bot import BotSession, Decision, GameOver, GameStart
from xmage_neural_combat import CombatPlan, combat_kind
from xmage_neural_search import root_family
from xmage_neural_decisions import close_resources

PROFILE = {
    "name": "exp1-permitted-worlds-minimum-visits-v1",
    "tree": "fresh per received root",
    "search_budget": "minimum_root_visits_until_legal_future",
    "search_clock": "shared host decision clock; abort incomplete work",
    "search_timeout_seconds": 600,
    "source_default_search_timeout_seconds": 4,
    "source_default_visit_budget": 1000,
    "prior_temperature": "1.5",
    "prior_bonus": "0.1",
    "puct_constant": "1",
    "backprop_discount": "0.99",
    "selection_temperature": 0,
    "root_noise": False,
    "opponent_hand_encoding": False,
    "mulligan": "original constructor default allowMulligans=false",
    "modes": "original numeric mode ordinals; offered-choice binding; original unoffered-branch accounting",
    "cleanup": "recorded end-step pass and public completed passes; original discard callback and full observation comparison",
    "full_game_qualified": False,
}
_START_FIELDS = ("seat", "format", "own_deck", "opponent_deck", "rules", "engine",
                 "engine_profile", "time_control", "limits", "resources", "agent_seed")
_DECISION_FIELDS = ("acting_seat", "seat_step", "observation", "context", "candidates", "group", "extensions")


def game_key(seed: int) -> bytes:
    if type(seed) is not int or not 0 <= seed <= wire.MAX_JSON_INT:
        raise ValueError("Exp1 needs its nonnegative protocol agent seed")
    return hmac.digest(seed.to_bytes(8, "big"), b"spellbench-xmage-kit/v1/game", "sha256")


def _cards(observation):
    for player in observation.get("players", []):
        for zone in ("hand", "battlefield", "graveyard", "exile"):
            yield from player.get(zone) or []
    for entry in observation.get("stack", []):
        if entry.get("stack_kind") == "spell":
            yield entry


class PublicHistory:
    """Remember only this seat's visible names, choices and confirmed costs."""
    def __init__(self, seat):
        self.seat = seat
        self.origins, self.activations = {}, []
        self.anchor, self.earlier = None, []

    def loyalty(self, observation, oid):
        for player in observation.get("players", []):
            if player.get("seat") == self.seat:
                for card in player.get("battlefield", []):
                    if card.get("object_id") == oid:
                        return (card.get("permanent") or {}).get("counters", {}).get("loyalty")
        return None

    def observe(self, observation):
        for card in _cards(observation):
            oid, name = card.get("object_id"), card.get("card_name")
            if isinstance(oid, str) and isinstance(name, str):
                self.origins.setdefault(oid, name)
        turn = observation.get("turn")
        self.activations = [a for a in self.activations if a["turn"] == turn]
        for activation in self.activations:
            now = self.loyalty(observation, activation["object_id"])
            on_stack = any(e.get("stack_kind") == "activated_ability"
                           and (e.get("source") or {}).get("object_id") == activation["object_id"]
                           for e in observation.get("stack", []))
            if (type(now) is int and now != activation["before"]) or on_stack:
                activation["confirmed"] = True

    def fields(self, observation):
        renamed = {c["object_id"]: self.origins[c["object_id"]] for c in _cards(observation)
                   if c.get("object_id") in self.origins and isinstance(c.get("card_name"), str)
                   and c["card_name"] != self.origins[c["object_id"]]}
        return {"loyalty_used": sorted({a["object_id"] for a in self.activations if a["confirmed"]}),
                "card_origins": dict(sorted(renamed.items()))}

    def callback(self, decision):
        if self.anchor is None:
            raise ValueError("callback has no recorded own priority anchor")
        observation = decision["observation"]
        previous = self.anchor["decision"]["observation"]
        action = self.anchor["selection"]["semantic_echo"]
        cleanup = self.cleanup_discard(decision, previous, action)
        if (observation.get("turn"), observation.get("phase_step")) != (
                previous.get("turn"), previous.get("phase_step")) and not cleanup:
            raise ValueError("callback crossed an unrecorded turn or phase transition")
        passes = []
        if action.get("kind") == "pass":
            if not previous.get("stack") and not cleanup:
                raise ValueError("callback followed an empty-stack pass without a public replay anchor")
            # The other seat must pass before the saved top object resolves
            # or the recorded end step finishes, unless it had already passed.
            # Java replay compares every resulting observation. Any intervening
            # response, callback or changed object is refused there.
            other = "p1" if self.seat == "p0" else "p0"
            passed = previous.get("passed_seats")
            if not isinstance(passed, list) or any(p not in ("p0", "p1") for p in passed):
                raise ValueError("callback anchor needs public passed-seat facts")
            if other not in passed:
                passes.append(other)
        elif action.get("kind") not in ("cast_spell", "activate_ability"):
            raise ValueError("callback has no replayable recorded action")
        return {"anchor": copy.deepcopy(self.anchor),
                "replay": {"priority_passes": passes, "earlier": copy.deepcopy(self.earlier)}}

    def cleanup_discard(self, decision, previous, action):
        observation = decision["observation"]
        context = decision.get("context", {})
        completed = observation.get("passed_seats")
        if not (action.get("kind") == "pass" and previous.get("phase_step") == "end_step"
                and observation.get("phase_step") == "cleanup"
                and type(previous.get("turn")) is int and type(observation.get("turn")) is int
                and observation["turn"] == previous["turn"]
                and previous.get("active_seat") == observation.get("active_seat") == self.seat
                and observation.get("viewer") == decision.get("acting_seat") == self.seat
                and not previous.get("stack") and not observation.get("stack")
                and observation.get("priority_seat") is None
                and isinstance(completed, list) and len(completed) == 2 and set(completed) == {"p0", "p1"}
                and context.get("kind") == "choice" and context.get("purpose") == "discard"
                and context.get("source") is None):
            return False
        candidates = decision.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return False
        for candidate in candidates:
            semantic = candidate.get("semantic", {})
            obj = semantic.get("choice", {}).get("object", {})
            if not (semantic.get("kind") == "select_object" and semantic.get("purpose") == "discard"
                    and semantic.get("source") is None and semantic.get("minimum") == 1
                    and semantic.get("maximum") == 1 and semantic.get("selected_count") == 0
                    and obj.get("zone") == "hand" and obj.get("owner_seat") == self.seat
                    and obj.get("controller_seat") == self.seat):
                return False
        # These facts permit replaying the original end-step completion. Java
        # must still reach the actual discard callback and compare its entire
        # observation before any search. Earlier discard picks stay in history.
        return True

    def selected(self, decision, selection):
        semantic = selection["semantic_echo"]
        observation = decision["observation"]
        if semantic.get("kind") == "activate_ability":
            oid = (semantic.get("source") or {}).get("object_id")
            before = self.loyalty(observation, oid)
            if type(before) is int:
                self.activations.append({"object_id": oid, "before": before,
                                         "turn": observation.get("turn"), "confirmed": False})
        entry = copy.deepcopy({"decision": decision, "selection": selection})
        if decision.get("context", {}).get("kind") == "priority":
            self.anchor, self.earlier = entry, []
        elif self.anchor is not None:
            self.earlier.append(entry)


class NeuralAgent:
    """Own one mixed search session through one public game lifecycle."""
    def __init__(self, factory, *, checkpoint: str, visits: int = 1000, audit=None,
                 profile=None, plan_factory=None):
        if type(visits) is not int or not 2 <= visits <= 1000:
            raise ValueError("Exp1 visits must be 2..1000")
        self.factory, self.checkpoint, self.visits = factory, checkpoint, visits
        self.audit = audit or (lambda event: None)
        self.profile = copy.deepcopy(PROFILE if profile is None else profile)
        self.plan_factory = CombatPlan if plan_factory is None else plan_factory
        self.session = self.game = self.history = self.key = self.plan = None
        self.failed = False
        self.step = None

    def on_game_start(self, game: GameStart):
        if self.failed or self.game is not None:
            raise ValueError("neural agent already has a game or has failed")
        try:
            if game.seat not in ("p0", "p1") or not isinstance(game.own_deck, dict):
                raise ValueError("neural game needs its seat and permitted own deck")
            if game.rules.get("opponent_decklist") != "visible" and game.opponent_deck is not None:
                raise ValueError("hidden opponent deck was supplied to the neural agent")
            if game.engine_profile.get("observation", {}).get("passed_seats") is not True:
                raise ValueError("neural replay requires public passed-seat observations")
            self.key = game_key(game.agent_seed)
            self.game = copy.deepcopy(game)
            self.history = PublicHistory(game.seat)
            self.session = self.factory()
            if self.session.model.checkpoint != self.checkpoint:
                raise ValueError("neural session checkpoint differs from its public bot identity")
            self.audit({"event": "neural_game_start", "checkpoint": self.checkpoint,
                        "visits": self.visits, "profile": copy.deepcopy(self.profile)})
        except BaseException as failure:
            self.failed = True
            close_resources(self, failure=failure)
            raise

    def _record(self, decision):
        received = {key: copy.deepcopy(decision.raw["decision"][key]) for key in _DECISION_FIELDS
                    if key in decision.raw["decision"]}
        received["x_history"] = self.history.fields(received["observation"])
        received["x_observation_flags"] = copy.deepcopy(self.game.engine_profile["observation"])
        start = {key: copy.deepcopy(self.game.raw[key]) for key in _START_FIELDS if key in self.game.raw}
        return {"game_start": start, "decision": received,
                "world_seed": hmac.digest(self.key, f"world:{decision.seat_step}:0".encode(), "sha256").hex(),
                "id_seed": hmac.digest(self.key, b"ids", "sha256").hex()}

    def choose(self, decision: Decision) -> int:
        if self.failed or self.game is None or self.session is None:
            raise ValueError("neural agent is inactive or has failed")
        started = time.monotonic()
        try:
            if (decision.game_id != self.game.game_id or decision.acting_seat != self.game.seat
                    or decision.observation.get("viewer") != self.game.seat):
                raise ValueError("neural decision belongs to another game or viewer")
            if (type(decision.seat_step) is not int or not 0 <= decision.seat_step <= wire.MAX_JSON_INT
                    or self.step is not None and decision.seat_step != self.step + 1):
                raise ValueError("neural decision seat step is stale or skipped")
            if decision.context.get("rewind") is not False:
                raise ValueError("neural history does not support a rewound action")
            clocks = [decision.clock.get(key) for key in ("remaining_ms", "max_decision_ms")]
            if any(type(value) is not int or value <= 0 for value in clocks):
                raise ValueError("neural decision needs its positive remaining and maximum clocks")
            budget = min(clocks) / 1000
            deadline = started + budget - min(0.1, budget / 20)

            def remaining():
                value = deadline - time.monotonic()
                if value <= 0:
                    raise TimeoutError("neural frontend exhausted the shared decision clock")
                return value

            self.history.observe(decision.observation)
            record = self._record(decision)
            received = record["decision"]
            kinds = {candidate.semantic.get("kind") for candidate in decision.candidates}
            result = None
            if self.plan is not None and not self.plan.complete and kinds not in (
                    {"declare_attack"}, {"declare_block"}):
                raise ValueError("neural combat group ended before all declarations")
            if kinds in ({"declare_attack"}, {"declare_block"}):
                family = combat_kind(received)
                if self.plan is None or self.plan.complete:
                    result = self.session.plan(record, visits=self.visits, timeout_s=remaining())
                    self.plan = self.plan_factory(received, result, visits=self.visits)
                selection = self.plan.select(received)
            elif kinds == {"mulligan"}:
                # This is the original newly constructed player's shipped flag,
                # not a guessed neural decision or another bot's keep heuristic.
                offered = [c for c in decision.candidates if c.semantic.get("keep") is True]
                if len(offered) != 1:
                    raise ValueError("original default mulligan keep is unoffered or aliased")
                selection = {"candidate_id": offered[0].candidate_id, "semantic_echo": offered[0].semantic}
                family = "original_default_mulligan_keep"
            else:
                family = root_family(received)
                if family != "priority":
                    record.update(self.history.callback(received))
                if len(decision.candidates) == 1:
                    candidate = decision.candidates[0]
                    selection = {"candidate_id": candidate.candidate_id, "semantic_echo": candidate.semantic}
                else:
                    result = self.session.choose(record, visits=self.visits, timeout_s=remaining())
                    selection = result["selection"]
            remaining()
            offered = [c for c in decision.candidates if type(selection.get("candidate_id")) is int
                       and c.candidate_id == selection["candidate_id"]
                       and c.semantic == selection.get("semantic_echo")]
            if len(offered) != 1 or result is not None and result.get("checkpoint") != self.checkpoint:
                raise ValueError("neural choice is unoffered or belongs to another checkpoint")
            self.history.selected(received, selection)
            self.step = decision.seat_step
            self.audit({"event": "neural_choice", "seat_step": self.step, "family": family,
                        "selection": selection, "neural_calls": 0 if result is None else result["neural_calls"],
                        "world_flags": [] if result is None else result.get("world_flags", [])})
            remaining()
            return selection["candidate_id"]
        except BaseException as exc:
            self.failed = True
            try:
                self.audit({"event": "neural_failure", "seat_step": decision.seat_step,
                            "error": f"{type(exc).__name__}: {exc}"})
            except BaseException as audit_error:
                exc.add_note("Neural failure audit failed: " + str(audit_error))
            close_resources(self, failure=exc)
            raise

    def on_game_over(self, game: GameOver):
        if self.game is None or game.game_id != self.game.game_id:
            raise ValueError("neural terminal belongs to another game")
        self.close()
        self.game = self.history = self.key = self.plan = self.step = None

    def close(self):
        session, self.session = self.session, None
        if session is not None:
            session.close()

    def public_session(self, *, name, version):
        return BotSession(choose=self.choose, on_game_start=self.on_game_start,
                          on_game_over=self.on_game_over, name=name, version=version,
                          requires_observation=("passed_seats", "keywords"))
