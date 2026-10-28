"""The local play server behind the human seat: one page on 127.0.0.1, fed by the relay agent (``relay.py``).

The relay posts every request of the human seat here and blocks until it has an answer. The server answers what
needs no person (a lone candidate, priority passes outside the human's stops, the remaining substeps of a combat
plan) at once, so the page sees only real decisions. Everything else waits for the page. The page long-polls
``/api/state`` and posts answers, plans, stop settings and controls. Every request needs the session token: the
relay sends it as a header, the page carries it from its URL.

Each answered decision of the human seat is appended to ``<log_dir>/<game_id>.<seat>.jsonl`` (``LOG_SCHEMA``),
with how it was answered (``human``, ``plan``, ``single``, ``auto_pass``) and the wall time it took.
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

from . import text

LOG_SCHEMA = "spellbench-human-log/v1"
PAGE = Path(__file__).with_name("page.html")
PHASE_STEPS = ("upkeep", "draw", "precombat_main", "beginning_of_combat", "declare_attackers", "declare_blockers",
               "combat_damage", "end_of_combat", "postcombat_main", "end_step")
DEFAULT_STOPS = {f"{side}_{step}": False for side in ("own", "opp") for step in PHASE_STEPS}
DEFAULT_STOPS.update(own_precombat_main=True, own_postcombat_main=True, opp_stack=True, own_stack=False)
LOG_LIMIT = 400


def _ms() -> int:
    return int(time.time() * 1000)


class Hub:
    """All session state, guarded by one condition variable."""

    def __init__(self, *, log_dir: Path | None = None, games_total: int | None = None, label: str = "") -> None:
        self.cond = threading.Condition()
        self.version = 0
        self.log_dir = log_dir
        self.label = label
        self.games_total = games_total
        self.stops = dict(DEFAULT_STOPS)
        self.ready = False          # the human asked for the next game
        self.hello_waiting = False  # a relay is waiting for that
        self.game: dict[str, Any] | None = None
        self.results: list[dict[str, Any]] = []
        self.log: list[dict[str, Any]] = []
        self.observation: dict[str, Any] | None = None
        self.clock: dict[str, Any] | None = None
        self.pending: dict[str, Any] | None = None
        self.answer: int | None = None
        self.seq = 0
        self.plan: dict[str, Any] | None = None
        self.skip: dict[str, Any] | None = None  # {"turn", "active", "hard"}
        self.game_over: dict[str, Any] | None = None
        self._log_file = None
        self._seen_stack: set[str] = set()
        self._combat_logged: set[tuple[Any, str]] = set()

    # -- bookkeeping --------------------------------------------------------------------------------------------

    def _bump(self) -> None:
        self.version += 1
        self.cond.notify_all()

    def _note(self, side: str, line: str) -> None:
        turn = (self.observation or {}).get("turn")
        self.log.append({"side": side, "text": line, "turn": turn})
        del self.log[:-LOG_LIMIT]

    def _write(self, record: dict[str, Any]) -> None:
        if self._log_file is not None:
            self._log_file.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            self._log_file.flush()

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
            self.plan = self.skip = self.game_over = None
            self._seen_stack, self._combat_logged = set(), set()
            self._note("game", f"Game {self.game['number']}: you ({own.get('name')}, {seat}) vs b512 "
                               f"({opp.get('name')})")
            if self.log_dir is not None:
                self.log_dir.mkdir(parents=True, exist_ok=True)
                path = self.log_dir / f"{request.get('game_id')}.{seat}.jsonl"
                self._log_file = open(path, "w", encoding="utf-8", newline="\n")
                self._write({"schema": LOG_SCHEMA, "kind": "header", "game_id": request.get("game_id"), "seat": seat,
                             "own_deck": own, "opponent_deck": opp, "time_control": request.get("time_control"),
                             "label": self.label, "stops": self.stops})
            self._bump()

    def game_end(self, request: Mapping[str, Any]) -> None:
        with self.cond:
            terminal = dict(request.get("terminal") or {})
            me = (self.game or {}).get("seat")
            winner = terminal.get("winner")
            result = "draw" if winner is None else ("win" if winner == me else "loss")
            self.game_over = {**terminal, "result": result}
            self.results.append({"game_id": request.get("game_id"), "result": result,
                                 "reason": terminal.get("reason"), "own_deck": (self.game or {}).get("own_deck"),
                                 "seat": me})
            self._note("game", f"Game over: {'you win' if result == 'win' else 'you lose' if result == 'loss' else 'draw'}"
                               f" ({terminal.get('classification')}: {terminal.get('reason')})")
            self._write({"kind": "game_over", "terminal": terminal, "result": result})
            if self._log_file is not None:
                self._log_file.close()
                self._log_file = None
            self.pending = None
            self._bump()

    def choose(self, request: Mapping[str, Any]) -> int:
        decision = request.get("decision") or {}
        with self.cond:
            started = time.monotonic()
            self._absorb(decision, request.get("clock") or {})
            how, candidate_id = self._automatic(decision)
            if candidate_id is None:
                self.seq += 1
                self.pending = self._view(decision)
                self.answer = None
                self._bump()
                while self.answer is None or self.pending is None:
                    self.cond.wait()
                    if self.pending is None:  # the game ended underneath (host adjudication)
                        raise RuntimeError("decision withdrawn")
                candidate_id, how = self.answer, self.pending.get("how", "human")
                self.pending = None
            chosen = next(c for c in decision["candidates"] if c["candidate_id"] == candidate_id)
            semantic = chosen.get("semantic") or {}
            me = (self.game or {}).get("seat")
            if semantic.get("kind") != "pass" and how != "plan" and len(decision["candidates"]) > 1:
                self._note("you", f"You: {text.candidate(semantic, me)}")
            self._write({"kind": "decision", "step": decision.get("seat_step"), "candidate_id": candidate_id,
                         "how": how, "elapsed_ms": int((time.monotonic() - started) * 1000),
                         "candidate_count": len(decision["candidates"]), "semantic": semantic,
                         "phase_step": (decision.get("observation") or {}).get("phase_step"),
                         "turn": (decision.get("observation") or {}).get("turn")})
            self._bump()
            return candidate_id

    # -- what the human sees ------------------------------------------------------------------------------------

    def _absorb(self, decision: Mapping[str, Any], clock: Mapping[str, Any]) -> None:
        """Fold one decision's observation and public history into the log."""
        me = (self.game or {}).get("seat")
        observation = decision.get("observation") or {}
        previous = self.observation
        history = ((decision.get("extensions") or {}).get("x_public_history_v1") or {}).get("events") or []
        for side, line in text.history(history, me):
            self._note(side, line)
        for entry in observation.get("stack") or []:
            object_id = entry.get("object_id")
            if object_id in self._seen_stack:
                continue
            self._seen_stack.add(object_id)
            seat = entry.get("controller_seat")
            side = "you" if seat == me else "opp"
            if entry.get("stack_kind") == "activated_ability":
                self._note(side, f"{text.seat_name(seat, me)} activates {text.card(entry)}")
            elif entry.get("stack_kind") == "triggered_ability":
                self._note(side, f"{text.card(entry)} triggers ({'yours' if seat == me else 'opp'})")
        players = {p.get("seat"): p for p in observation.get("players") or []}
        if previous is not None:
            for p in previous.get("players") or []:
                now = players.get(p.get("seat"))
                if now is not None and now.get("life") != p.get("life"):
                    seat = p.get("seat")
                    self._note("you" if seat == me else "opp",
                               f"{'Your' if seat == me else 'Opp'} life {p.get('life')} -> {now.get('life')}")
        turn_key = (observation.get("turn"), observation.get("active_seat"))
        for seat, player in players.items():
            battlefield = player.get("battlefield") or []
            attackers = [c for c in battlefield if (c.get("permanent") or {}).get("attacking")]
            if attackers and (turn_key, "attack") not in self._combat_logged:
                self._combat_logged.add((turn_key, "attack"))
                self._note("you" if seat == me else "opp", f"{text.seat_name(seat, me)} attack"
                           f"{'' if seat == me else 's'} with " + ", ".join(text.card(c) for c in attackers))
            blockers = [c for c in battlefield if (c.get("permanent") or {}).get("blocking")]
            if blockers and (turn_key, "block") not in self._combat_logged:
                self._combat_logged.add((turn_key, "block"))
                parts = []
                for c in blockers:
                    blocked = (c.get("permanent") or {}).get("blocked_attackers") or []
                    parts.append(f"{text.card(c)} blocks " + (", ".join(text.card(a) for a in blocked) or "?"))
                self._note("you" if seat == me else "opp", f"{text.seat_name(seat, me)}: " + "; ".join(parts))
        self.observation = dict(observation)
        self.clock = {"remaining_ms": clock.get("remaining_ms"), "max_decision_ms": clock.get("max_decision_ms"),
                      "at": _ms()}

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
        return ("human", None) if self._stops_here(decision) else ("auto_pass", passing)

    def _stops_here(self, decision: Mapping[str, Any]) -> bool:
        me = (self.game or {}).get("seat")
        observation = decision.get("observation") or {}
        stack = observation.get("stack") or []
        turn_key = (observation.get("turn"), observation.get("active_seat"))
        skip = self.skip
        if skip is not None and (skip["turn"], skip["active"]) != turn_key:
            self.skip = skip = None
        if stack:
            top_mine = stack[-1].get("controller_seat") == me
            if top_mine:
                return self.stops.get("own_stack", False) and skip is None
            return self.stops.get("opp_stack", True) and not (skip is not None and skip["hard"])
        if skip is not None:
            return False
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

    def _view(self, decision: Mapping[str, Any]) -> dict[str, Any]:
        me = (self.game or {}).get("seat")
        candidates = []
        for c in decision.get("candidates") or []:
            semantic = c.get("semantic") or {}
            candidates.append({"id": c["candidate_id"], "kind": semantic.get("kind"),
                               "text": text.candidate(semantic, me), "engine_text": c.get("display_text"),
                               "refs": sorted(set(text.refs(semantic))), "semantic": semantic})
        kinds = {c["kind"] for c in candidates}
        group = decision.get("group") or {}
        screen = "generic"
        if kinds == {"declare_attack"} and group.get("substep_index") == 0:
            screen = "attack"
        elif kinds == {"declare_block"} and group.get("substep_index") == 0:
            screen = "block"
        return {"seq": self.seq, "prompt": text.prompt(decision, me), "context": decision.get("context"),
                "group": group, "candidates": candidates, "screen": screen, "received_at": _ms()}

    # -- page side ----------------------------------------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        wins = sum(r["result"] == "win" for r in self.results)
        losses = sum(r["result"] == "loss" for r in self.results)
        return {"version": self.version, "label": self.label, "games_total": self.games_total,
                "results": self.results, "wins": wins, "losses": losses, "draws": len(self.results) - wins - losses,
                "hello_waiting": self.hello_waiting, "ready": self.ready, "game": self.game,
                "observation": self.observation, "clock": self.clock, "pending": self.pending, "log": self.log,
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
            except (KeyError, TypeError, ValueError) as exc:
                self._json({"error": f"bad request: {exc}"}, HTTPStatus.BAD_REQUEST)

        def _result(self, error: str | None) -> None:
            self._json({"ok": True} if error is None else {"error": error}, 200 if error is None else 409)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.token = token  # type: ignore[attr-defined]
    return server
