"""The local play server behind the human seat: one page on 127.0.0.1, fed by the relay agent (``relay.py``).

The relay posts every request of the human seat here and blocks until it has an answer. The server answers what
needs no person (a lone candidate, priority passes outside the human's stops, the remaining substeps of a combat
plan) at once, so the page sees only real decisions. Everything else waits for the page. The page long-polls
``/api/state`` and posts answers, plans, stop settings and controls. Every request needs the session token: the
relay sends it as a header, the page carries it from its URL.

Each answered decision of the human seat is appended to ``<log_dir>/<game_id>.<seat>.jsonl`` (``LOG_SCHEMA``),
with how it was answered (``human``, ``plan``, ``single``, ``auto_pass``) and the wall time it took.

Mana: the kernel engine declares ``engine_autopay``, and its autopay spends only lands and plain tap-for-mana
sources. A spell affordable only with mana from a costed source (an Eldrazi Spawn's sacrifice, a Treasure) is not
offered until that mana is floating, unlike rule 601.2g, which lets a player activate mana abilities mid-cast. Every
outcome stays reachable (activate, then cast), so the page labels such sources "Activate" and shows a hint instead.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from . import narrate, text

LOG_SCHEMA = "spellbench-human-log/v1"
PAGE = Path(__file__).with_name("page.html")
PHASE_STEPS = ("upkeep", "draw", "precombat_main", "beginning_of_combat", "declare_attackers", "declare_blockers",
               "combat_damage", "end_of_combat", "postcombat_main", "end_step")
DEFAULT_STOPS = {f"{side}_{step}": False for side in ("own", "opp") for step in PHASE_STEPS}
DEFAULT_STOPS.update(own_precombat_main=True, own_postcombat_main=True, opp_stack=True, own_stack=False)
LOG_LIMIT = 600
# Answers the causal log already narrates from the engine's events (a cast, an activation, a target, a cost, an
# attack); other answers are echoed as "You choose: ...".
NARRATED_KINDS = frozenset({"pass", "cast_spell", "activate_ability", "activate_mana_ability", "play_land",
                            "choose_target", "finish_target_selection", "choose_cost_target", "declare_attack",
                            "declare_block", "special_action"})


def log_since(log: list[dict[str, Any]], total: int, cursor: int) -> tuple[list[dict[str, Any]], int]:
    """The lines of ``log`` (the newest ones of ``total`` ever appended) at or after position ``cursor``, and the
    new cursor (``total``). Positions count lines ever appended, so they keep meaning once the list is trimmed."""
    first = total - len(log)  # position of log[0]
    return list(log[max(cursor - first, 0):]), total


def _ms() -> int:
    return int(time.time() * 1000)


def real_actions(candidates: Any) -> list[Mapping[str, Any]]:
    """The candidates of a priority decision that are a real choice: everything but passing and mana abilities
    (floating mana alone does nothing, and the engine's autopay pays for spells). Read from the engine's own list of
    what is legal, so it names no card and no ability."""
    return [c for c in candidates or [] if (c.get("semantic") or {}).get("kind") not in ("pass", "activate_mana_ability")]


class Conceded(RuntimeError):
    """The person gave up the game: every later decision of it is refused so the arena ends it at once."""


class Hub:
    """All session state, guarded by one condition variable."""

    def __init__(self, *, log_dir: Path | None = None, games_total: int | None = None, label: str = "",
                 opponent: str = "the bot", record_root: Path | None = None, real_action_stops: bool = False) -> None:
        self.cond = threading.Condition()
        # True: the person gets every priority at which they have a legal action besides passing and mana abilities,
        # in any step of either turn and on any stack (the Manabrew path, which has no panel for stops). False: only
        # the stops of ``self.stops`` (the play page's S panel).
        self.real_action_stops = real_action_stops
        self.version = 0
        self.log_dir = log_dir
        self.label = label
        self.opponent = opponent
        self.games_total = games_total
        self.stops = dict(DEFAULT_STOPS)
        self.ready = False          # the human asked for the next game
        self.hello_waiting = False  # a relay is waiting for that
        self.game: dict[str, Any] | None = None
        self.results: list[dict[str, Any]] = []
        self.log: list[dict[str, Any]] = []
        self.log_total = 0          # lines ever appended this game (the list keeps only the newest LOG_LIMIT)
        self.observation: dict[str, Any] | None = None
        self.clock: dict[str, Any] | None = None
        self.pending: dict[str, Any] | None = None
        self.answer: int | None = None
        self.seq = 0
        self.plan: dict[str, Any] | None = None
        self.skip: dict[str, Any] | None = None  # {"turn", "active", "hard"}
        self.exhaust_stack = False  # pass every priority until the stack is empty (the client's "end turn" on a stack)
        self.game_over: dict[str, Any] | None = None
        self.conceded: str | None = None  # the game id the person gave up (or lost the connection to), if any
        self._log_file = None
        self._combat_logged: set[tuple[Any, str]] = set()
        # The causal log (narrate.py): fed from this session's own engine record when recording is on, else from
        # the human seat's decisions alone.
        self.record_root = record_root
        self.narrator: narrate.Narrator | None = None
        self._tail: narrate.RecordTail | None = None
        self._step: tuple[Any, Any, Any] | None = None

    # -- bookkeeping --------------------------------------------------------------------------------------------

    def _bump(self) -> None:
        self.version += 1
        self.cond.notify_all()

    def _note(self, side: str, line: str, *, depth: int = 0, facts: list | None = None, header: bool = False) -> None:
        turn = (self.observation or {}).get("turn")
        self.log.append({"side": side, "text": line, "turn": turn, "depth": depth, "facts": facts or [],
                         "header": header})
        self.log_total += 1
        del self.log[:-LOG_LIMIT]

    def log_since(self, cursor: int) -> tuple[list[dict[str, Any]], int]:
        """The log lines at or after position ``cursor`` (a count of lines ever appended this game, as returned by
        an earlier call; 0 for a reader that starts at the beginning) and the cursor to pass next time. A reader
        that fell more than LOG_LIMIT lines behind gets the oldest line still kept."""
        with self.cond:
            return log_since(self.log, self.log_total, cursor)

    def _write(self, record: dict[str, Any]) -> None:
        if self._log_file is not None:
            self._log_file.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            self._log_file.flush()

    def announce(self, text: str) -> None:
        """A game-level line for the log, kept until the next game starts (it is shown first in that game)."""
        with self.cond:
            self._announcement = text
            self._bump()

    # -- relay side ---------------------------------------------------------------------------------------------

    def wait_ready(self) -> None:
        with self.cond:
            self.hello_waiting = True
            self._bump()
            while not self.ready:
                self.cond.wait()
            self.hello_waiting = False
            self._bump()

    def game_start(self, request: Mapping[str, Any]) -> None:
        with self.cond:
            self.ready = False
            seat = request.get("seat")
            own = request.get("own_deck") or {}
            opp = request.get("opponent_deck") or {}
            self.game = {"game_id": request.get("game_id"), "seat": seat, "own_deck": own.get("name"),
                         "opp_deck": opp.get("name"), "number": len(self.results) + 1,
                         "bank_ms": (request.get("time_control") or {}).get("bank_ms"),
                         "rules": request.get("rules") or {}}
            self.log, self.observation, self.clock, self.pending = [], None, None, None
            self.log_total = 0
            self.plan = self.skip = self.game_over = None
            self.exhaust_stack = False
            self._combat_logged = set()
            self.narrator = narrate.Narrator(seat) if seat else None
            self._tail, self._step = None, None
            self._note("game", f"Game {self.game['number']}: you ({own.get('name')}, {seat}) vs {self.opponent} "
                               f"({opp.get('name')})")
            if getattr(self, "_announcement", None):
                self._note("game", self._announcement)
                self._announcement = None
            if self.log_dir is not None:
                self.log_dir.mkdir(parents=True, exist_ok=True)
                path = self.log_dir / f"{request.get('game_id')}.{seat}.jsonl"
                self._log_file = open(path, "w", encoding="utf-8", newline="\n")
                self._write({"schema": LOG_SCHEMA, "kind": "header", "game_id": request.get("game_id"), "seat": seat,
                             "bot_name": "Human", "own_deck": own, "opponent_deck": opp, "time_control": request.get("time_control"),
                             "label": self.label, "stops": self.stops})
            self._bump()

    def game_end(self, request: Mapping[str, Any]) -> None:
        with self.cond:
            if self.game_over is not None and self.conceded is not None and request.get("game_id") == self.conceded:
                return  # the arena's own notice of a game the person already ended
            terminal = dict(request.get("terminal") or {})
            me = (self.game or {}).get("seat")
            winner = terminal.get("winner")
            result = "draw" if winner is None else ("win" if winner == me else "loss")
            self.game_over = {**terminal, "result": result}
            self.results.append({"game_id": request.get("game_id"), "result": result,
                                 "reason": terminal.get("reason"), "own_deck": (self.game or {}).get("own_deck"),
                                 "seat": me})
            how = (terminal.get("reason") if terminal.get("classification") == terminal.get("reason")
                   else f"{terminal.get('classification')}: {terminal.get('reason')}")
            self._note("game", f"Game over: {'you win' if result == 'win' else 'you lose' if result == 'loss' else 'draw'}"
                               f" ({how})")
            self._write({"kind": "game_over", "terminal": terminal, "result": result})
            if self._log_file is not None:
                self._log_file.close()
                self._log_file = None
            self.pending = None
            self._bump()

    def close_game(self, game_id: str, terminal: Mapping[str, Any]) -> None:
        """End game ``game_id`` on the page if its relay never sent ``game_over`` (the host closed the seat after a
        timeout or a failed process): a pending decision is withdrawn and the page offers the next game."""
        with self.cond:  # a reentrant lock: game_end takes it again
            if self.game is not None and self.game.get("game_id") == game_id and self.game_over is None:
                self.game_end({"game_id": game_id, "terminal": dict(terminal)})

    def concede(self, reason: str = "conceded") -> bool:
        """The person ends the current game as a loss (``conceded``), or the session does when the person is gone
        (``connection_lost``). The page and the Manabrew client see the game over at once; a decision the engine
        is waiting on, and every later one, is refused (``Conceded``), which the arena records as the human seat's
        forfeit. Returns False when there is no game in progress."""
        with self.cond:
            game = self.game
            if game is None or self.game_over is not None or not game.get("game_id"):
                return False
            seat = game.get("seat")
            self.conceded = game["game_id"]
            self.game_end({"game_id": game["game_id"], "terminal": {
                "winner": "p1" if seat == "p0" else "p0", "classification": reason, "reason": reason}})
            return True

    def choose(self, request: Mapping[str, Any]) -> int:
        decision = request.get("decision") or {}
        with self.cond:
            if self.conceded is not None and self.game is not None and self.game.get("game_id") == self.conceded:
                raise Conceded(self.game_over.get("reason") if self.game_over else "conceded")
            started = time.monotonic()
            self._absorb(decision, request.get("clock") or {})
            if not (decision.get("observation") or {}).get("stack"):
                self.exhaust_stack = False  # the stack the person asked to pass through is empty
            how, candidate_id = self._automatic(decision)
            chosen_text = None
            if candidate_id is None:
                self._priority_note(decision)
                self.seq += 1
                self.pending = self._view(decision)
                self.answer = None
                self._bump()
                while self.answer is None or self.pending is None:
                    self.cond.wait()
                    if self.pending is None:  # the game ended underneath (host adjudication, or the person's concession)
                        if self.conceded is not None and self.game is not None and self.game.get("game_id") == self.conceded:
                            raise Conceded("conceded")
                        raise RuntimeError("decision withdrawn")
                candidate_id, how = self.answer, self.pending.get("how", "human")
                chosen_text = next((c["text"] for c in self.pending["candidates"] if c["id"] == candidate_id), None)
                self.pending = None
            chosen = next(c for c in decision["candidates"] if c["candidate_id"] == candidate_id)
            semantic = chosen.get("semantic") or {}
            me = (self.game or {}).get("seat")
            if semantic.get("kind") not in NARRATED_KINDS and how != "plan" and len(decision["candidates"]) > 1:
                label = chosen_text or text.candidate(semantic, me)
                self._note("you", f"You choose: {label}", depth=1, facts=[("choice", me)])
            self._write({"kind": "decision", "step": decision.get("seat_step"), "candidate_id": candidate_id,
                         "how": how, "elapsed_ms": int((time.monotonic() - started) * 1000),
                         "candidate_count": len(decision["candidates"]), "semantic": semantic,
                         "phase_step": (decision.get("observation") or {}).get("phase_step"),
                         "turn": (decision.get("observation") or {}).get("turn")})
            self._bump()
            return candidate_id

    # -- what the human sees ------------------------------------------------------------------------------------

    def _absorb(self, decision: Mapping[str, Any], clock: Mapping[str, Any]) -> None:
        """Fold one decision's observation and the engine events since the previous one into the log."""
        if self.narrator is not None:
            tail = self._record_tail()
            if tail is not None:
                for row in tail.read():
                    message = row.get("message") or {}
                    if row.get("dir") == "engine_to_host" and message.get("response_type") == "decision":
                        self.narrator.engine_decision(message["seat_decision"])
            else:
                self.narrator.engine_decision(decision)
            self.absorb_narrated(decision)
        else:
            self._absorb_plain(decision)
        self.observation = dict(decision.get("observation") or {})
        self.clock = {"remaining_ms": clock.get("remaining_ms"), "max_decision_ms": clock.get("max_decision_ms"),
                      "at": _ms()}

    def _record_tail(self) -> narrate.RecordTail | None:
        """This game's engine record, written by the runner in this process (operator recording on)."""
        if self._tail is None and self.record_root is not None and self.game is not None:
            found = sorted(Path(self.record_root).glob(f"game-*-{self.game.get('game_id')}-*/engine.jsonl"))
            if found:
                self._tail = narrate.RecordTail(found[-1])
        return self._tail

    def absorb_narrated(self, decision: Mapping[str, Any]) -> None:
        """Append the narrator's lines for the span ending at this human decision, then the combat declarations and
        the step the human is now in."""
        me = (self.game or {}).get("seat")
        observation = decision.get("observation") or {}
        history = ((decision.get("extensions") or {}).get("x_public_history_v1") or {}).get("events") or []
        lines = self.narrator.merge(history) + self.narrator.board_changes(observation)
        players = {p.get("seat"): p for p in observation.get("players") or []}
        last_life: dict[Any, int] = {}
        for n, line in enumerate(lines):
            for fact in line.get("facts") or []:
                if fact[0] == "life":
                    last_life[fact[1]] = n
        for seat, n in last_life.items():
            life = (players.get(seat) or {}).get("life")
            if life is not None:
                lines[n] = narrate.Line(lines[n], text=lines[n]["text"] + f" ({'you' if seat == me else 'Opp'}: {life} life)")
        for line in lines:
            if line.get("quiet"):  # accounted for by the line before it; not worth its own line
                if self.log:
                    self.log[-1]["facts"] = list(self.log[-1].get("facts") or []) + list(line.get("facts") or [])
                continue
            self._note(line["side"], line["text"], depth=line.get("depth", 0), facts=list(line.get("facts") or []),
                       header=bool(line.get("header") or line.get("step")))
        self._combat(observation, me)

    def _combat(self, observation: Mapping[str, Any], me: Any) -> None:
        """Attack and block declarations, from the observation's combat state."""
        turn_key = (observation.get("turn"), observation.get("active_seat"))
        for player in observation.get("players") or []:
            seat = player.get("seat")
            battlefield = player.get("battlefield") or []
            attackers = [c for c in battlefield if (c.get("permanent") or {}).get("attacking")]
            if attackers and (turn_key, "attack") not in self._combat_logged:
                self._combat_logged.add((turn_key, "attack"))
                parts = []
                for c in attackers:
                    aim = (c.get("permanent") or {}).get("attack_target")
                    parts.append(text.card(c) + (f" -> {text.target(aim, me)}" if isinstance(aim, Mapping) else ""))
                self._note("you" if seat == me else "opp", f"{text.seat_name(seat, me)} attack"
                           f"{'' if seat == me else 's'} with " + ", ".join(parts),
                           facts=[("attack", seat, text.card(c)) for c in attackers])
            blockers = [c for c in battlefield if (c.get("permanent") or {}).get("blocking")]
            if blockers and (turn_key, "block") not in self._combat_logged:
                self._combat_logged.add((turn_key, "block"))
                parts = []
                for c in blockers:
                    blocked = (c.get("permanent") or {}).get("blocked_attackers") or []
                    parts.append(f"{text.card(c)} blocks " + (", ".join(text.card(a) for a in blocked) or "?"))
                self._note("you" if seat == me else "opp", f"{text.seat_name(seat, me)} block"
                           f"{'' if seat == me else 's'}: " + "; ".join(parts),
                           facts=[("block", seat, text.card(c)) for c in blockers])

    def _absorb_plain(self, decision: Mapping[str, Any]) -> None:
        """The log before a game has a seat: public history lines only."""
        me = (self.game or {}).get("seat")
        history = ((decision.get("extensions") or {}).get("x_public_history_v1") or {}).get("events") or []
        for side, line in text.history(history, me):
            self._note(side, line)

    def _automatic(self, decision: Mapping[str, Any]) -> tuple[str, int | None]:
        candidates = decision.get("candidates") or []
        if len(candidates) == 1:
            return "single", candidates[0]["candidate_id"]
        planned = self._from_plan(decision)
        if planned is not None:
            return "plan", planned
        context = decision.get("context") or {}
        if context.get("kind") != "priority":
            return "human", None
        kinds = {c["semantic"].get("kind") for c in candidates}
        passing = next((c["candidate_id"] for c in candidates if c["semantic"].get("kind") == "pass"), None)
        if passing is None:
            return "human", None
        if kinds <= {"pass", "activate_mana_ability"}:
            return "auto_pass", passing  # mana is paid automatically; floating it alone does nothing
        real = self.real_action_stops and bool(real_actions(candidates))
        return ("human", None) if self._stops_here(decision, real) else ("auto_pass", passing)

    def _stops_here(self, decision: Mapping[str, Any], real: bool = False) -> bool:
        """Whether this priority goes to the person. ``real``: they have a legal action besides passing and mana
        abilities and the session stops for those (``real_action_stops``), so a stop is not needed to be asked."""
        me = (self.game or {}).get("seat")
        observation = decision.get("observation") or {}
        stack = observation.get("stack") or []
        turn_key = (observation.get("turn"), observation.get("active_seat"))
        skip = self.skip
        if skip is not None and (skip["turn"], skip["active"]) != turn_key:
            self.skip = skip = None
        if stack:
            if self.exhaust_stack:
                return False
            top_mine = text.stack_top(stack).get("controller_seat") == me
            if top_mine:
                return (self.stops.get("own_stack", False) or real) and skip is None
            return (self.stops.get("opp_stack", True) or real) and not (skip is not None and skip["hard"])
        if skip is not None:
            return False
        if real:
            return True
        side = "own" if observation.get("active_seat") == me else "opp"
        return bool(self.stops.get(f"{side}_{observation.get('phase_step')}", False))

    def _from_plan(self, decision: Mapping[str, Any]) -> int | None:
        """The candidate a combat plan names for this substep, or ``None`` to ask the human."""
        plan = self.plan
        group = decision.get("group") or {}
        if plan is None or plan.get("group_id") != group.get("group_id"):
            self.plan = None
            return None
        candidates = decision.get("candidates") or []
        kinds = {c["semantic"].get("kind") for c in candidates}
        if plan["kind"] == "attack" and kinds == {"declare_attack"}:
            attacker = (candidates[0]["semantic"].get("attacker") or {}).get("object_id")
            wanted = attacker in plan["attackers"]
            for c in candidates:
                defender = c["semantic"].get("defender")
                if not wanted and defender is None:
                    return c["candidate_id"]
                if wanted and isinstance(defender, Mapping) and defender.get("player") not in (None, (self.game or {}).get("seat")):
                    return c["candidate_id"]
            return None
        if plan["kind"] == "block" and kinds == {"declare_block"}:
            blocker = (candidates[0]["semantic"].get("blocker") or {}).get("object_id")
            used = plan.setdefault("used", [])
            attacker = plan["blocks"].get(blocker) if blocker not in used else None
            used.append(blocker)
            for c in candidates:
                chosen = c["semantic"].get("attacker")
                if attacker is None and chosen is None:
                    return c["candidate_id"]
                if attacker is not None and isinstance(chosen, Mapping) and chosen.get("object_id") == attacker:
                    return c["candidate_id"]
            return None
        return None

    def _priority_note(self, decision: Mapping[str, Any]) -> None:
        """With stops for real actions, say in the log why the person has priority and what they can do, unless it is
        their own main phase with an empty stack (where they always do). Display only."""
        if not self.real_action_stops or (decision.get("context") or {}).get("kind") != "priority":
            return
        me = (self.game or {}).get("seat")
        observation = decision.get("observation") or {}
        stack = observation.get("stack") or []
        if (not stack and observation.get("phase_step") in text.MAIN_STEPS and observation.get("active_seat") == me):
            return
        lands = frozenset(o.get("object_id") for player in observation.get("players") or []
                          for o in player.get("battlefield") or []
                          if "land" in ((o.get("characteristics") or {}).get("types") or []))
        options = [text.candidate(c.get("semantic") or {}, me, lands) for c in real_actions(decision.get("candidates"))]
        shown = "; ".join(options[:6]) + (f"; and {len(options) - 6} more" if len(options) > 6 else "")
        why = f"Your priority in {text.where(observation, me)}"
        if stack:
            top = text.stack_top(stack)
            why += f", {text.seat_name(top.get('controller_seat'), me)}: {text.card(top)} on the stack"
        self._note("game", f"{why}. You can: {shown}", depth=1)

    def _view(self, decision: Mapping[str, Any]) -> dict[str, Any]:
        me = (self.game or {}).get("seat")
        observation = decision.get("observation") or {}
        lands = frozenset(o.get("object_id") for player in observation.get("players") or []
                          for o in player.get("battlefield") or []
                          if "land" in ((o.get("characteristics") or {}).get("types") or []))
        candidates = []
        for c in decision.get("candidates") or []:
            semantic = c.get("semantic") or {}
            candidates.append({"id": c["candidate_id"], "kind": semantic.get("kind"),
                               "text": text.candidate(semantic, me, lands), "engine_text": c.get("display_text"),
                               "refs": sorted(set(text.refs(semantic))), "semantic": semantic})
        options = text.effect_options(decision, me)
        if options is not None:  # an effect option: say what each option does where it can be known
            for c in candidates:
                c["text"] = options[1].get(c["id"], c["text"])
        kinds = {c["kind"] for c in candidates}
        group = decision.get("group") or {}
        screen = "generic"
        if kinds == {"declare_attack"} and group.get("substep_index") == 0:
            screen = "attack"
        elif kinds == {"declare_block"} and group.get("substep_index") == 0:
            screen = "block"
        # The engine's autopay only uses plain tap sources, so a spell payable only with mana from a costed source
        # (an Eldrazi Spawn's sacrifice, a Treasure) is not offered until that mana is floating.
        hint = None
        if any(c["kind"] == "activate_mana_ability" and (c["semantic"].get("source") or {}).get("object_id") not in lands
               for c in candidates):
            hint = ("Autopay only taps lands and plain mana sources: a spell that needs mana from an Activate source "
                    "(sacrifice, Treasure) appears once you activate it.")
        return {"seq": self.seq, "prompt": options[0] if options else text.prompt(decision, me),
                "context": decision.get("context"),
                "group": group, "candidates": candidates, "screen": screen, "hint": hint, "received_at": _ms()}

    # -- page side ----------------------------------------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        wins = sum(r["result"] == "win" for r in self.results)
        losses = sum(r["result"] == "loss" for r in self.results)
        return {"version": self.version, "label": self.label, "opponent": self.opponent, "games_total": self.games_total,
                "results": self.results, "wins": wins, "losses": losses, "draws": len(self.results) - wins - losses,
                "hello_waiting": self.hello_waiting, "ready": self.ready, "game": self.game,
                "observation": self.observation, "clock": self.clock, "pending": self.pending, "log": self.log,
                "log_total": self.log_total,
                "game_over": self.game_over, "stops": self.stops, "skip": self.skip, "now": _ms(),
                "phases": list(PHASE_STEPS)}

    def answer_with(self, seq: int, candidate_id: int) -> str | None:
        with self.cond:
            pending = self.pending
            if pending is None or pending["seq"] != seq:
                return "stale decision"
            if all(c["id"] != candidate_id for c in pending["candidates"]):
                return "not a candidate"
            pending["how"] = "human"
            self.answer = candidate_id
            self._bump()
            return None

    def plan_with(self, seq: int, plan: Mapping[str, Any]) -> str | None:
        with self.cond:
            pending = self.pending
            if pending is None or pending["seq"] != seq:
                return "stale decision"
            kind = plan.get("kind")
            if kind == "attack":
                self.plan = {"kind": "attack", "attackers": [str(a) for a in plan.get("attackers") or []]}
            elif kind == "block":
                self.plan = {"kind": "block", "blocks": {str(k): (None if v is None else str(v))
                                                         for k, v in (plan.get("blocks") or {}).items()}}
            else:
                return "unknown plan"
            self.plan["group_id"] = pending["group"].get("group_id")
            decision = {"candidates": [{"candidate_id": c["id"], "semantic": c["semantic"]}
                                       for c in pending["candidates"]], "group": pending["group"]}
            chosen = self._from_plan(decision)
            if chosen is None:
                self.plan = None
                return "the plan does not fit this declaration; choose substeps one by one"
            pending["how"] = "plan"
            self.answer = chosen
            self._bump()
            return None

    def pass_turn(self, seq: int, *, exhaust_stack: bool = False) -> str | None:
        """The person's "end turn" for the decision ``seq`` (the Manabrew client's button): pass this priority and
        every later one this turn that has no opponent spell on the stack, as the play page's pass-turn does. With
        ``exhaust_stack`` (the button pressed while a spell is on the stack) pass every priority until the stack is
        empty instead."""
        with self.cond:
            pending = self.pending
            if pending is None or pending["seq"] != seq:
                return "stale decision"
            if (pending.get("context") or {}).get("kind") != "priority":
                return "not a priority decision"
            if exhaust_stack:
                self.exhaust_stack = True
                passing = next((c["id"] for c in pending["candidates"] if c["kind"] == "pass"), None)
                if passing is None:
                    return "passing is not a choice here"
                pending["how"] = "human"
                self.answer = passing
                self._bump()
                return None
            return self.control("pass_turn", {})

    def control(self, action: str, body: Mapping[str, Any]) -> str | None:
        with self.cond:
            if action in ("start", "next"):
                self.ready = True
            elif action in ("pass_turn", "skip_turn"):
                observation = self.observation or {}
                self.skip = {"turn": observation.get("turn"), "active": observation.get("active_seat"),
                             "hard": action == "skip_turn"}
                pending = self.pending
                if pending is not None and (pending.get("context") or {}).get("kind") == "priority":
                    passing = next((c["id"] for c in pending["candidates"] if c["kind"] == "pass"), None)
                    if passing is not None:
                        pending["how"] = "human"
                        self.answer = passing
            elif action == "cancel_skip":
                self.skip = None
            elif action == "stops":
                for key, value in (body.get("stops") or {}).items():
                    if key in self.stops:
                        self.stops[key] = bool(value)
            else:
                return "unknown action"
            self._bump()
            return None

    def wait_state(self, since: int, timeout: float = 25.0) -> dict[str, Any]:
        with self.cond:
            deadline = time.monotonic() + timeout
            while self.version <= since:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.cond.wait(remaining)
            return self.state()


def make_server(hub: Hub, host: str = "127.0.0.1", port: int = 0, token: str | None = None) -> ThreadingHTTPServer:
    token = token or secrets.token_urlsafe(16)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - quiet console
            return

        def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, value: Any, status: int = 200) -> None:
            self._send(status, json.dumps(value, separators=(",", ":")).encode("utf-8"))

        def _authorized(self) -> bool:
            query = parse_qs(urlparse(self.path).query)
            supplied = self.headers.get("X-Human-Token") or (query.get("t") or [""])[0]
            if secrets.compare_digest(supplied, token):
                return True
            self._json({"error": "bad token"}, HTTPStatus.FORBIDDEN)
            return False

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length) or b"{}")

        def do_GET(self) -> None:  # noqa: N802
            if not self._authorized():
                return
            url = urlparse(self.path)
            if url.path == "/":
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/state":
                since = int((parse_qs(url.query).get("since") or ["-1"])[0])
                self._json(hub.wait_state(since))
            else:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorized():
                return
            path = urlparse(self.path).path
            body = self._body()
            try:
                if path == "/relay/hello":
                    hub.wait_ready()
                    self._json({"ok": True})
                elif path == "/relay/game_start":
                    hub.game_start(body["request"])
                    self._json({"ok": True})
                elif path == "/relay/choose":
                    self._json({"candidate_id": hub.choose(body["request"])})
                elif path == "/relay/game_over":
                    hub.game_end(body["request"])
                    self._json({"ok": True})
                elif path == "/api/answer":
                    self._result(hub.answer_with(int(body["seq"]), int(body["candidate_id"])))
                elif path == "/api/plan":
                    self._result(hub.plan_with(int(body["seq"]), body.get("plan") or {}))
                elif path == "/api/control":
                    self._result(hub.control(str(body.get("action")), body))
                else:
                    self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except Conceded as exc:
                self._json({"error": f"conceded: {exc}"}, HTTPStatus.GONE)
            except (KeyError, TypeError, ValueError) as exc:
                self._json({"error": f"bad request: {exc}"}, HTTPStatus.BAD_REQUEST)

        def _result(self, error: str | None) -> None:
            self._json({"ok": True} if error is None else {"error": error}, 200 if error is None else 409)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.token = token  # type: ignore[attr-defined]
    return server
