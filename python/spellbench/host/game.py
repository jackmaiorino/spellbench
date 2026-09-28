"""The v2 game loop: routing, canonical forwarding, the digest and halts (spec 11.2, 11.5, 11.8).

``play_game`` drives one game end to end: it builds the ``reset`` request and starts the
digest from it, starts both seats at once, sends ``reset``, then alternates between
validating the engine's decision (``host.validator.LiveValidator``), asking the acting
seat to choose, and sending the engine ``step``.

The digest (spec 11.8) chains the engine exchanges that were written and answered: each
step request, and each answer whose line is JSON. An exchange that got no answer line (a
failed write, a timeout, EOF) is not chained, so a halted game's digest never depends on
whether the failure surfaced at the write or at the read, which is a matter of timing (a
bot's think time, say). Nothing from an agent enters it.

The host records three endings itself (spec 11.5), each appending one adjudication record
to the digest and sending ``game_over`` to every started seat it has not closed: a
``forfeit`` (a seat failed, its clock ran out, or it stalled at a cap; ``_forfeit_for``), a
``halt`` (a live-validation violation, or an engine fault: ``error``, ``timeout``,
``transport``, ``malformed``, ``terminal_counts`` or ``terminal_reason``; ``_halt``) and the
mandatory-loop draw (``_draw``). An engine terminal (``natural``, ``truncated`` or an
engine-reported ``halted``) gets no adjudication record: its answer in the chain already
records it.

A host fault is never charged to a participant. A seat driver raises only ``SeatFailure``
(``host.seat``), so any other exception from ``start``, ``choose`` or ``game_over`` is the
host's, as is ``HostMisuseError`` from the engine client (a call out of sequence, such as a
reused engine): each propagates out of ``play_game``, and no result is recorded.

Clocks and caps (spec 11.4, Task 29) run through three hooks. Each seat has a Fischer clock
(``host.clock.SeatClock``): ``choose`` shows the bank as it stands before that decision and
is bounded by ``_budget_ms``, the smaller of the bank and ``max_decision_ms``; ``_charge``
then charges the answer's wall time, in whole milliseconds rounded up, and an answer over
either limit is a ``timeout`` forfeit even though it arrived. ``_after_answer`` counts every
answered decision toward the seat's caps and the stalling window over both seats' last 250
answers, that one included. When the answer reaches a cap, the host rules at once, before
that answer's ``step`` is sent (Decision 5), and ``step_count`` still counts it (R3-12): a
``stalling`` forfeit of the seat with more real choices in the window (on a tie, the seat
that reached the cap), or, when neither seat made one, the mandatory-loop draw.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .. import wire
from .._schema import SEATS
from ..agent_messages import AgentTerminal, Choice, Clock, choose_payload, game_over_payload, game_start_payload
from ..digests import GameDigest
from ..errors import EngineError, PeerTimeoutError, ProtocolError, TransportError
from ..messages import Decision, ResetRequest, Terminal, TerminalResult
from .clock import STALLING_WINDOW, SeatCaps, SeatClock, StallingWindow, is_real_choice
from .engine_process import EngineProcess, TerminalCountError, TerminalReasonError
from .seat import SeatDriver, SeatFailure
from .setup import GameSetup  # re-exported
from .validator import LiveValidator
from .violation import ValidatorViolation

# Spec 11.5: a seat driver failure that leaves its request outstanding or its process
# gone; the host closes that seat's driver at once and sends it nothing more (R2-4).
_SILENCING_CAUSES = ("timeout", "transport_error")


@dataclass(frozen=True)
class GameResult:
    """One game's outcome, however it ended.

    ``adjudication`` is the ledger shape of ``arena.ledger.Adjudication.to_json()``
    (``{"kind", "detail"}`` for a halt or the mandatory-loop draw, plus ``cause`` and
    ``loser_seat`` for a forfeit), or ``None`` for an engine terminal (natural, truncated
    or halted), which needs no host adjudication. ``violation`` is ``{"rule", "detail"}``
    when the halt was a live-validation violation, else ``None``. ``step_count`` counts
    the answered decisions (including one a cap adjudicates right after its answer,
    before its ``step`` is sent: Decision 5), and ``decision_count`` the completed groups
    the validator counted (R3-12). ``last_selection_seat`` is the seat of the last
    answered decision for a halted or truncated game, else ``None``.
    """

    outcome: str
    classification: str
    winner: str | None
    reason: str
    adjudication: dict[str, Any] | None
    step_count: int
    decision_count: int
    decisions_checked: int
    last_selection_seat: str | None
    game_digest: str
    violation: dict[str, str] | None
    diagnostics: tuple[str, ...]


def _other(seat: str) -> str:
    return "p1" if seat == "p0" else "p0"


def _invalid_answer(sd: Mapping[str, Any], choice: Choice) -> str | None:
    """Why ``choice`` cannot be accepted, or ``None`` (spec 9.4, 10.3; R2-16).

    ``candidate_id`` must be in range, checked before it is ever used to index
    ``candidates``, so a negative id never indexes from the end. ``seat_step`` and
    ``semantic_echo``, when the agent sent them, must equal the offered decision by
    canonical bytes, so ``False`` never equals ``0`` (spec 4.3).
    """
    candidates = sd["candidates"]
    candidate_id = choice.candidate_id
    if not (0 <= candidate_id < len(candidates)):
        return f"candidate_id {candidate_id} is outside the {len(candidates)} candidates"
    if "seat_step" in choice.echoes:
        if wire.canonical_json_dumps(choice.echoes["seat_step"]) != wire.canonical_json_dumps(sd["seat_step"]):
            return "seat_step echo does not match the offered decision"
    if "semantic_echo" in choice.echoes:
        semantic = candidates[candidate_id]["semantic"]
        if wire.canonical_json_dumps(choice.echoes["semantic_echo"]) != wire.canonical_json_dumps(semantic):
            return "semantic_echo does not match the chosen candidate"
    return None


class _Game:
    def __init__(self, setup: GameSetup, engine: EngineProcess, seats: Mapping[str, SeatDriver],
                 clock_ns: Callable[[], int]) -> None:
        if engine.hello_result is None:
            raise ProtocolError("play_game needs an engine that answered hello")
        self.setup, self.engine, self.seats, self.clock_ns = setup, engine, seats, clock_ns
        self.hello = engine.hello_result
        self.validator = LiveValidator(self.hello, setup.rules, max_decisions=setup.limits.max_decisions,
                                       max_steps=setup.limits.max_steps)
        self.reset = ResetRequest(request_id=engine.next_request_id(), game_id=setup.game_id, format=setup.format,
                                  seats=setup.wire_decks, rules=setup.rules, game_secret=setup.game_secret_hex,
                                  max_decisions=setup.limits.max_decisions, max_steps=setup.limits.max_steps)
        self.digest = GameDigest(self.reset.to_json())
        self.started: list[str] = []
        self.silenced: set[str] = set()      # seats closed after a timeout or transport failure: sent nothing more (R2-4)
        self.last_seat: str | None = None
        self.diagnostics: list[str] = []
        # Spec 11.4: each seat's bank clock and caps, and the stalling window over both seats' answers.
        time_control, limits = setup.time_control, setup.limits
        self.clocks = {seat: SeatClock(time_control.bank_ms, time_control.increment_ms, time_control.max_decision_ms)
                       for seat in SEATS}
        self.caps = SeatCaps(per_turn=limits.max_seat_decisions_per_turn,
                             groups_per_game=limits.max_seat_decisions_per_game,
                             steps_per_game=limits.max_seat_steps_per_game)
        self.window = StallingWindow()

    def play(self) -> GameResult:
        failures = self._start_both()        # both seats at once; the results are judged p0 first (R2-26)
        for seat in SEATS:
            if failures[seat] is not None:
                return self._forfeit(seat, failures[seat])
        response = self._engine("reset", lambda: self.engine.reset(self.reset), step=False)
        while not isinstance(response, GameResult):
            if isinstance(response, Terminal):
                return self._terminal(response)
            try:
                sd = self.validator.check(response)
            except ValidatorViolation as violation:
                return self._violation(violation)
            seat = sd["acting_seat"]
            answer = self._ask(seat, sd)
            if isinstance(answer, GameResult):
                return answer
            self.validator.answered(sd, answer)
            self.last_seat = seat
            ruling = self._after_answer(seat, sd, answer)
            if ruling is not None:
                return ruling
            semantic = sd["candidates"][answer]["semantic"]
            response = self._engine(f"step {response.step}",
                                    lambda: self.engine.step(candidate_id=answer, semantic=semantic), step=True)
        return response

    # -- starting both seats -------------------------------------------------

    def _start_both(self) -> dict[str, SeatFailure | None]:
        """Start both seats at once and judge both starts once (spec 11.4, 11.5; R2-26).

        Both payloads are built first, so a setup the host cannot send raises here, before any
        seat starts. Each ``start`` runs on its own thread, all joined by one shared deadline of
        ``startup_ms + game_start_ms`` (a subprocess driver bounds its launch and ``hello`` by
        ``startup_ms``, then its ``game_start`` by ``game_start_ms``). The judgment is taken
        once, under a lock, from what the threads reported by then; a thread that reports
        later changes nothing. A start still running is a ``timeout`` and a ``SeatFailure``
        keeps its own cause; a seat that timed out or whose process failed
        (``transport_error``) is closed at once and sent nothing more (R2-4). Any other
        exception is a host fault: once both starts are judged it is raised (p0's first), and
        neither seat forfeits.
        """
        time_control = self.setup.time_control
        payloads = {seat: self._game_start_payload(seat) for seat in SEATS}
        lock = threading.Lock()
        reported: dict[str, BaseException | None] = {}
        judged = False

        def run(seat: str) -> None:
            try:
                self.seats[seat].start(payloads[seat], timeout_s=time_control.game_start_ms / 1000)
                outcome = None
            except BaseException as exc:  # noqa: BLE001 - classified on the host's thread once judged
                outcome = exc
            with lock:
                if not judged:
                    reported[seat] = outcome

        threads = [threading.Thread(target=run, args=(seat,), name=f"game-start-{seat}", daemon=True) for seat in SEATS]
        limit_ms = time_control.startup_ms + time_control.game_start_ms
        deadline = time.monotonic() + limit_ms / 1000
        for thread in threads:
            thread.start()
        self.started.extend(SEATS)
        for thread in threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        overrun = f"the seat did not start within {limit_ms} ms (startup_ms plus game_start_ms)"
        with lock:
            judged = True
            outcomes = {seat: reported[seat] if seat in reported else SeatFailure("timeout", overrun) for seat in SEATS}
        for seat, outcome in outcomes.items():
            if isinstance(outcome, SeatFailure) and outcome.cause in _SILENCING_CAUSES:
                self._silence(seat)
        for outcome in outcomes.values():
            if outcome is not None and not isinstance(outcome, SeatFailure):
                raise outcome
        return outcomes

    def _game_start_payload(self, seat: str) -> dict[str, Any]:
        """``game_start`` past the envelope (spec 10.2); ``opponent_deck`` per the rules (R2-24)."""
        index = SEATS.index(seat)
        opponent_deck = self.setup.own_decks[1 - index] if self.setup.rules.opponent_decklist == "visible" else None
        return game_start_payload(
            game_id=self.setup.game_id, seat=seat, format=self.setup.format, own_deck=self.setup.own_decks[index],
            opponent_deck=opponent_deck, rules=self.setup.rules, engine=self.hello.engine,
            engine_profile=self.hello.profile, time_control=self.setup.time_control, limits=self.setup.limits,
            resources=self.setup.resources, agent_seed=self.setup.agent_seeds[index],
        )

    # -- asking the acting seat ----------------------------------------------

    def _ask(self, seat: str, sd: Mapping[str, Any]) -> int | GameResult:
        """The acting seat's answer, a candidate id, or the ``GameResult`` of a forfeit."""
        budget_ms = self._budget_ms(seat)
        # Spec 10.3: remaining_ms is the seat's bank when choose is sent, before this decision is charged.
        clock = Clock(remaining_ms=self.clocks[seat].remaining_ms, max_decision_ms=self.setup.time_control.max_decision_ms)
        # The driver gets its own copy, the canonical re-serialization of the validated decision (spec 11.2): nothing
        # it does to its payload reaches the host's, which the step echo and the group tracking read.
        forwarded = wire.strict_json_loads(wire.canonical_json_dumps(sd))
        payload = choose_payload(game_id=self.setup.game_id, seat_decision=forwarded, clock=clock)
        started_ns = self.clock_ns()
        try:
            choice = self.seats[seat].choose(payload, timeout_s=budget_ms / 1000)
        except SeatFailure as failure:
            if failure.cause in _SILENCING_CAUSES:
                self._silence(seat)
                return self._forfeit(seat, failure)
            # Spec 11.4: a decision that exceeds its budget is a timeout, whatever came back. The peer's write and
            # read are each bounded by the budget, so a malformed answer or an error envelope can arrive late too.
            late = self._charge(seat, sd, self._elapsed_ms(started_ns))
            return late if late is not None else self._forfeit(seat, failure)
        ruling = self._charge(seat, sd, self._elapsed_ms(started_ns))
        if ruling is not None:
            return ruling
        detail = _invalid_answer(sd, choice)
        if detail is not None:
            return self._forfeit_for(seat, "invalid_selection", detail)
        return choice.candidate_id

    def _elapsed_ms(self, started_ns: int) -> int:
        """Wall time since ``started_ns`` in whole milliseconds, rounded up."""
        return -(-(self.clock_ns() - started_ns) // 1_000_000)

    def _silence(self, seat: str) -> None:
        self.silenced.add(seat)
        self.seats[seat].close()

    # -- the engine's answers ------------------------------------------------

    def _engine(self, phase: str, call: Callable[[], Decision | Terminal], *, step: bool) -> Decision | Terminal | GameResult:
        """Run ``call`` (``reset`` or one ``step``), chain its exchange into the digest, and halt on an engine fault.

        Only the exceptions below are the engine's; anything else, ``HostMisuseError`` included,
        is the host's and propagates (module docstring).
        """
        self.engine.set_timeout(self.setup.time_control.engine_step_ms / 1000)
        try:
            result = call()
        except EngineError as exc:
            return self._engine_fault(exc, step, "error", f"the engine answered {phase} with error {exc.code}")
        except PeerTimeoutError as exc:
            ms = self.setup.time_control.engine_step_ms
            return self._engine_fault(exc, step, "timeout", f"the engine did not answer {phase} within {ms} ms")
        except TerminalCountError as exc:       # before ProtocolError, its base (R2-3)
            return self._engine_fault(exc, step, "terminal_counts", self._terminal_counts_detail(exc.terminal.result),
                                      terminal=exc.terminal)
        except TerminalReasonError as exc:      # before ProtocolError, its base
            return self._engine_fault(exc, step, "terminal_reason", str(exc), terminal=exc.terminal)
        except TransportError as exc:
            return self._engine_fault(exc, step, "transport", f"the engine process failed at {phase}")
        except ProtocolError as exc:
            return self._engine_fault(exc, step, "malformed",
                                      f"the engine's answer to {phase} was not a valid protocol message")
        self._chain(step)
        return result

    def _engine_fault(self, exc: BaseException, step: bool, fault: str, detail: str, *,
                      terminal: Terminal | None = None) -> GameResult:
        """Halt as ``host_engine_fault:<fault>``, after chaining the exchange if it was answered.

        A terminal the engine client refused still meets the validator's terminal checks
        first, so V3 and V10 outrank a count or reason fault as they do in ``_terminal``.
        """
        self._note(exc)
        self._chain(step)
        if terminal is not None:
            try:
                self.validator.check_terminal(terminal)
            except ValidatorViolation as violation:
                return self._violation(violation)
        return self._halt(f"host_engine_fault:{fault}", detail)

    def _chain(self, step: bool) -> None:
        """Chain the exchange just made when it was written and answered (spec 11.8; module docstring).

        The engine client clears ``last_request`` before each write and sets it only once an
        answer line arrives, so ``None`` here means this call got no answer.
        """
        request, response = self.engine.last_request, self.engine.last_response
        if request is None:
            return
        if step:
            self.digest.add_step(request, response)
        elif response is not None:
            self.digest.add_response(response)      # the reset request itself seeds the digest

    def _note(self, exc: BaseException) -> None:
        """The exception text, and the engine's stderr unless that text already quotes it (``wire.SubprocessPeer``'s
        transport failures do), go to ``diagnostics``: never to the ledger or the digest."""
        self.diagnostics.append(str(exc))
        stderr = "" if isinstance(exc, TransportError) else self.engine.stderr_text()
        if stderr:
            self.diagnostics.append(stderr)

    def _terminal_counts_detail(self, result: TerminalResult) -> str:
        return (f"terminal step_count {result.step_count}, decision_count {result.decision_count}; "
                f"host counted {self.validator.answered_steps}, {self.validator.completed_groups}")

    # -- the bank clock, caps and stalling (spec 11.4) ------------------------

    def _budget_ms(self, seat: str) -> int:
        """This decision's budget: the smaller of ``max_decision_ms`` and the seat's bank."""
        return self.clocks[seat].budget_ms()

    def _charge(self, seat: str, sd: Mapping[str, Any], elapsed_ms: int) -> GameResult | None:
        """Charge an answer's time to the seat's bank; over ``max_decision_ms`` or the bank, it forfeits ``timeout``."""
        if self.clocks[seat].charge(elapsed_ms):
            return None
        return self._forfeit_for(seat, "timeout",
                                 f"the answer to choose at seat step {sd['seat_step']} exceeded the seat's clock")

    def _after_answer(self, seat: str, sd: Mapping[str, Any], candidate_id: int) -> GameResult | None:
        """Count the answer toward the stalling window and the seat's caps; rule at once if it reaches a cap.

        A cap is reached when the seat's count equals it (Decision 5). ``turn`` is the
        observation's, and the answer completes a group when it was the group's last substep
        (spec 8). The window holds this answer too, and the ruling is a ``stalling`` forfeit
        of ``ruling.loser_seat`` or, with no real choice in the window, the mandatory-loop draw.
        """
        group, candidates = sd["group"], sd["candidates"]
        chosen_kind = candidates[candidate_id]["semantic"]["kind"]
        self.window.record(seat, real_choice=is_real_choice(len(candidates), chosen_kind))
        # A group counts once its last substep is answered, even if a rewind later abandons it: spec 8 takes abandoned
        # groups out of decision_count only, and counting them here keeps spec 11.4's promise that two seats within
        # their caps never jointly reach a game cap.
        cap = self.caps.record(seat, turn=sd["observation"]["turn"],
                               completed_group=group["substep_index"] + 1 == group["substep_count"])
        if cap is None:
            return None
        reached = f"{seat} reached {cap} ({getattr(self.setup.limits, cap)})"
        ruling = self.window.ruling(seat)
        if ruling.kind == "draw":
            return self._draw(f"{reached}; no real choice in the last {STALLING_WINDOW} decisions")
        counts = self.window.counts()
        return self._forfeit_for(ruling.loser_seat, "stalling",
                                 f"{reached}; real choices in the last {STALLING_WINDOW} decisions: "
                                 f"p0 {counts['p0']}, p1 {counts['p1']}")

    # -- endings: an engine terminal, a host halt, a forfeit, a draw ---------

    def _terminal(self, response: Terminal) -> GameResult:
        """An engine terminal the client already bound and checked for its reason and ``step_count`` (spec 9.3 to 9.5).

        The host still checks it, the validator first: V3 and V10 (spec 11.3), then both
        counts, of which only the host's group tracking can check ``decision_count``
        (Decision 4). A failure halts the game instead of accepting it.
        """
        try:
            self.validator.check_terminal(response)
        except ValidatorViolation as violation:
            return self._violation(violation)
        result = response.result
        if result.step_count != self.validator.answered_steps or result.decision_count != self.validator.completed_groups:
            return self._halt("host_engine_fault:terminal_counts", self._terminal_counts_detail(result))
        last_selection_seat = self.last_seat if result.classification in ("halted", "truncated") else None
        self._send_game_over(outcome=result.outcome, classification=result.classification, winner=result.winner,
                             reason=result.reason)
        return self._result(outcome=result.outcome, classification=result.classification, winner=result.winner,
                            reason=result.reason, adjudication=None, last_selection_seat=last_selection_seat)

    def _violation(self, violation: ValidatorViolation) -> GameResult:
        return self._halt(f"host_validator:{violation.rule}", violation.detail, violation=violation)

    def _halt(self, reason: str, detail: str, *, violation: ValidatorViolation | None = None) -> GameResult:
        self.digest.add_adjudication(classification="halted", outcome="halted", reason=reason, winner=None)
        self._send_game_over(outcome="halted", classification="halted", winner=None, reason=reason)
        violation_dict = None if violation is None else {"rule": violation.rule, "detail": violation.detail}
        return self._result(outcome="halted", classification="halted", winner=None, reason=reason,
                            adjudication={"kind": "halt", "detail": detail}, last_selection_seat=self.last_seat,
                            violation=violation_dict)

    def _forfeit_for(self, seat: str, cause: str, detail: str) -> GameResult:
        """Every forfeit ending (spec 11.5): a live seat failure, a late answer, or stalling at a cap (spec 11.4)."""
        winner = _other(seat)
        outcome, reason = f"{winner}_win", f"forfeit:{cause}"
        self.digest.add_adjudication(classification="forfeit", outcome=outcome, reason=reason, winner=winner)
        self._send_game_over(outcome=outcome, classification="forfeit", winner=winner, reason=reason)
        adjudication = {"kind": "forfeit", "cause": cause, "loser_seat": seat, "detail": detail}
        return self._result(outcome=outcome, classification="forfeit", winner=winner, reason=reason,
                            adjudication=adjudication, last_selection_seat=None)

    def _forfeit(self, seat: str, failure: SeatFailure) -> GameResult:
        return self._forfeit_for(seat, failure.cause, failure.detail)

    def _draw(self, detail: str) -> GameResult:
        """The mandatory-loop draw at a cap (spec 11.4, 11.5): a ``natural`` draw the host records itself (CR 104.4b)."""
        self.digest.add_adjudication(classification="natural", outcome="draw", reason="mandatory_loop", winner=None)
        self._send_game_over(outcome="draw", classification="natural", winner=None, reason="mandatory_loop")
        return self._result(outcome="draw", classification="natural", winner=None, reason="mandatory_loop",
                            adjudication={"kind": "mandatory_loop", "detail": detail}, last_selection_seat=None)

    def _send_game_over(self, *, outcome: str, classification: str, winner: str | None, reason: str) -> None:
        """``game_over`` to every started, unsilenced seat, ignoring its ``SeatFailure`` (spec 10.4, 11.5; R2-4)."""
        timeout_s = self.setup.time_control.game_start_ms / 1000
        for seat in SEATS:
            if seat not in self.started or seat in self.silenced:
                continue
            terminal = AgentTerminal(outcome=outcome, classification=classification, winner=winner, reason=reason,
                                     seat_step_count=self.validator.answered_by(seat))
            payload = game_over_payload(game_id=self.setup.game_id, terminal=terminal)
            try:
                self.seats[seat].game_over(payload, timeout_s=timeout_s)
            except SeatFailure:
                pass

    def _result(self, *, outcome: str, classification: str, winner: str | None, reason: str,
                adjudication: dict[str, Any] | None, last_selection_seat: str | None,
                violation: dict[str, str] | None = None) -> GameResult:
        return GameResult(
            outcome=outcome, classification=classification, winner=winner, reason=reason, adjudication=adjudication,
            step_count=self.validator.answered_steps, decision_count=self.validator.completed_groups,
            decisions_checked=self.validator.decisions_checked, last_selection_seat=last_selection_seat,
            game_digest=self.digest.value(), violation=violation, diagnostics=tuple(self.diagnostics),
        )


def play_game(setup: GameSetup, *, engine: EngineProcess, seats: Mapping[str, SeatDriver],
              clock_ns: Callable[[], int] = time.monotonic_ns) -> GameResult:
    """Play one game end to end (the engine has answered ``hello``; the caller closes the engine and the seats).

    A host fault propagates instead of returning a result (module docstring).
    """
    return _Game(setup, engine, seats, clock_ns).play()
