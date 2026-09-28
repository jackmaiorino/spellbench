"""The v2 game loop: routing, canonical forwarding, the digest and halts (spec 11.2, 11.5, 11.8).

``play_game`` drives one game end to end: it builds the ``reset`` request and starts the
digest from it, starts both seats at once, sends ``reset``, then alternates between
validating the engine's decision (``host.validator.LiveValidator``), asking the acting
seat to choose, and sending the engine ``step``. Every engine answer and step request is
chained into the digest as it happens (spec 11.8), whether the call succeeds or fails, so
the digest is a faithful record of the wire traffic even when the game ends in a fault.

Three endings are host-recorded rather than reported by the engine (spec 11.5): a
``forfeit`` (a seat driver failed), a ``halt`` (a live-validation violation, or an engine
fault: ``error``, ``timeout``, ``transport``, ``malformed``, ``terminal_counts`` or
``terminal_reason``). Each appends its own adjudication record to the digest
(``_halt``, ``_forfeit_for``) and sends every started, unsilenced seat a ``game_over``.
A legitimate engine terminal (``natural``, ``truncated`` or an engine-reported
``halted``) needs no adjudication record: the terminal message chained through the
digest already speaks for itself.

Part B (Task 29) wires the bank clock, seat caps and the stalling window through three
hooks that this task stubs out: ``_budget_ms`` (always ``max_decision_ms``), ``_charge``
and ``_after_answer`` (always ``None``, so they never end the game here).
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
    (``{"kind", "detail"}`` for a halt, plus ``cause`` and ``loser_seat`` for a forfeit),
    or ``None`` for a natural, truncated or engine-reported halted terminal, which needs
    no host adjudication. ``violation`` is ``{"rule", "detail"}`` when the halt was a
    live-validation violation, else ``None``. ``step_count`` counts the answered
    decisions (including one adjudicated right after its answer and before its ``step``
    was sent, Task 29's Decision 5), and ``decision_count`` the completed groups the
    validator counted (R3-12). ``last_selection_seat`` is the seat of the last answered
    decision for a halted or truncated game, else ``None``.
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
    def __init__(self, setup: GameSetup, engine: EngineProcess, seats: Mapping[str, SeatDriver], clock_ns) -> None:
        if engine.hello_result is None:
            raise ProtocolError("play_game needs an engine that answered hello")
        self.setup, self.engine, self.seats, self.clock_ns = setup, engine, seats, clock_ns
        self.hello = engine.hello_result
        self.validator = LiveValidator(self.hello, setup.rules)
        self.reset = ResetRequest(request_id=engine.next_request_id(), game_id=setup.game_id, format=setup.format,
                                  seats=setup.wire_decks, rules=setup.rules, game_secret=setup.game_secret_hex,
                                  max_decisions=setup.limits.max_decisions, max_steps=setup.limits.max_steps)
        self.digest = GameDigest(self.reset.to_json())
        self.started: list[str] = []
        self.silenced: set[str] = set()      # seats closed after a timeout or transport failure: sent nothing more (R2-4)
        self.last_seat: str | None = None
        self.diagnostics: list[str] = []

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
                return self._halt(f"host_validator:{violation.rule}", violation.detail, violation=violation)
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
        """Start both seats concurrently, joined by one shared deadline (R2-26).

        Records both seats as started whether or not their ``start`` call succeeded, then
        silences (closes) every seat whose failure was a timeout or a transport error: its
        request is still outstanding or its process is gone (R2-4).
        """
        game_start_timeout_s = self.setup.time_control.game_start_ms / 1000
        deadline_s = (self.setup.time_control.startup_ms + self.setup.time_control.game_start_ms) / 1000
        results: dict[str, SeatFailure | None] = {}

        def run(seat: str) -> None:
            try:
                self.seats[seat].start(self._game_start_payload(seat), timeout_s=game_start_timeout_s)
            except SeatFailure as failure:
                results[seat] = failure
            else:
                results[seat] = None

        threads = {seat: threading.Thread(target=run, args=(seat,), daemon=True) for seat in SEATS}
        started_ns = self.clock_ns()
        for thread in threads.values():
            thread.start()
        self.started.extend(SEATS)
        for seat in SEATS:
            elapsed_s = (self.clock_ns() - started_ns) / 1_000_000_000
            threads[seat].join(max(0.0, deadline_s - elapsed_s))
            if seat not in results:
                ms = self.setup.time_control.game_start_ms
                results[seat] = SeatFailure("timeout", f"no answer to game_start within {ms} ms")
        for seat in SEATS:
            failure = results[seat]
            if failure is not None and failure.cause in _SILENCING_CAUSES:
                self._silence(seat)
        return results

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
        clock = Clock(remaining_ms=budget_ms, max_decision_ms=self.setup.time_control.max_decision_ms)
        payload = choose_payload(game_id=self.setup.game_id, seat_decision=sd, clock=clock)
        started_ns = self.clock_ns()
        try:
            choice = self.seats[seat].choose(payload, timeout_s=budget_ms / 1000)
        except SeatFailure as failure:
            if failure.cause in _SILENCING_CAUSES:
                self._silence(seat)
            return self._forfeit(seat, failure)
        elapsed_ms = (self.clock_ns() - started_ns) / 1_000_000
        ruling = self._charge(seat, sd, elapsed_ms)
        if ruling is not None:
            return ruling
        detail = _invalid_answer(sd, choice)
        if detail is not None:
            return self._forfeit_for(seat, "invalid_selection", detail)
        return choice.candidate_id

    def _silence(self, seat: str) -> None:
        self.silenced.add(seat)
        self.seats[seat].close()

    # -- the engine's answers, chained into the digest whether they fault or not --

    def _engine(self, phase: str, call: Callable[[], Decision | Terminal], *, step: bool) -> Decision | Terminal | GameResult:
        """Run ``call``, chain its wire traffic into the digest, and map an engine fault to a halt."""
        self.engine.set_timeout(self.setup.time_control.engine_step_ms / 1000)
        try:
            result = call()
        except EngineError as exc:
            self._note(exc)
            self._chain_engine(step)
            return self._halt("host_engine_fault:error", f"the engine answered {phase} with error {exc.code}")
        except PeerTimeoutError as exc:
            self._note(exc)
            self._chain_engine(step)
            ms = self.setup.time_control.engine_step_ms
            return self._halt("host_engine_fault:timeout", f"the engine did not answer {phase} within {ms} ms")
        except TerminalCountError as exc:
            self._note(exc)
            self._chain_engine(step)
            return self._halt("host_engine_fault:terminal_counts", self._terminal_counts_detail(exc.terminal.result))
        except TerminalReasonError as exc:
            self._note(exc)
            self._chain_engine(step)
            return self._halt("host_engine_fault:terminal_reason", str(exc))
        except TransportError as exc:
            self._note(exc)
            self._chain_engine(step)
            return self._halt("host_engine_fault:transport", f"the engine process failed at {phase}")
        except ProtocolError as exc:
            self._note(exc)
            self._chain_engine(step)
            return self._halt("host_engine_fault:malformed", f"the engine's answer to {phase} was not a valid protocol message")
        else:
            self._chain_engine(step)
            return result

    def _note(self, exc: BaseException) -> None:
        self.diagnostics.append(str(exc))
        stderr = self.engine.stderr_text()
        if stderr:
            self.diagnostics.append(stderr)

    def _chain_engine(self, step: bool) -> None:
        if step:
            self.digest.add_step(self.engine.last_request, self.engine.last_response)
        elif self.engine.last_response is not None:
            self.digest.add_response(self.engine.last_response)

    def _terminal_counts_detail(self, result: TerminalResult) -> str:
        return (f"terminal step_count {result.step_count}, decision_count {result.decision_count}; "
                f"host counted {self.validator.answered_steps}, {self.validator.completed_groups}")

    # -- Part B hooks (Task 29): the bank clock, caps and stalling -----------

    def _budget_ms(self, seat: str) -> int:
        return self.setup.time_control.max_decision_ms

    def _charge(self, seat: str, sd: Mapping[str, Any], elapsed_ms: float) -> GameResult | None:
        return None

    def _after_answer(self, seat: str, sd: Mapping[str, Any], candidate_id: int) -> GameResult | None:
        return None

    # -- endings: a legitimate terminal, a host halt, a forfeit --------------

    def _terminal(self, response: Terminal) -> GameResult:
        """A terminal the engine client already bound and count-checked for step_count (spec 9.3 to 9.5).

        The host still checks it (V3, V10) and its decision_count, which only the host's
        group tracking knows; either failure halts instead of accepting it.
        """
        try:
            self.validator.check_terminal(response)
        except ValidatorViolation as violation:
            return self._halt(f"host_validator:{violation.rule}", violation.detail, violation=violation)
        result = response.result
        if result.step_count != self.validator.answered_steps or result.decision_count != self.validator.completed_groups:
            return self._halt("host_engine_fault:terminal_counts", self._terminal_counts_detail(result))
        last_selection_seat = self.last_seat if result.classification in ("halted", "truncated") else None
        self._send_game_over(outcome=result.outcome, classification=result.classification, winner=result.winner,
                             reason=result.reason)
        return self._result(outcome=result.outcome, classification=result.classification, winner=result.winner,
                            reason=result.reason, adjudication=None, last_selection_seat=last_selection_seat)

    def _halt(self, reason: str, detail: str, *, violation: ValidatorViolation | None = None) -> GameResult:
        self.digest.add_adjudication(classification="halted", outcome="halted", reason=reason, winner=None)
        self._send_game_over(outcome="halted", classification="halted", winner=None, reason=reason)
        violation_dict = None if violation is None else {"rule": violation.rule, "detail": violation.detail}
        return self._result(outcome="halted", classification="halted", winner=None, reason=reason,
                            adjudication={"kind": "halt", "detail": detail}, last_selection_seat=self.last_seat,
                            violation=violation_dict)

    def _forfeit_for(self, seat: str, cause: str, detail: str) -> GameResult:
        """Every forfeit ending (spec 11.5): a live seat failure, or (Task 29) stalling."""
        winner = _other(seat)
        outcome, reason = f"{winner}_win", f"forfeit:{cause}"
        self.digest.add_adjudication(classification="forfeit", outcome=outcome, reason=reason, winner=winner)
        self._send_game_over(outcome=outcome, classification="forfeit", winner=winner, reason=reason)
        adjudication = {"kind": "forfeit", "cause": cause, "loser_seat": seat, "detail": detail}
        return self._result(outcome=outcome, classification="forfeit", winner=winner, reason=reason,
                            adjudication=adjudication, last_selection_seat=None)

    def _forfeit(self, seat: str, failure: SeatFailure) -> GameResult:
        return self._forfeit_for(seat, failure.cause, failure.detail)

    def _send_game_over(self, *, outcome: str, classification: str, winner: str | None, reason: str) -> None:
        """``game_over`` to every started, unsilenced seat, ignoring failures (spec 10.4, 11.5; R2-4)."""
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
    """Play one game end to end (the engine has answered ``hello``; the caller closes the engine and the seats)."""
    return _Game(setup, engine, seats, clock_ns).play()
