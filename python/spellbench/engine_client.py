"""Host-side client for the environment role (spec section 7).

Spawns (or wraps) an engine process, performs the hello handshake with
provenance pinning, and drives ``reset``/``step`` with step and group
contiguity validation. Idempotent retry (spec section 4.1) is available via
:meth:`EngineProcess.retry_last`.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ._client import Peer, RoleClient
from .errors import ENGINE_ERROR_CODES, EngineError, ProtocolError, ValidationError
from .models import (
    Decision,
    Deck,
    EnvHelloOk,
    ErrorResponse,
    Group,
    HelloRequest,
    Provenance,
    ResetRequest,
    SeatDeck,
    Selection,
    StepRequest,
    Terminal,
    TerminalResult,
)


class EngineProcess(RoleClient):
    """A client of one engine process (at most one active game per process)."""

    def __init__(
        self,
        argv: Sequence[str] | None = None,
        *,
        peer: Peer | None = None,
        timeout_s: float | None = None,
    ) -> None:
        super().__init__(argv, peer=peer, timeout_s=timeout_s)
        self._hello: EnvHelloOk | None = None
        self._provenance: Provenance | None = None
        self._game_id: str | None = None
        self._expected_step: int | None = None
        self._group: Group | None = None
        self._group_actor: str | None = None
        self._decision: Decision | None = None

    @property
    def hello_result(self) -> EnvHelloOk | None:
        return self._hello

    @property
    def provenance(self) -> Provenance | None:
        return self._provenance

    @property
    def game_id(self) -> str | None:
        return self._game_id

    @property
    def current_decision(self) -> Decision | None:
        return self._decision

    def hello(self, request: HelloRequest | None = None) -> EnvHelloOk:
        if self._hello is not None:
            raise ProtocolError("hello already completed for this process")
        if request is None:
            request = HelloRequest(request_id=self._next_request_id())
        self._claim_request_id(request.request_id)
        response, response_line = self._exchange(request.to_json())
        result = self._validate_response(response, request.to_json(), response_line)
        assert isinstance(result, EnvHelloOk)
        return result

    def reset(
        self,
        request: ResetRequest | None = None,
        *,
        game_id: str | None = None,
        format: str | None = None,
        decks: Sequence[Deck | Mapping[str, Any]] | None = None,
        game_seed: int | None = None,
        max_decisions: int | None = None,
        max_steps: int | None = None,
    ) -> Decision | Terminal:
        if self._hello is None:
            raise ProtocolError("reset before hello")
        if self._game_id is not None:
            raise ProtocolError("a game is already active on this process")
        if request is None:
            if (
                game_id is None
                or format is None
                or decks is None
                or game_seed is None
                or max_decisions is None
                or max_steps is None
            ):
                raise ProtocolError("reset requires game_id, format, decks, game_seed, max_decisions, max_steps")
            normalized = tuple(
                deck if isinstance(deck, Deck) else Deck.from_json(deck) for deck in decks
            )
            if len(normalized) != 2:
                raise ProtocolError("reset decks must have exactly two entries, p0 first")
            request = ResetRequest(
                request_id=self._next_request_id(),
                game_id=game_id,
                format=format,
                seats=(
                    SeatDeck(seat="p0", deck=normalized[0]),
                    SeatDeck(seat="p1", deck=normalized[1]),
                ),
                game_seed=game_seed,
                max_decisions=max_decisions,
                max_steps=max_steps,
            )
        self._claim_request_id(request.request_id)
        response, response_line = self._exchange(request.to_json())
        return self._validate_response(response, request.to_json(), response_line)

    def step(
        self,
        selection: Selection | int,
        *,
        semantic_echo: Mapping[str, Any] | None = None,
    ) -> Decision | Terminal:
        if self._game_id is None or self._expected_step is None or self._decision is None:
            raise ProtocolError("step without an active decision")
        if type(selection) is int:
            candidate_id = selection
            if semantic_echo is not None:
                raise ProtocolError("semantic_echo is derived from the decision when selection is an int")
            echo: Mapping[str, Any] | None = None
            if 0 <= candidate_id < len(self._decision.candidates):
                echo = self._decision.candidates[candidate_id].semantic
            if echo is None:
                raise ProtocolError("selection candidate_id is outside the current candidate list")
            selection = Selection(candidate_id=candidate_id, semantic_echo=dict(echo))
        else:
            if semantic_echo is not None:
                raise ProtocolError("pass either a Selection or candidate_id parts, not both")
            candidates = self._decision.candidates
            if selection.candidate_id >= len(candidates):
                raise ProtocolError("selection candidate_id is outside the current candidate list")
            if selection.semantic_echo != candidates[selection.candidate_id].semantic:
                raise ProtocolError("selection semantic_echo does not match the offered candidate")
        request = StepRequest(
            request_id=self._next_request_id(),
            game_id=self._game_id,
            expected_step=self._expected_step,
            selection=selection,
        )
        self._claim_request_id(request.request_id)
        response, response_line = self._exchange(request.to_json())
        return self._validate_response(response, request.to_json(), response_line)

    # ------------------------------------------------------------------

    def _validate_response(
        self,
        response: dict[str, Any],
        request: dict[str, Any],
        response_line: bytes,
    ) -> EnvHelloOk | Decision | Terminal:
        response_type = response.get("response_type")
        if response_type == "error":
            try:
                error = ErrorResponse.from_json(response, codes=ENGINE_ERROR_CODES)
            except ValidationError as exc:
                raise ProtocolError(f"invalid error response from engine: {exc}") from exc
            if error.request_id != request["request_id"]:
                raise ProtocolError("error response request_id mismatch")
            remote = EngineError(error.code, error.message)
            self._commit(request, response_line, remote)
            raise remote
        if response_type == "hello_ok":
            if request["request_type"] != "hello":
                raise ProtocolError("hello_ok response to a non-hello request")
            try:
                hello_ok = EnvHelloOk.from_json(response)
            except ValidationError as exc:
                raise ProtocolError(f"invalid hello_ok from engine: {exc}") from exc
            if hello_ok.request_id != request["request_id"]:
                raise ProtocolError("hello_ok request_id mismatch")
            self._hello = hello_ok
            self._provenance = hello_ok.engine.provenance()
            return self._commit(request, response_line, hello_ok)
        if response_type == "decision":
            if request["request_type"] not in ("reset", "step"):
                raise ProtocolError("decision response to a non-reset/step request")
            try:
                decision = Decision.from_json(response)
            except ValidationError as exc:
                raise ProtocolError(f"invalid decision from engine: {exc}") from exc
            self._validate_decision(decision, request)
            return self._commit(request, response_line, decision)
        if response_type == "terminal":
            if request["request_type"] not in ("reset", "step"):
                raise ProtocolError("terminal response to a non-reset/step request")
            try:
                terminal = Terminal.from_json(response)
            except ValidationError as exc:
                raise ProtocolError(f"invalid terminal from engine: {exc}") from exc
            self._validate_terminal(terminal, request)
            return self._commit(request, response_line, terminal)
        raise ProtocolError(f"unsupported response_type from engine: {response_type!r}")

    def _validate_common(self, echoed: str, game_id: str, provenance: Provenance, request: dict[str, Any]) -> None:
        if echoed != request["request_id"]:
            raise ProtocolError("response request_id mismatch")
        if game_id != request["game_id"]:
            raise ProtocolError("response game_id mismatch")
        if self._provenance is None or provenance != self._provenance:
            raise ProtocolError("engine provenance drifted within process")

    def _validate_decision(self, decision: Decision, request: dict[str, Any]) -> None:
        self._validate_common(decision.request_id, decision.game_id, decision.provenance, request)
        is_reset = request["request_type"] == "reset"
        expected_step = 0 if is_reset else request["expected_step"] + 1
        if decision.step != expected_step:
            raise ProtocolError(f"decision step drift: expected {expected_step}, got {decision.step}")
        group = decision.group
        if is_reset:
            if group.group_id != 0 or group.substep_index != 0:
                raise ProtocolError("initial decision must begin group 0 at substep 0")
        else:
            if self._group is None or self._game_id is None:
                raise ProtocolError("missing prior group state")
            if self._group.substep_index + 1 < self._group.substep_count:
                if (
                    group.group_id != self._group.group_id
                    or group.substep_index != self._group.substep_index + 1
                    or group.substep_count != self._group.substep_count
                    or decision.acting_seat != self._group_actor
                ):
                    raise ProtocolError("decision group substeps are not contiguous and stable")
            elif group.group_id != self._group.group_id + 1 or group.substep_index != 0:
                raise ProtocolError("group_id must advance by exactly 1 after a completed group")
        self._game_id = decision.game_id
        self._expected_step = decision.step
        self._group = group
        self._group_actor = decision.acting_seat
        self._decision = decision

    def _validate_terminal(self, terminal: Terminal, request: dict[str, Any]) -> None:
        self._validate_common(terminal.request_id, terminal.game_id, terminal.provenance, request)
        is_reset = request["request_type"] == "reset"
        result: TerminalResult = terminal.result
        expected_step_count = 0 if is_reset else request["expected_step"] + 1
        if result.step_count != expected_step_count:
            raise ProtocolError(
                f"terminal step_count mismatch: expected {expected_step_count}, got {result.step_count}"
            )
        if is_reset:
            expected_decision_count = 0
        else:
            if self._group is None:
                raise ProtocolError("missing prior group state at terminal")
            if self._group.substep_index + 1 == self._group.substep_count:
                expected_decision_count = self._group.group_id + 1
            elif result.classification == "halted":
                # Spec 8: an engine that cannot complete a group halts the
                # game; the unfinished group is not a completed decision.
                expected_decision_count = self._group.group_id
            else:
                raise ProtocolError("terminal interrupted a partial group")
        if result.decision_count != expected_decision_count:
            raise ProtocolError(
                f"terminal decision_count mismatch: expected {expected_decision_count}, "
                f"got {result.decision_count}"
            )
        self._game_id = None
        self._expected_step = None
        self._group = None
        self._group_actor = None
        self._decision = None
