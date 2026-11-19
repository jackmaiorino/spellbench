"""The local play server behind the human seat: one page on 127.0.0.1, fed by the relay agent (``relay.py``).

The relay posts every request of the human seat here and blocks until it has an answer. The server answers what
needs no person (a lone candidate, priority passes outside the human's stops, the remaining substeps of a combat
plan) at once, so the page sees only real decisions. Everything else waits for the page. The page long-polls
``/api/state`` and posts answers, plans, stop settings and controls. Every request needs the session token: the
relay sends it as a header, the page carries it from its URL.

Each answered decision of the human seat is appended to ``<log_dir>/<game_id>.<seat>.jsonl`` (``LOG_SCHEMA``),
with how it was answered (``human``, ``plan``, ``single``, ``auto_pass``, ``auto_order``) and the wall time it took.

Mana: the kernel engine declares ``engine_autopay``, and its autopay spends only lands and plain tap-for-mana
sources. A spell affordable only with mana from a costed source (an Eldrazi Spawn's sacrifice, a Treasure) is not
offered until that mana is floating, unlike rule 601.2g, which lets a player activate mana abilities mid-cast. Every
outcome stays reachable (activate, then cast), so the page labels such sources "Activate" and shows a hint instead.
"""

from __future__ import annotations

import hashlib
import json
import queue
import secrets
import threading
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from . import narrate, text
from .advisor import FLAT_EXTENSIONS, Advisor, AdvisorError

LOG_SCHEMA = "spellbench-human-log/v1"
PAGE = Path(__file__).with_name("page.html")
PHASE_STEPS = ("upkeep", "draw", "precombat_main", "beginning_of_combat", "declare_attackers", "declare_blockers",
               "combat_damage", "end_of_combat", "postcombat_main", "end_step")
DEFAULT_STOPS = {f"{side}_{step}": False for side in ("own", "opp") for step in PHASE_STEPS}
DEFAULT_STOPS.update(own_precombat_main=True, own_postcombat_main=True, opp_stack=True, own_stack=False)
LOG_LIMIT = 600
FRAME_LIMIT = 40  # stack-changing positions kept for the Manabrew host to draw (``Hub.frames``)
# Positions whose board differs, for the Manabrew host's paced drawing (``Hub.positions``): with no reader, the newest
# POSITION_LIMIT; with one, every position it has not taken yet, up to POSITION_UNSENT_LIMIT (beyond that the oldest go,
# and the reader is told how many: ``positions_gap``).
POSITION_LIMIT = 400
POSITION_UNSENT_LIMIT = 2000
READ_BACKLOG = 16  # advisor reads waiting at most; beyond that the oldest is dropped (shown as not read)
DROPPED_READ = "dropped before it was read"
# The steps of a turn in order, as the observation names them (the engine itself offers priority in only some of them).
STEP_ORDER = ("untap", "upkeep", "draw", "precombat_main", "beginning_of_combat", "declare_attackers",
              "declare_blockers", "combat_damage", "end_of_combat", "postcombat_main", "end_step", "cleanup")
# The steps in which the engine ever offers priority to a player (its decision surface passes silently in every other
# step: upkeep, draw, beginning of combat, combat damage, end of combat and the end step). A stop the person sets
# anywhere else can never come up as a window.
ENGINE_PRIORITY_STEPS = ("precombat_main", "declare_attackers", "declare_blockers", "postcombat_main")
# With full priority (``Hub(full_priority=True)``, a session started with ``--full-priority``) the engine gives the
# person's seat every priority window the rules have: every step but untap and cleanup. The bot's seat keeps the
# steps above.
FULL_PRIORITY_STEPS = tuple(step for step in STEP_ORDER if step not in ("untap", "cleanup"))
# The steps only full priority opens. The bot's model never had a priority decision in them.
NEW_PRIORITY_STEPS = frozenset(FULL_PRIORITY_STEPS) - frozenset(ENGINE_PRIORITY_STEPS)
UNTRAINED_READ = "not read: the model never had priority in this step in training"
OWN_STACK_READ = "not read: the model was never asked while its own spell or ability was on top of the stack"


def reachable_step(step: str, steps: tuple[str, ...] = ENGINE_PRIORITY_STEPS) -> str:
    """The step at which a stop aimed at ``step`` can actually be taken: the first step at or after it in which the
    engine offers the person priority (``steps``), else the last step of the turn in which it does. Without full
    priority the opponent's end step becomes their second main phase; with it every step but untap and cleanup is
    taken where it was set."""
    index = STEP_ORDER.index(step)
    return next((s for s in steps if STEP_ORDER.index(s) >= index), steps[-1])


# Steps in which declared attackers make a priority window part of an active combat (a plain pass does not skip it).
COMBAT_STEPS = frozenset({"declare_attackers", "declare_blockers", "combat_damage", "end_of_combat"})
# What the observation holds that changes with nothing the person could act on: not part of a position.
VOLATILE_OBSERVATION_KEYS = frozenset({"viewer", "priority_seat", "passed_seats"})
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


