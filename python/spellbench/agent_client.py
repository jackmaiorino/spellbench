"""Host-side client for the agent role (spec section 10).

Spawns (or wraps) an agent process, performs the hello handshake, starts one
game at a time, and routes decisions through ``choose`` with selection echo
validation against the offered decision.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ._client import Peer, RoleClient
from .errors import AGENT_ERROR_CODES, AgentError, ProtocolError, ValidationError
from .models import (
    Ack,
    AgentHelloOk,
    Choice,
    ChooseRequest,
    Decision,
    Deck,
    EngineIdentity,
    ErrorResponse,
    GameOverRequest,
    GameStartRequest,
    HelloRequest,
    Selection,
    TerminalResult,
)


class AgentProcess(RoleClient):
    """A client of one agent process (one seat of one game at a time)."""

    def __init__(
        self,
        argv: Sequence[str] | None = None,
        *,
        peer: Peer | None = None,
        timeout_s: float | None = None,
    ) -> None:
        super().__init__(argv, peer=peer, timeout_s=timeout_s)
        self._hello: AgentHelloOk | None = None
        self._game_id: str | None = None

    @property
    def hello_result(self) -> AgentHelloOk | None:
        return self._hello

    @property
    def game_id(self) -> str | None:
        return self._game_id

    def hello(self, request: HelloRequest | None = None) -> AgentHelloOk:
        if self._hello is not None:
            raise ProtocolError("hello already completed for this process")
        if request is None:
            request = HelloRequest(request_id=self._next_request_id())
        self._claim_request_id(request.request_id)
        response, response_line = self._exchange(request.to_json())
        result = self._validate_response(response, request.to_json(), response_line)
        assert isinstance(result, AgentHelloOk)
        return result

    def game_start(
        self,
        request: GameStartRequest | None = None,
        *,
        game_id: str | None = None,
        seat: str | None = None,
        format: str | None = None,
        decks: Sequence[Deck | Mapping[str, Any]] | None = None,
        engine: EngineIdentity | Mapping[str, Any] | None = None,
    ) -> Ack:
        if self._hello is None:
            raise ProtocolError("game_start before hello")
        if self._game_id is not None:
            raise ProtocolError("a game is already active on this agent")
        if request is None:
            if game_id is None or seat is None or format is None or decks is None or engine is None:
                raise ProtocolError("game_start requires game_id, seat, format, decks, engine")
            normalized_decks = tuple(
                deck if isinstance(deck, Deck) else Deck.from_json(deck) for deck in decks
            )
            if len(normalized_decks) != 2:
                raise ProtocolError("game_start decks must have exactly two entries, p0 first")
            if not isinstance(engine, EngineIdentity):
                engine = EngineIdentity.from_json(engine)
            request = GameStartRequest(
                request_id=self._next_request_id(),
                game_id=game_id,
                seat=seat,
                format=format,
                decks=(normalized_decks[0], normalized_decks[1]),
                engine=engine,
            )
        self._claim_request_id(request.request_id)
        response, response_line = self._exchange(request.to_json())
        result = self._validate_response(response, request.to_json(), response_line)
        assert isinstance(result, Ack)
        return result

    def choose(self, decision: Decision) -> Selection:
        """Route one decision to the agent; returns the validated selection."""
        if self._game_id is None:
            raise ProtocolError("choose without an active game")
        if decision.game_id != self._game_id:
            raise ProtocolError("decision game_id does not match the active game")
        request = ChooseRequest(
            request_id=self._next_request_id(),
            game_id=self._game_id,
            decision=decision,
        )
        self._claim_request_id(request.request_id)
        response, response_line = self._exchange(request.to_json())
        result = self._validate_response(response, request.to_json(), response_line)
        assert isinstance(result, Selection)
        return result

    def game_over(self, terminal: TerminalResult) -> Ack:
        if self._game_id is None:
            raise ProtocolError("game_over without an active game")
        request = GameOverRequest(
            request_id=self._next_request_id(),
            game_id=self._game_id,
            terminal=terminal,
        )
        self._claim_request_id(request.request_id)
        response, response_line = self._exchange(request.to_json())
        result = self._validate_response(response, request.to_json(), response_line)
        assert isinstance(result, Ack)
        return result

    # ------------------------------------------------------------------

    def _validate_response(
        self,
        response: dict[str, Any],
        request: dict[str, Any],
        response_line: bytes,
    ) -> AgentHelloOk | Ack | Selection:
        response_type = response.get("response_type")
        if response_type == "error":
            try:
                error = ErrorResponse.from_json(response, codes=AGENT_ERROR_CODES)
            except ValidationError as exc:
                raise ProtocolError(f"invalid error response from agent: {exc}") from exc
            if error.request_id != request["request_id"]:
                raise ProtocolError("error response request_id mismatch")
            remote = AgentError(error.code, error.message)
            self._commit(request, response_line, remote)
            raise remote
        expected = {"hello": "hello_ok", "game_start": "ack", "choose": "choice", "game_over": "ack"}
        wanted = expected.get(request["request_type"])
        if wanted is None or response_type != wanted:
            raise ProtocolError(
                f"unexpected response_type from agent: {response_type!r} for {request['request_type']}"
            )
        try:
            if response_type == "hello_ok":
                hello_ok = AgentHelloOk.from_json(response)
            elif response_type == "ack":
                parsed: Ack | Choice = Ack.from_json(response)
            else:
                parsed = Choice.from_json(response)
        except ValidationError as exc:
            raise ProtocolError(f"invalid {response_type} from agent: {exc}") from exc
        if response_type == "hello_ok":
            if hello_ok.request_id != request["request_id"]:
                raise ProtocolError("hello_ok request_id mismatch")
            self._hello = hello_ok
            return self._commit(request, response_line, hello_ok)
        if parsed.request_id != request["request_id"]:
            raise ProtocolError(f"{response_type} request_id mismatch")
        if response_type == "choice":
            assert isinstance(parsed, Choice)
            selection = parsed.selection
            candidates = request["decision"]["candidates"]
            if selection.candidate_id >= len(candidates):
                raise ProtocolError("agent choice candidate_id is outside the offered candidate list")
            if selection.semantic_echo != candidates[selection.candidate_id]["semantic"]:
                raise ProtocolError("agent choice semantic_echo does not match the offered candidate")
            return self._commit(request, response_line, selection)
        assert isinstance(parsed, Ack)
        if request["request_type"] == "game_start":
            self._game_id = request["game_id"]
        elif request["request_type"] == "game_over":
            self._game_id = None
        return self._commit(request, response_line, parsed)
