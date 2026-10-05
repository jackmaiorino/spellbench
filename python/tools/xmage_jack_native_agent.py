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
from xmage_jack_native_session import bound_decision, bound_replay, bound_selection, digest, priority_state
from xmage_neural_agent import PublicHistory, _DECISION_FIELDS, _START_FIELDS, game_key


def family(decision):
    kinds = {c["semantic"].get("kind") for c in decision["candidates"]}
    if decision["observation"].get("phase_step") == "pregame" and kinds == {"mulligan"}:
        return "mulligan"
    if decision.get("context", {}).get("kind") == "priority":
        return "priority"
    if decision.get("context", {}).get("kind") == "choice" and len(kinds) == 1:
        kind = next(iter(kinds))
        if kind in ("choose_boolean", "optional_cost", "choose_cast_method"):
            return "binary"
        if kind == "choose_number" and all(c["semantic"].get("purpose") == "x_value"
                                            for c in decision["candidates"]):
            return "x"
        if kind in ("choose_option", "choose_color", "choose_name"):
            return "named"
    if (decision.get("context", {}).get("kind") == "choice" and kinds
            and kinds <= {"choose_spell_mode", "finish_selection"}
            and all(c["semantic"].get("kind") != "finish_selection"
                    or c["semantic"].get("purpose") == "modes" for c in decision["candidates"])):
        return "mode"
    raise ValueError("original player callback family is not connected")


class JackNativeAgent:
    """Always enter the actual original callback, including forced choices."""
    def __init__(self, factory, *, checkpoint, profile, audit=None):
        if not isinstance(checkpoint, str) or not checkpoint or profile not in PROFILES:
            raise ValueError("original frontend needs its checkpoint and declared profile")
        self.factory, self.checkpoint, self.profile = factory, checkpoint, profile
        self.audit = audit or (lambda event: None)
        self.session = self.game = self.history = self.key = self.start = self.step = None
        self.anchor_seeds = None
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
            if kind == "priority" and self.history.anchor is not None:
                if self.history.anchor["priority_pass_after_activation"]:
                    raise ValueError("original pass-after-activation continuation is not connected")
            if kind in ("binary", "x", "mode", "named"):
                if (self.history.anchor is None or self.history.anchor["selection"]["semantic_echo"].get("kind")
                        not in ("cast_spell", "activate_ability")):
                    raise ValueError("original callback has no recorded activation anchor")
                record.update(self.history.callback(current))
                # Reconstruct the saved priority world throughout this activation.
                # Replaying prior choices must not resample its hidden world.
                record.update(self.anchor_seeds)
                bound_replay(record, self.game.seat)
            wire.canonical_json_dumps(record)
            result = self.session.choose(record, timeout_s=remaining())
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
                priority_state(result.get("original_priority_state"))
            if kind != "mulligan":
                self.history.selected(current, selection)
            if kind == "priority":
                self.history.anchor.update({key: copy.deepcopy(result[key]) for key in (
                    "priority_pass_after_activation", "original_priority_state")})
                self.anchor_seeds = {key: record[key] for key in ("world_seed", "id_seed")}
            self.step = decision.seat_step
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
            self.game = self.history = self.key = self.start = self.step = self.anchor_seeds = None
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