def stack_ids(observation: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(entry.get("object_id") for entry in observation.get("stack") or [])


def active_combat(observation: Mapping[str, Any]) -> bool:
    """Attackers are declared and the game is in a step of that combat (the engine's own test for a plain pass)."""
    if observation.get("phase_step") not in COMBAT_STEPS:
        return False
    return any((card.get("permanent") or {}).get("attacking")
               for player in observation.get("players") or [] for card in player.get("battlefield") or [])


def position_key(decision: Mapping[str, Any]) -> str:
    """A fingerprint of everything a priority window shows the person: the whole observation (turn, step, stack, both
    boards, hands, graveyards, mana pools, combat) except the fields that change with no game event, and the
    candidates' meanings. Read from the engine's own data, so it names no card and no ability. Equal keys mean the
    person would see the same position with the same choices."""
    observation = {k: v for k, v in (decision.get("observation") or {}).items() if k not in VOLATILE_OBSERVATION_KEYS}
    candidates = sorted(json.dumps(c.get("semantic"), sort_keys=True) for c in decision.get("candidates") or [])
    return hashlib.sha1(json.dumps([observation, candidates], sort_keys=True, default=str).encode()).hexdigest()


def display_key(observation: Mapping[str, Any]) -> str:
    """A fingerprint of what the board shows the person: turn, step, stack, and each seat's life, hand and library
    counts, graveyard and exile, and permanents (tapped, attacking, blocking, counters, damage). Two decisions with
    the same key look the same on the board. Display only (``Hub.frames``)."""
    players = []
    for player in observation.get("players") or []:
        board = [(c.get("object_id"), (c.get("permanent") or {}).get("tapped"),
                  (c.get("permanent") or {}).get("attacking"), (c.get("permanent") or {}).get("blocking"),
                  (c.get("permanent") or {}).get("counters"), (c.get("permanent") or {}).get("damage"))
                 for c in player.get("battlefield") or []]
        players.append((player.get("seat"), player.get("life"), player.get("hand_count"), player.get("library_count"),
                        [c.get("object_id") for c in player.get("graveyard") or []],
                        [c.get("object_id") for c in player.get("exile") or []], board))
    return json.dumps([observation.get("turn"), observation.get("active_seat"), observation.get("phase_step"),
                       stack_ids(observation), players], sort_keys=True, default=str)


def combat_question(decision: Mapping[str, Any], me: str | None) -> dict[str, Any] | None:
    """The question one substep of an attack or block declaration asks, in plain words, or None for any other
    decision. The engine asks about one creature at a time: an attack substep is "attack with this creature, and
    whom?", a block substep "block with this creature, and which attacker?". ``choices`` gives each candidate a short
    label ("attack", "hold back", "block Guardian of the Guildpact", "no block"); ``key`` names the declaration (its
    group, turn and active seat). Display only."""
    candidates = decision.get("candidates") or []
    kinds = {(c.get("semantic") or {}).get("kind") for c in candidates}
    if kinds == {"declare_attack"}:
        kind, role, other = "attack", "attacker", "defender"
    elif kinds == {"declare_block"}:
        kind, role, other = "block", "blocker", "attacker"
    else:
        return None
    subject = (candidates[0].get("semantic") or {}).get(role) or {}
    name = text.card(subject)
    observation = decision.get("observation") or {}
    aims = [(c.get("semantic") or {}).get(other) for c in candidates]
    idents = [aim_identity(aim) for aim in aims]
    real = sorted({ident for ident in idents if ident != "none"}, key=idents.index)
    base: dict[str, str] = {}  # identity -> its label before telling same-named ones apart
    for aim, ident in zip(aims, idents):
        if ident in base:
            continue
        if kind == "attack":
            base[ident] = "hold back" if aim is None else ("attack" if len(real) == 1 else f"attack {text.target(aim, me)}")
        else:
            base[ident] = "no block" if aim is None else f"block {text.card(aim)}"
    labels = distinct_labels(base, real, observation)
    choices = {c["candidate_id"]: labels[ident] for c, ident in zip(candidates, idents)}
    targets = {c["candidate_id"]: ident for c, ident in zip(candidates, idents)}
    if kind == "attack":
        title = f"Attack with {name}?"
    elif len(real) == 1:
        title = f"{labels[real[0]][0].upper()}{labels[real[0]][1:]} with {name}?"
    else:
        title = f"Block with {name}?"
    group = decision.get("group") or {}
    return {"kind": kind, "subject": name, "subject_id": subject.get("object_id"), "title": title,
            "index": int(group.get("substep_index") or 0), "count": int(group.get("substep_count") or 1),
            "choices": choices, "targets": targets,
            "key": [kind, group.get("group_id"), observation.get("turn"), observation.get("active_seat")]}


def aim_identity(aim: Any) -> str:
    """What a combat choice points at, by identity: ``none`` (no attack, no block), ``player:p1`` or ``object:ID``."""
    if not isinstance(aim, Mapping):
        return "none"
    if "player" in aim:
        return f"player:{aim['player']}"
    obj = aim.get("object") if isinstance(aim.get("object"), Mapping) else aim
    return f"object:{obj.get('object_id')}"


def _permanent_note(observation: Mapping[str, Any], object_id: Any) -> str:
    """A permanent's state as the board shows it ("3/3, 1 damage, 2 counters, tapped"), to tell same-named cards
    apart."""
    for player in observation.get("players") or []:
        for c in player.get("battlefield") or []:
            if c.get("object_id") != object_id:
                continue
            chars, permanent = c.get("characteristics") or {}, c.get("permanent") or {}
            parts = []
            if chars.get("power") is not None and chars.get("toughness") is not None:
                parts.append(f"{chars['power']}/{chars['toughness']}")
            if permanent.get("damage"):
                parts.append(f"{permanent['damage']} damage")
            counters = sum(v for v in (permanent.get("counters") or {}).values() if isinstance(v, int))
            if counters:
                parts.append(f"{counters} counter{'s' if counters != 1 else ''}")
            if permanent.get("tapped"):
                parts.append("tapped")
            return ", ".join(parts)
    return ""


def distinct_labels(base: Mapping[str, str], order: list[str], observation: Mapping[str, Any]) -> dict[str, str]:
    """Labels that tell choices of the same name apart: a card's state on the board when that differs ("block Ogre
    (3/3, 1 damage)"), else its place in the engine's order ("block Ogre #2"). Choices pointing at the same thing keep
    one label."""
    labels = dict(base)
    by_label: dict[str, list[str]] = {}
    for ident in order:
        by_label.setdefault(base[ident], []).append(ident)
    for label, idents in by_label.items():
        if len(idents) < 2:
            continue
        notes = [_permanent_note(observation, ident.split(":", 1)[1]) if ident.startswith("object:") else ""
                 for ident in idents]
        if all(notes) and len(set(notes)) == len(notes):
            for ident, note in zip(idents, notes):
                labels[ident] = f"{label} ({note})"
        else:
            for n, ident in enumerate(idents, 1):
                labels[ident] = f"{label} #{n}"
    return labels


class Conceded(RuntimeError):
    """The person gave up the game: every later decision of it is refused so the arena ends it at once."""


# Said first in every game of a session with an advisor (its identity is in each game's record header).
ADVISED_NOTE = ("Advisor on: {label} shows how it weighs your choices. This is advised play, not a measure of your "
                "unassisted play.")
# Said at the put-back prompt (in the log, and in the description of the plain selection used when the Manabrew prompt
# cannot be built): the engine puts the cards back right after the new seven are drawn, before the next Keep or
# Mulligan choice (a real table asks Keep or Mulligan first). It is the order the bots trained on.
FULL_PRIORITY_NOTE = ("Full priority: you get priority in every step, and while your own spell is on the stack. The bot "
                      "plays as it trained: it does NOT respond to anything you do in upkeep, draw, beginning of "
                      "combat, combat damage, end of combat or the end step (so a spell you cast there cannot be "
                      "countered). In the main phases and the declare steps it responds as always.")
GRAVEYARD_ORDER_NOTE = ("Graveyard order: cards that go to your graveyard together (a mill, a discard of several "
                        "cards, the rest of a look) are ordered for you, by name, and so are the cards one look puts "
                        "into your hand. No card in these decks reads graveyard order.")
# Where the order of the cards one look (an arrangement) sends there is read by nothing: the session answers it.
UNORDERED_DESTINATIONS = frozenset({"graveyard", "hand"})
PUT_BACK_NOTE = ("Put cards back now: this engine bottoms them right after the new seven are drawn, then asks Keep or "
                 "Mulligan on the smaller hand (real tables ask Keep or Mulligan first, then bottom).")


class Hub:
    """All session state, guarded by one condition variable. A decision is answered ``human`` (the person chose),
    ``plan`` (a step of a combat plan the person made), ``single`` (one candidate) or ``auto_pass`` (the session
    declined for the person: a priority pass at which only passing or mana was possible or no stop applies, or the
    no-attackers answer to a declaration that a hold they set runs past) or ``auto_order`` (with
    ``auto_graveyard_order``: the order of cards that one look puts into the person's graveyard or hand, where no
    order exists that anything reads; the first card listed is taken)."""

    def __init__(self, *, log_dir: Path | None = None, games_total: int | None = None, label: str = "",
                 opponent: str = "the bot", record_root: Path | None = None, real_action_stops: bool = False,
                 banner: str | None = None, advisor: Advisor | None = None, full_priority: bool = False,
                 client_autopass: bool = False, auto_graveyard_order: bool = False) -> None:
        self.cond = threading.Condition()
        # True: the engine orders cards going to the person's own graveyard together without asking (the session
        # told it the person's seat), and this class answers the order of the cards one look puts into their
        # graveyard or hand (``_settled_order``).
        self.auto_graveyard_order = auto_graveyard_order
        # The arrangement under way: its group id and where the person sent each card of it (``_conclude``).
        self._arranged_group: Any = None
        self._arranged: dict[Any, str] = {}
        # True: the engine gives the person's seat every priority window (upkeep, draw, beginning of combat, combat
        # damage, end of combat, the end step, and their own spell on the stack), so a stop set in any of those steps
        # is taken there. The bot's seat is unchanged. False: the engine's trained windows only.
        self.full_priority = full_priority
        self.priority_steps = FULL_PRIORITY_STEPS if full_priority else ENGINE_PRIORITY_STEPS
        # True (with ``real_action_stops``): a window at which the person has mana abilities and nothing else is sent
        # to the client instead of being passed here, under the same hold, stack and combat rules as a window with a
        # real action; the client passes it after its AUTOPASS countdown unless its Full control is on. A window with
        # nothing but passing is always passed here.
        self.client_autopass = client_autopass and real_action_stops
        # A second scorer that reads the person's own decisions (``advisor.py``). ``advice`` is its read of the
        # decision in front of the person, then of the one they answered last (with ``chosen``), until the next.
        self.advisor = advisor
        self.advisor_identity = advisor.identity() if advisor is not None else None
        self.advice: dict[str, Any] | None = None
        # The reads of the attack or block declaration under way (``_declaration_item``): one item per creature the
        # engine asked about, with the person's answer. Shown with every read until that combat is over. Display
        # only: the decision records are written as before.
        self.declaration: dict[str, Any] | None = None
        # True: the person gets every priority at which they have a legal action besides passing and mana abilities,
        # in any step of either turn and on any stack (the Manabrew path, which has no panel for stops). False: only
        # the stops of ``self.stops`` (the play page's S panel).
        self.real_action_stops = real_action_stops
        self.version = 0
        self.log_dir = log_dir
        self.label = label
        self.banner = banner  # a line shown first in every game's log and written in each game's record header
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
        self.exhaust_ids: frozenset[Any] = frozenset()  # the stack objects there were when it was asked for
        # The client's pass-until (Manabrew path): {"seat", "step", "through_combat", "origin", "origin_index",
        # "turn"}; see ``pass_with``. It stays until it is reached, lost or an action of the person's clears it.
        self.hold: dict[str, Any] | None = None
        self._stop_moved_noted: tuple[Any, ...] | None = None  # the stop ``_note_stop_moved`` last explained
        self.auto_attack_group: Any = None  # the attack declaration answered with no attackers because of a hold
        self.forced_attack_group: Any = None  # an attack declaration in which a creature must attack
        self.passed_at: tuple[Any, Any] | None = None  # (turn, step) the positions in ``passed_keys`` belong to
        self.passed_keys: set[str] = set()  # positions the person already passed at, in that step
        self.pending_key: str | None = None
        self.last_stack: tuple[Any, ...] = ()
        self.frames: list[dict[str, Any]] = []  # observations of decisions at which the stack changed (newest last)
        self.frames_total = 0
        # observations of decisions at which what the board shows changed (newest last), each with ``_frame`` (the
        # log lines there were by then), for the paced drawing; ``last_shown`` is the newest one's ``display_key``
        self.positions: list[dict[str, Any]] = []
        self.positions_total = 0
        self.positions_reader = False  # a host draws them (``wait_state`` with ``positions_from``) ...
        self.positions_taken = 0       # ... and has taken those before this count (they can go)
        self.last_shown: str | None = None
        # The advisor's reads run in a thread of their own, off this lock (``_queue_read``): an answer the person gave
        # is never held back by a read, and the person's concession or departure never waits for one.
        self._jobs: "queue.Queue[tuple[Any, ...]] | None" = None
        self._scorer = threading.Lock()  # one read at a time on the scorer's pipe
        self._reader: threading.Thread | None = None
        self._reads_open = 0
        self.game_over: dict[str, Any] | None = None
        self.conceded: str | None = None  # the game id the person gave up (or lost the connection to), if any
        self._announcements: list[str] = []  # lines for the log of the game that starts next (``announce``)
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
        """A game-level line for the log, kept until the next game starts (it is shown first in that game; several
        are shown in the order given)."""
        with self.cond:
            self._announcements.append(text)
            self._bump()

    def say(self, text: str) -> None:
        """A game-level line for the log now (a notice of the session's, such as the person's clock running down)."""
        with self.cond:
            self._note("game", text)
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
            self.advice = self.declaration = None
            if self.banner:
                self._note("game", self.banner)
            if self.advisor_identity is not None:
                self._note("game", ADVISED_NOTE.format(label=self.advisor_identity["label"]))
            if self.full_priority:
                self._note("game", FULL_PRIORITY_NOTE)
            if self.auto_graveyard_order:
                self._note("game", GRAVEYARD_ORDER_NOTE)
            self.plan = self.skip = self.game_over = None
            self._arranged_group, self._arranged = None, {}
            self.exhaust_stack, self.exhaust_ids = False, frozenset()
            self.hold = self.auto_attack_group = self.forced_attack_group = self.passed_at = self.pending_key = None
            self.passed_keys = set()
            self.last_stack, self.frames, self.frames_total = (), [], 0
            self.last_shown, self.positions, self.positions_total, self.positions_taken = None, [], 0, 0
            self._drop_reads()  # reads queued for the game before are of no use now
            self._combat_logged = set()
            self._opening = {"mine": 0, "opp": 0, "done": False}
            self.narrator = narrate.Narrator(seat) if seat else None
            self._tail, self._step = None, None
            self._note("game", f"Game {self.game['number']}: you ({own.get('name')}, {seat}) vs {self.opponent} "
                               f"({opp.get('name')})")
            for line in self._announcements:
                self._note("game", line)
            self._announcements = []
            if self.log_dir is not None:
                self.log_dir.mkdir(parents=True, exist_ok=True)
                path = self.log_dir / f"{request.get('game_id')}.{seat}.jsonl"
                self._log_file = open(path, "w", encoding="utf-8", newline="\n")
                self._write({"schema": LOG_SCHEMA, "kind": "header", "game_id": request.get("game_id"), "seat": seat,
                             "bot_name": "Human", "own_deck": own, "opponent_deck": opp, "time_control": request.get("time_control"),
                             "label": self.label, "banner": self.banner, "stops": self.stops,
                             "advisor": self.advisor_identity,
                             **({"full_priority": True} if self.full_priority else {}),
                             **({"auto_graveyard_order": True} if self.auto_graveyard_order else {})})
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
            self._drop_reads()
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
        (``connection_lost``) or the table cannot go on (``relay_lost``, ``host_fault``). The page and the Manabrew
        client see the game over at once; a decision the engine
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
        # The model input (kept by the relay only for a session with an advisor) is for the advisor alone: it is
        # taken out here, so the person's view, the log and the narrator never hold it.
        model_input = None
        extensions = decision.get("extensions")
        if isinstance(extensions, Mapping) and any(name in extensions for name in FLAT_EXTENSIONS):
            model_input = next(extensions[name] for name in FLAT_EXTENSIONS if name in extensions)
            decision = {**decision, "extensions": {name: value for name, value in extensions.items()
                                                   if name not in FLAT_EXTENSIONS}}
        with self.cond:
            started = time.monotonic()
            how, candidate_id = self._begin(decision, request.get("clock") or {}, model_input=model_input,
                                            game_id=request.get("game_id"))
            chosen_text = None
            advice = None
            if candidate_id is None:
                seq = self.pending["seq"]
                while self.answer is None or self.pending is None:
                    self.cond.wait()
                    if self.pending is None:  # the game ended underneath (host adjudication, or the person's concession)
                        if self.conceded is not None and self.game is not None and self.game.get("game_id") == self.conceded:
                            raise Conceded("conceded")
                        raise RuntimeError("decision withdrawn")
                candidate_id, how, chosen_text = self._take_answer()
                # the read of this decision as it stands now (its scores may still be on their way: then the record
                # says so, and the panel's list fills in when they come)
                advice = self.advice if self.advice is not None and self.advice.get("seq") == seq else None
                if advice is not None:
                    self.advice = advice = {**advice, "chosen": candidate_id}
                    if advice.get("question") is not None:
                        self._declaration_item(advice["question"], candidate_id, how, self._read_of(advice))
            return self._conclude(decision, how, candidate_id, chosen_text, started, advice)

    def _begin(self, decision: Mapping[str, Any], clock: Mapping[str, Any], *, model_input: Any = None,
               game_id: Any = None) -> tuple[str, int | None]:
        """Take in a decision. Returns how it is answered without the person and the candidate, or ``(how, None)``
        with the decision pending for the person (``self.pending``; the answer comes with ``answer_with``,
        ``pass_with`` or ``plan_with``)."""
        if self.conceded is not None and self.game is not None and self.game.get("game_id") == self.conceded:
            raise Conceded(self.game_over.get("reason") if self.game_over else "conceded")
        self._absorb(decision, clock)
        observation = decision.get("observation") or {}
        stack = stack_ids(observation)
        if stack != self.last_stack:  # a position the person may need to see before the stack moves on
            self.last_stack = stack
            self.frames.append(dict(observation))
            self.frames_total += 1
            del self.frames[:-FRAME_LIMIT]
        shown = display_key(observation)
        if shown != self.last_shown:  # any change the board shows: the paced drawing draws each one
            # ``_frame``: how many log lines there were by then, so the host shows each position with its own lines
            self.positions.append({**observation, "_frame": {"log_total": self.log_total}})
            self.positions_total += 1
            self._trim_positions()
            self.last_shown = shown
        self._expire_declaration(observation)
        if not stack or not frozenset(stack) <= self.exhaust_ids:
            # the stack the person asked to pass through is empty, or something that was not on it appeared: stop
            self.exhaust_stack, self.exhaust_ids = False, frozenset()
        how, candidate_id = self._automatic(decision)
        if candidate_id is not None and how in ("plan", "single") and self.advisor_identity is not None:
            # A later creature of a declaration the person made on one screen (or one that has a single choice): the
            # engine asks about it now, with the earlier answers in place. The answer goes back at once; the read
            # follows in the advisor's own thread and fills in its line of the list.
            question = combat_question(decision, (self.game or {}).get("seat"))
            if question is not None:
                if how == "single":
                    self._declaration_item(question, candidate_id, how, {"only": True})
                else:
                    self._declaration_item(question, candidate_id, how, None)
                    game = (self.game or {}).get("game_id")
                    key = list(question["key"])
                    self._queue_read(decision, model_input, game_id, lambda read: self._fill_item(game, question, read),
                                     lambda: (self._reading_alive(game) and self.declaration is not None
                                              and self.declaration["key"] == key),
                                     lambda: self._mark_dropped(game, None, question))
        if candidate_id is None:
            self._priority_note(decision)
            self.seq += 1
            self.pending = self._view(decision)
            if self.pending.get("screen") == "bottom":
                self._note("game", PUT_BACK_NOTE)
            self.pending_key = position_key(decision)
            self.answer = None
            self.advice = self._advise(decision, model_input, game_id)
            self._bump()
        return how, candidate_id

    def _advise(self, decision: Mapping[str, Any], model_input: Any, game_id: Any) -> dict[str, Any] | None:
        """The advisor's read of the decision that is now pending. It starts as ``reading`` and is filled in by the
        advisor's own thread (``_apply_read``) with the texts the person sees for its choices, most likely first. A
        decision it cannot read says why; a scorer that fails is dropped for the rest of the session, with a log line,
        and the game goes on."""
        if self.advisor_identity is None:
            return None
        advice: dict[str, Any] = {"seq": self.seq, "model": self.advisor_identity["label"],
                                  "prompt": self.pending["prompt"]}
        question = combat_question(decision, (self.game or {}).get("seat"))
        if question is not None:
            # An attack or block substep: the read is about one creature, named in ``question``; ``screen`` says
            # whether the person declares the whole attack or block on one screen (the Manabrew client's combat
            # prompts are built from it), so the panel can say that the other creatures' reads follow.
            advice["question"] = {**question, "screen": self.pending.get("screen")}
            if self.declaration is not None and self.declaration["key"] != question["key"]:
                self.declaration = None  # another declaration: its own list starts with its first answer
        if self.declaration is not None and self.declaration["items"]:
            advice["declaration"] = self._declaration_view()
        if self.advisor is None:
            return {**advice, "unavailable": "the advisor stopped earlier in this session"}
        if ((decision.get("context") or {}).get("kind") == "priority"
                and (decision.get("observation") or {}).get("phase_step") in NEW_PRIORITY_STEPS):
            # A window only full priority opens: the model's numbers here would come from an input it never trained
            # on, so none are shown.
            return {**advice, "unavailable": UNTRAINED_READ}
        top = text.stack_top((decision.get("observation") or {}).get("stack"))
        if (self.full_priority and (decision.get("context") or {}).get("kind") == "priority" and top is not None
                and top.get("controller_seat") == (self.game or {}).get("seat")):
            # The person's own object on top of the stack: with full priority this is nearly always a window the bot's
            # surface passes (holding priority). The few it does offer are not told apart here; none is read.
            return {**advice, "unavailable": OWN_STACK_READ}
        seq, game = self.seq, (self.game or {}).get("game_id")
        texts = {c["id"]: c["text"] for c in self.pending["candidates"]}
        question = advice.get("question")
        key = list(question["key"]) if question is not None else None
        # wanted while its read is the one shown, or while its combat's list (where its line is) is shown
        self._queue_read(decision, model_input, game_id, lambda read: self._apply_read(game, seq, texts, question, read),
                         lambda: self._reading_alive(game) and ((self.advice or {}).get("seq") == seq or (
                             key is not None and self.declaration is not None and self.declaration["key"] == key)),
                         lambda: self._mark_dropped(game, seq, question))
        if self.declaration is not None and self.declaration["items"]:  # as it is after the queue was pruned
            advice["declaration"] = self._declaration_view()
        return {**advice, "reading": True}

    def _apply_read(self, game: Any, seq: int, texts: Mapping[int, str], question: Mapping[str, Any] | None,
                    read: Mapping[str, Any]) -> None:
        """Put a pending decision's read in place (under the lock), if its game is still on. The advice it belongs
        to may have been answered meanwhile (the read is then shown with the answer); a read of an older decision is
        dropped, except that a combat question's line of the list is filled in."""
        if (self.game or {}).get("game_id") != game or self.game_over is not None:
            return
        advice = self.advice
        if advice is not None and advice.get("seq") == seq:
            body = {k: v for k, v in advice.items() if k != "reading"}
            if "unavailable" in read:
                body["unavailable"] = read["unavailable"]
            else:
                body.update(self._rows(read, texts, question), value=read["value"], win=read["win"],
                            scores=[[row["id"], round(row["p"], 6)] for row in read["rows"]])
            # An answer already accepted for this decision (taken by ``choose`` or not yet) was given without this
            # read: the record must not say it was shown. Decided here, under the same lock as the answer.
            if advice.get("chosen") is not None or (self.answer is not None and (self.pending or {}).get("seq") == seq):
                body["late"] = True
            body["rev"] = int(advice.get("rev") or 0) + 1
            self.advice = body
        if question is not None:  # its line of the list, if the person has answered it already
            self._fill_item(game, question, read)

    @staticmethod
    def _rows(read: Mapping[str, Any], texts: Mapping[int, str], question: Mapping[str, Any] | None) -> dict[str, Any]:
        """The panel's rows of a read. Choices the person reads as the same line (two copies of a land) are one row
        with their shares added: the model splits its weight between them, and the person cannot tell them apart. A
        combat question's choices are told apart by what they point at (``question["targets"]``), never by name
        alone, and carry their short label (``short``)."""
        merged: dict[str, dict[str, Any]] = {}
        for row in read["rows"]:
            key = question["targets"].get(row["id"], f"id:{row['id']}") if question else texts.get(row["id"], "?")
            line = merged.setdefault(key, {"ids": [], "p": 0.0, "text": texts.get(row["id"], "?")})
            line["ids"].append(row["id"])
            line["p"] += row["p"]
        rows = []
        for key, line in merged.items():
            row = {"ids": line["ids"], "text": line["text"], "p": round(line["p"], 4)}
            if question is not None:
                row["short"] = question["choices"].get(line["ids"][0], line["text"])
                row["target"] = key
            rows.append(row)
        rows.sort(key=lambda row: -row["p"])  # stable: ties stay in the model's row order
        return {"rows": rows}

    @staticmethod
    def _read_of(advice: Mapping[str, Any]) -> dict[str, Any] | None:
        """A pending advice's read by candidate, for the declaration's list; None while it is still being read."""
        if "unavailable" in advice:
            return {"unavailable": advice["unavailable"]}
        if "scores" in advice:
            return {"rows": [{"id": cid, "p": p} for cid, p in advice["scores"]]}
        return None

    # -- the advisor's thread ------------------------------------------------------------------------------------

    def _queue_read(self, decision: Mapping[str, Any], model_input: Any, game_id: Any, apply, alive, dropped) -> None:
        """Read one decision in the advisor's own thread, never under this lock: ``apply(read)`` runs under the lock
        once the read is back and checks that what it belongs to is still current. ``alive()`` (under the lock) says
        whether the read is still wanted: a job whose game or declaration has passed is skipped without asking the
        scorer, and ``dropped()`` then shows it as not read. Reads are done in order. The queue never blocks: jobs no
        longer wanted are pruned here, at most READ_BACKLOG wait (the oldest go), and it is emptied when a game starts
        or ends (``_drop_reads``)."""
        if self._jobs is None:
            self._jobs = queue.Queue()
            self._reader = threading.Thread(target=self._read_loop, daemon=True, name="advisor-reads")
            self._reader.start()
        waiting = self._take_jobs()
        for job in waiting:
            if job is not None and not job[4]():
                self._forget(job)
        waiting = [job for job in waiting if job is None or job[4]()]
        waiting.append((decision, model_input, str(game_id or (self.game or {}).get("game_id") or "game"), apply, alive,
                        dropped))
        self._reads_open += 1
        while sum(job is not None for job in waiting) > READ_BACKLOG:
            oldest = next(index for index, job in enumerate(waiting) if job is not None)
            self._forget(waiting.pop(oldest))
        for job in waiting:
            self._jobs.put(job)

    def _take_jobs(self) -> list[Any]:
        assert self._jobs is not None
        taken = []
        while True:
            try:
                taken.append(self._jobs.get_nowait())
            except queue.Empty:
                return taken

    def _forget(self, job: tuple[Any, ...]) -> None:
        """A queued read that will not be made: it no longer counts as open, and its row says it was not read."""
        self._reads_open -= 1
        try:
            job[5]()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        self.cond.notify_all()

    def _mark_dropped(self, game: Any, seq: int | None, question: Mapping[str, Any] | None) -> None:
        """A read that was dropped: the advice still waiting for it, and its line of the list, stop saying reading."""
        if (self.game or {}).get("game_id") != game:
            return
        advice = self.advice
        if seq is not None and advice is not None and advice.get("seq") == seq and advice.get("reading"):
            body = {k: v for k, v in advice.items() if k != "reading"}
            body["unavailable"] = DROPPED_READ
            body["rev"] = int(advice.get("rev") or 0) + 1
            self.advice = body
        declaration = self.declaration
        if question is not None and declaration is not None and declaration["key"] == list(question["key"]):
            for item in declaration["items"]:
                if item["index"] == question["index"] and item.get("reading"):
                    self._fill(item, question, {"unavailable": DROPPED_READ})
                    self._publish_declaration()

    def _reading_alive(self, game: Any) -> bool:
        return (self.game or {}).get("game_id") == game and self.game_over is None

    def _drop_reads(self) -> None:
        """Empty the queue of reads (a game started or ended: none of them is wanted any more). Under the lock."""
        if self._jobs is None:
            return
        for job in self._take_jobs():
            if job is None:  # the stop sentinel stays
                self._jobs.put(None)
            else:
                self._forget(job)
        self.cond.notify_all()

    def close_advisor(self) -> None:
        """At the session's end, in bounded time whatever the scorer does: drop the queued reads, stop the scorer
        (``Advisor.close`` ends the process first, which also frees a read stuck writing to it), then let the
        advisor's thread go."""
        with self.cond:
            self._drop_reads()
            advisor, self.advisor = self.advisor, None
            jobs, reader = self._jobs, self._reader
        if jobs is not None:
            jobs.put(None)
        if advisor is not None:
            advisor.close()
        if reader is not None:
            reader.join(timeout=5)

    def _read_loop(self) -> None:
        assert self._jobs is not None
        while True:
            job = self._jobs.get()
            if job is None:
                return  # close_advisor
            decision, model_input, game_id, apply, alive, _ = job
            with self.cond:
                wanted = alive()
                advisor = self.advisor
                if not wanted:  # its game or declaration has passed: the scorer is not asked
                    self._forget(job)
                    continue
            if advisor is None:
                read: dict[str, Any] = {"unavailable": "the advisor stopped earlier in this session"}
            else:
                try:
                    with self._scorer:
                        read = advisor.read(game_id, decision, model_input)
                except AdvisorError as exc:
                    read = {"unavailable": str(exc)}
                    with self.cond:
                        if self.advisor is advisor:
                            self._note("game", f"The advisor stopped: {exc}. The game goes on without it.")
                            self.advisor = None
                            threading.Thread(target=advisor.close, daemon=True).start()
                except Exception as exc:  # noqa: BLE001 - a read never takes the session down
                    traceback.print_exc()
                    read = {"unavailable": f"the read failed ({type(exc).__name__})"}
            with self.cond:
                try:
                    if alive():
                        apply(read)
                    else:  # it passed while being read: its row says it was not read
                        job[5]()
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
                self._reads_open -= 1
                self._bump()

    def wait_reads(self, timeout: float = 30.0) -> bool:
        """Wait until every queued read is back (tests and tools). Returns False on timeout."""
        deadline = time.monotonic() + timeout
        with self.cond:
            while self._reads_open:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self.cond.wait(left)
        return True

    # -- the declaration's list ----------------------------------------------------------------------------------

    def _declaration_item(self, question: Mapping[str, Any], candidate_id: int, how: str,
                          read: Mapping[str, Any] | None) -> None:
        """Add one answered creature question to the declaration under way (a new declaration starts the list
        again) and show the list with the current read. ``read``: its read by candidate, ``{"only": True}`` for a
        single legal choice, ``unavailable``, or None while it is still being read (``_fill_item`` fills it in)."""
        key = list(question["key"])
        if self.declaration is None or self.declaration["key"] != key:
            self.declaration = {"key": key, "kind": question["kind"], "count": question["count"], "items": [],
                                "turn": key[2:]}
        item: dict[str, Any] = {"index": question["index"], "subject": question["subject"],
                                "subject_id": question["subject_id"], "chosen": question["choices"].get(candidate_id, "?"),
                                "chosen_target": question["targets"].get(candidate_id), "how": how}
        if read is None:
            item["reading"] = True
        else:
            self._fill(item, question, read)
        self.declaration["items"].append(item)
        self._publish_declaration()

    def _fill_item(self, game: Any, question: Mapping[str, Any], read: Mapping[str, Any]) -> None:
        """A read that came back for a line of the list: filled in if its game and declaration are still current."""
        declaration = self.declaration
        if ((self.game or {}).get("game_id") != game or self.game_over is not None or declaration is None
                or declaration["key"] != list(question["key"])):
            return
        for item in declaration["items"]:
            if item["index"] == question["index"] and item.get("reading"):
                self._fill(item, question, read)
                self._publish_declaration()
                return

    @staticmethod
    def _fill(item: dict[str, Any], question: Mapping[str, Any], read: Mapping[str, Any]) -> None:
        """One line's read: the shares of what each choice points at (by identity, so two attackers of one name stay
        two rows), the share of the person's choice and, for an attack, the share of attacking at all."""
        item.pop("reading", None)
        if "unavailable" in read:
            item["unavailable"] = read["unavailable"]
            return
        if read.get("only"):
            item["only"] = True  # one legal choice: nothing to weigh
            return
        shares: dict[str, float] = {}
        labels: dict[str, str] = {}
        for row in read.get("rows") or []:
            target = question["targets"].get(row["id"], f"id:{row['id']}")
            shares[target] = shares.get(target, 0.0) + row["p"]
            labels.setdefault(target, question["choices"].get(row["id"], "?"))
        rows = sorted(shares.items(), key=lambda pair: -pair[1])
        item["rows"] = [{"text": labels[target], "target": target, "p": round(p, 4)} for target, p in rows]
        item["p_chosen"] = round(shares.get(item["chosen_target"], 0.0), 4)
        if question["kind"] == "attack":
            item["p_attack"] = round(sum(p for target, p in rows if target != "none"), 4)

    def _declaration_view(self) -> dict[str, Any]:
        declaration = self.declaration or {}
        return {"kind": declaration.get("kind"), "count": declaration.get("count"),
                "items": [dict(item) for item in declaration.get("items") or []]}

    def _publish_declaration(self) -> None:
        """Show the declaration's list as it is now with the current read (or take it away once it has ended)."""
        if self.advice is None:
            return
        advice = {k: v for k, v in self.advice.items() if k != "declaration"}
        if self.declaration is not None and self.declaration["items"]:
            advice["declaration"] = self._declaration_view()
        elif "declaration" not in self.advice:
            return
        advice["rev"] = int(self.advice.get("rev") or 0) + 1
        self.advice = advice

    def _expire_declaration(self, observation: Mapping[str, Any]) -> None:
        """End the declaration's list once its combat is over: another turn, or a step outside combat. Looked at for
        every decision of the person's seat, those answered without them too."""
        declaration = self.declaration
        if declaration is None:
            return
        here = [observation.get("turn"), observation.get("active_seat")]
        if here != declaration["turn"] or observation.get("phase_step") not in COMBAT_STEPS:
            self.declaration = None
            self._publish_declaration()

    def _take_answer(self) -> tuple[int, str, str | None]:
        """The person's answer to the pending decision, which is then no longer pending."""
        pending = self.pending
        candidate_id, how = self.answer, pending.get("how", "human")
        chosen_text = next((c["text"] for c in pending["candidates"] if c["id"] == candidate_id), None)
        self.pending = None
        return candidate_id, how, chosen_text

    def _conclude(self, decision: Mapping[str, Any], how: str, candidate_id: int, chosen_text: str | None,
                  started: float, advice: Mapping[str, Any] | None = None) -> int:
        chosen = next(c for c in decision["candidates"] if c["candidate_id"] == candidate_id)
        semantic = chosen.get("semantic") or {}
        me = (self.game or {}).get("seat")
        if semantic.get("kind") == "arrange_card":
            # where this card of the look goes: the order within a destination nothing reads is settled later
            group = (decision.get("group") or {}).get("group_id")
            if self._arranged_group != group:
                self._arranged_group, self._arranged = group, {}
            self._arranged[(semantic.get("card") or {}).get("object_id")] = str(semantic.get("destination"))
        if (semantic.get("kind") not in NARRATED_KINDS and how not in ("plan", "auto_order")
                and len(decision["candidates"]) > 1):
            label = chosen_text or text.candidate(semantic, me)
            self._note("you", f"You choose: {label}", depth=1, facts=[("choice", me)])
        record = {"kind": "decision", "step": decision.get("seat_step"), "candidate_id": candidate_id,
                  "how": how, "elapsed_ms": int((time.monotonic() - started) * 1000),
                  "candidate_count": len(decision["candidates"]), "semantic": semantic,
                  "phase_step": (decision.get("observation") or {}).get("phase_step"),
                  "turn": (decision.get("observation") or {}).get("turn")}
        if advice is not None:  # what the advisor showed the person at this decision
            if "scores" in advice and not advice.get("late"):
                record["advisor"] = {"probabilities": advice["scores"], "value": advice["value"]}
            else:  # no read, or (reads take milliseconds) one that was not back when the person answered
                record["advisor"] = {"unavailable": advice.get("unavailable") or "not read before the answer"}
        self._write(record)
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
        self._opening_lines(self.observation)
        self.clock = {"remaining_ms": clock.get("remaining_ms"), "max_decision_ms": clock.get("max_decision_ms"),
                      "at": _ms()}

    def _opening_lines(self, observation: Mapping[str, Any]) -> None:
        """The London opening as a spectator at the table sees it: how many mulligans each seat has taken and, once
        the game begins, that the other seat kept its hand. Public counts only: never a card of the other seat."""
        me = (self.game or {}).get("seat")
        opening = getattr(self, "_opening", None)
        players = {p.get("seat"): p for p in observation.get("players") or []}
        if opening is None or me not in players or opening["done"]:
            return
        mine, other = players[me], players["p1" if me == "p0" else "p0"]
        for key, player, who, name in (("mine", mine, "you", "You take"), ("opp", other, "opp", "Opponent takes")):
            taken = player.get("mulligans_taken") or 0
            if taken > opening[key]:
                size = 7 - taken
                more = taken - opening[key]
                what = "a mulligan" if more == 1 else f"{more} more mulligans"
                self._note(who, f"{name} {what} (now {taken} taken: draws seven, puts {taken} on the bottom, "
                                f"{size} cards if kept)", header=False)
                opening[key] = taken
        if (observation.get("turn") or 0) >= 1:
            opening["done"] = True
            self._note("opp", f"Opponent keeps {7 - (other.get('mulligans_taken') or 0)} cards")
            self._note("you", f"You keep {7 - (mine.get('mulligans_taken') or 0)} cards")

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
        if self.hold is not None and (decision.get("context") or {}).get("kind") == "priority":
            # Every priority the engine gives the person moves the hold along (its turn is found, it is reached or
            # lost), also one answered below without asking: a window with nothing but passing, or with only mana.
            # Otherwise a hold whose step came up with nothing to do there would stay ahead for another turn.
            self._hold_unreached(decision.get("observation") or {})
        if len(candidates) == 1:
            semantic = candidates[0].get("semantic") or {}
            if semantic.get("kind") == "declare_attack" and semantic.get("defender") is not None:
                # a creature that must attack: the person is asked about the rest of this declaration
                self.forced_attack_group = self._attack_group(decision)
            return "single", candidates[0]["candidate_id"]
        planned = self._from_plan(decision)
        if planned is not None:
            return "plan", planned
        settled = self._settled_order(decision)
        if settled is not None:
            return "auto_order", settled
        declined = self._decline_attack(decision)
        if declined is not None:
            return "auto_pass", declined  # a hold the person set runs past this turn's attack: no attackers
        context = decision.get("context") or {}
        if context.get("kind") != "priority":
            return "human", None
        kinds = {c["semantic"].get("kind") for c in candidates}
        passing = next((c["candidate_id"] for c in candidates if c["semantic"].get("kind") == "pass"), None)
        if passing is None:
            return "human", None
        if kinds <= {"pass", "activate_mana_ability"}:
            if self.client_autopass and "activate_mana_ability" in kinds and self._stops_here(decision, True):
                return "human", None  # the client's own countdown, or its Full control, answers this one
            return "auto_pass", passing  # mana is paid automatically; floating it alone does nothing
        real = self.real_action_stops and bool(real_actions(candidates))
        return ("human", None) if self._stops_here(decision, real) else ("auto_pass", passing)

    def _settled_order(self, decision: Mapping[str, Any]) -> int | None:
        """The first candidate of an ordering the person is not asked (``auto_graveyard_order``), or ``None``. Only
        the ordering step of an arrangement (a look that sends cards to several places) whose candidates all go to
        the person's graveyard or hand: the destinations are those the person gave the cards earlier in the same
        group, so a card with no recorded destination, or one going to the top or bottom of a library, is asked."""
        if not self.auto_graveyard_order:
            return None
        candidates = decision.get("candidates") or []
        semantics = [c.get("semantic") or {} for c in candidates]
        if not semantics or any(s.get("kind") != "order_pick" or s.get("purpose") != "arrangement" for s in semantics):
            return None
        if (decision.get("group") or {}).get("group_id") != self._arranged_group:
            return None
        destinations = {self._arranged.get(((s.get("item") or {}).get("object") or {}).get("object_id"))
                        for s in semantics}
        if not destinations <= UNORDERED_DESTINATIONS:
            return None
        return candidates[0]["candidate_id"]

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
        # The hold is looked at in every window, so one that is reached or lost is dropped where that happens.
        held = real and self._hold_unreached(observation)
        if stack:
            if self.exhaust_stack:
                return False  # still the stack "end turn" was pressed on (``_begin`` ends this at anything new)
            top_mine = text.stack_top(stack).get("controller_seat") == me
            if top_mine:
                asked = (self.stops.get("own_stack", False) or real) and skip is None
            else:
                asked = (self.stops.get("opp_stack", True) or real) and not (skip is not None and skip["hard"])
            return asked and not (real and self._passed_here(decision))
        if skip is not None:
            return False
        if real:
            if held and not (not self.hold["through_combat"] and active_combat(observation)):
                return False  # the person said to pass up to a later step and nothing here stops that
            return not self._passed_here(decision)
        side = "own" if observation.get("active_seat") == me else "opp"
        return bool(self.stops.get(f"{side}_{observation.get('phase_step')}", False))

    # -- the person's pass-until, as the Manabrew client sends it ----------------------------------------------------

    def _hold_unreached(self, observation: Mapping[str, Any]) -> bool:
        """Whether a hold is set and its target (a seat's turn and step) is still ahead of this position. A hold that
        has been reached (the turn of its seat has come to its step or past it) or lost (that turn went by without a
        window at or after the step: the engine offers priority in only some steps) is dropped."""
        hold = self.hold
        if hold is None:
            return False
        turn_key = (observation.get("turn"), observation.get("active_seat"))
        index = STEP_ORDER.index(observation["phase_step"]) if observation.get("phase_step") in STEP_ORDER else -1
        target = STEP_ORDER.index(hold["step"])
        if hold["turn"] is None and turn_key[1] == hold["seat"] and (turn_key != hold["origin"] or hold["origin_index"] < target):
            hold["turn"] = turn_key  # the turn the target is in: the first of that seat's turns that has it ahead
        if hold["turn"] is None:
            if hold["origin"][1] != hold["seat"] and turn_key[1] == hold["origin"][1] and turn_key != hold["origin"]:
                self.hold = None  # the seat's turn came and went with no window in it
                return False
            return True
        if turn_key == hold["turn"] and index < target:
            return True
        self.hold = None  # reached, or that turn is over
        return False

    def _decline_attack(self, decision: Mapping[str, Any]) -> int | None:
        """The "no attack" candidate of this attack declaration when a hold is still ahead (the engine's own rule: it
        does not ask for attackers while the person passes up to a later step), unless an attack is forced, that is, a
        creature has no "no attack" candidate. The rest of the declaration follows the first answer."""
        if not self.real_action_stops:
            return None
        candidates = decision.get("candidates") or []
        if {c["semantic"].get("kind") for c in candidates} != {"declare_attack"}:
            return None
        observation = decision.get("observation") or {}
        group = self._attack_group(decision)
        decline = next((c["candidate_id"] for c in candidates if c["semantic"].get("defender") is None), None)
        if self.forced_attack_group == group:
            return None
        if self.auto_attack_group == group:
            return decline
        self.auto_attack_group = None
        if decline is None or not self._hold_unreached(observation):
            return None
        self.auto_attack_group = group
        return decline

    @staticmethod
    def _attack_group(decision: Mapping[str, Any]) -> tuple[Any, ...]:
        observation = decision.get("observation") or {}
        return ("attack", (decision.get("group") or {}).get("group_id"), observation.get("turn"),
                observation.get("active_seat"))

    def _passed_here(self, decision: Mapping[str, Any]) -> bool:
        """Whether the person already passed at exactly this position (same turn and step, same stack, boards, hands,
        mana and combat, same choices): the engine offered priority again with nothing changed, so asking again
        shows the same screen. Any change at all, a new legal action, a new stack object, a new combat state, is a
        different position and is asked."""
        observation = decision.get("observation") or {}
        here = (observation.get("turn"), observation.get("active_seat"), observation.get("phase_step"))
        return self.passed_at == here and position_key(decision) in self.passed_keys

    def _remember_pass(self) -> None:
        """The person passed at the pending decision's position."""
        observation = self.observation or {}
        here = (observation.get("turn"), observation.get("active_seat"), observation.get("phase_step"))
        if self.passed_at != here:
            self.passed_at, self.passed_keys = here, set()
        if self.pending_key is not None:
            self.passed_keys.add(self.pending_key)

    def _from_plan(self, decision: Mapping[str, Any]) -> int | None:
        """The candidate a combat plan names for this substep, or ``None`` to ask the human."""
        plan = self.plan
        group = decision.get("group") or {}
        if plan is None or plan.get("group_id") != group.get("group_id"):
            self.plan = None
            return None
        candidates = decision.get("candidates") or []
        kinds = {c["semantic"].get("kind") for c in candidates}
        if plan["kind"] == "bottom" and kinds == {"order_pick"}:
            # The person put their mulligan cards back in one prompt: substep i names the i-th card they picked.
            position = (candidates[0]["semantic"] or {}).get("position")
            wanted = plan["cards"][position] if isinstance(position, int) and 0 <= position < len(plan["cards"]) else None
            for c in candidates:
                if ((c["semantic"].get("item") or {}).get("object") or {}).get("object_id") == wanted:
                    return c["candidate_id"]
            return None
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
        if not options:
            return  # only mana abilities (``client_autopass``): the client counts this window down by itself
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
        elif (kinds == {"order_pick"} and group.get("substep_index") == 0
              and all((c["semantic"] or {}).get("purpose") == "mulligan_bottom" for c in candidates)):
            screen = "bottom"
        # The engine's autopay only uses plain tap sources, so a spell payable only with mana from a costed source
        # (an Eldrazi Spawn's sacrifice, a Treasure) is not offered until that mana is floating.
        hint = PUT_BACK_NOTE if screen == "bottom" else None
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
                "log_total": self.log_total, "advisor": self.advisor_identity, "advice": self.advice,
                "game_over": self.game_over, "stops": self.stops, "skip": self.skip, "now": _ms(),
                "phases": list(PHASE_STEPS)}

    def answer_with(self, seq: int, candidate_id: int) -> str | None:
        with self.cond:
            pending = self.pending
            if pending is None or pending["seq"] != seq:
                return "stale decision"
            chosen = next((c for c in pending["candidates"] if c["id"] == candidate_id), None)
            if chosen is None:
                return "not a candidate"
            if chosen["kind"] == "pass":
                self._remember_pass()
            self._clear_holds()  # any answer of the person's but a pass with a target ends what they asked for before
            pending["how"] = "human"
            self.answer = candidate_id
            self._bump()
            return None

    def _note_stop_moved(self, seat: str, asked: str, moved: str, origin: tuple[Any, Any], index: int) -> None:
        """Say once per turn why a stop the person set cannot be taken where they put it (display only). ``index``:
        the step they are in, in ``STEP_ORDER``."""
        key = (origin[0], seat, asked)
        if self._stop_moved_noted == key:
            return
        self._stop_moved_noted = key
        me = (self.game or {}).get("seat")
        owner = "your" if seat == me else "the opponent's"
        names = text.STEP_NAMES
        line = f"The engine gives no priority in {owner} {names.get(asked, asked)}"
        if origin[1] == seat and index >= STEP_ORDER.index(moved):
            line += ", and there is no later priority this turn."
        else:
            line += f", so your stop there is taken in {owner} {names.get(moved, moved)}, the nearest priority there is."
        self._note("game", line)

    def _clear_holds(self) -> None:
        self.hold = None
        self.exhaust_stack, self.exhaust_ids = False, frozenset()

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
            elif kind == "bottom":
                self.plan = {"kind": "bottom", "cards": [str(c) for c in plan.get("cards") or []]}
            else:
                return "unknown plan"
            self.plan["group_id"] = pending["group"].get("group_id")
            decision = {"candidates": [{"candidate_id": c["id"], "semantic": c["semantic"]}
                                       for c in pending["candidates"]], "group": pending["group"]}
            chosen = self._from_plan(decision)
            if chosen is None:
                self.plan = None
                return "the plan does not fit this declaration; choose substeps one by one"
            self._clear_holds()
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
                return self.pass_with(seq, None, exhaust_stack=True)
            return self.control("pass_turn", {})

    def pass_with(self, seq: int, until: Mapping[str, Any] | None = None, *, exhaust_stack: bool = False) -> str | None:
        """The person passes priority at the decision ``seq`` and says how far (the Manabrew client's pass buttons).
        ``until``: ``{"seat", "step", "through_combat"}``, the pass-until the client sends, which replaces any earlier
        one (no ``until`` clears it); later priorities are passed for the person while it is ahead (see
        ``_stops_here``). ``exhaust_stack``: pass every priority until the stack is empty or holds an object that was
        not there now."""
        with self.cond:
            pending = self.pending
            if pending is None or pending["seq"] != seq:
                return "stale decision"
            if (pending.get("context") or {}).get("kind") != "priority":
                return "not a priority decision"
            passing = next((c["id"] for c in pending["candidates"] if c["kind"] == "pass"), None)
            if passing is None:
                return "passing is not a choice here"
            self._remember_pass()
            self._clear_holds()
            observation = self.observation or {}
            if exhaust_stack:
                self.exhaust_stack, self.exhaust_ids = True, frozenset(stack_ids(observation))
            if isinstance(until, Mapping) and until.get("step") in STEP_ORDER and until.get("seat") in ("p0", "p1"):
                phase = observation.get("phase_step")
                origin = (observation.get("turn"), observation.get("active_seat"))
                index = STEP_ORDER.index(phase) if phase in STEP_ORDER else -1
                # A step the engine never gives the person priority in (without full priority: the end step above
                # all) is aimed at the nearest window that exists, so the person is stopped where they can act
                # instead of being passed past the turn.
                step = reachable_step(until["step"], self.priority_steps)
                if step != until["step"]:
                    self._note_stop_moved(until["seat"], until["step"], step, origin, index)
                self.hold = {"seat": until["seat"], "step": step,
                             "through_combat": bool(until.get("through_combat")), "origin": origin,
                             "origin_index": index,
                             # the turn the target is in: this one if it is the seat's and the step asked for is ahead
                             "turn": origin if origin[1] == until["seat"] and index < STEP_ORDER.index(until["step"]) else None}
            pending["how"] = "human"
            self.answer = passing
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

    def wait_state(self, since: int, timeout: float = 25.0, frames_from: int | None = None,
                   frames_game: Any = None, positions_from: int | None = None) -> dict[str, Any]:
        """The state once its version is above ``since`` (or after ``timeout``). With ``frames_from`` (a count of
        frames already taken) the state also holds ``frames``, the observations of the decisions since at which the
        stack changed, oldest first, ``frames_total`` and ``frames_game`` (the game they belong to), taken at the same
        moment as the state itself. The count belongs to one game: a new game restarts it, so a count taken in
        another game (``frames_game`` names it) or above the new total is not a position in this game's frames.
        ``positions_from`` does the same for ``positions`` (every change the board shows, for the paced drawing):
        ``positions`` and ``positions_total``."""
        with self.cond:
            deadline = time.monotonic() + timeout
            while self.version <= since:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.cond.wait(remaining)
            state = self.state()
            if frames_from is not None:
                current = (self.game or {}).get("game_id")
                if (frames_game is not None and frames_game != current) or frames_from > self.frames_total:
                    frames_from = 0  # the cursor is from an earlier game: this game's frames all count
                first = self.frames_total - len(self.frames)  # position of frames[0]
                state["frames"] = list(self.frames[max(frames_from - first, 0):])
                state["frames_total"] = self.frames_total
                state["frames_game"] = current
            if positions_from is not None:
                current = (self.game or {}).get("game_id")
                if (frames_game is not None and frames_game != current) or positions_from > self.positions_total:
                    positions_from = 0
                # the reader has drawn everything before its cursor: those can go; the rest stay until taken
                self.positions_reader = True
                self.positions_taken = max(self.positions_taken, positions_from)
                first = self.positions_total - len(self.positions)
                state["positions"] = list(self.positions[max(positions_from - first, 0):])
                state["positions_total"] = self.positions_total
                if positions_from < first:  # more were waiting than POSITION_UNSENT_LIMIT: say how many are gone
                    state["positions_gap"] = first - positions_from
                state["frames_game"] = current
                self._trim_positions()
            return state

    def _trim_positions(self) -> None:
        """Let positions go: with no reader, all but the newest POSITION_LIMIT; with one, those it has taken, and the
        oldest of the rest only beyond POSITION_UNSENT_LIMIT (``wait_state`` then reports the gap)."""
        first = self.positions_total - len(self.positions)
        if not self.positions_reader:
            drop = len(self.positions) - POSITION_LIMIT
        else:
            taken = max(0, self.positions_taken - first)
            drop = max(taken, len(self.positions) - POSITION_UNSENT_LIMIT)
        if drop > 0:
            del self.positions[:drop]


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
                    # a session with an advisor asks the relay to keep the model input of the person's decisions
                    self._json({"ok": True, "advisor": hub.advisor is not None})
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
