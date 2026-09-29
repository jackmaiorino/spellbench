"""The conformance runner engine adapters are held to (the interface K2 and G consume)."""

from __future__ import annotations

import io
import json
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from spellbench import conformance, wire
from spellbench.arena import cli
from spellbench.arena.drivers import BuiltinDriver
from spellbench.conformance import CHECK_NAMES, CheckResult, ConformanceReport, check_engine, replay_engine_transcript
from spellbench.digests import card_name_domain, deck_id
from spellbench.host.engine_process import EngineProcess
from spellbench.host.game import GameResult

TESTS = Path(__file__).resolve().parent
FAKE = [sys.executable, str(TESTS / "fake_v2_engine.py")]
HOSTILE = [sys.executable, str(TESTS / "hostile_v2_engine.py")]
# Task 32's checks, in the plan's order.
PLAN_CHECKS = ["hello", "protocol_mismatch", "malformed_json", "malformed_request", "malformed_request_non_object",
               "unsupported_rule", "game_id_reuse", "never_cached", "step_check_order", "step_before_reset",
               "unsupported_format", "unsupported_deck", "unsupported_request", "game_already_active",
               "game_id_mismatch", "expected_step_mismatch", "candidate_id_out_of_range", "semantic_echo_mismatch",
               "retransmission", "game_already_terminal", "games"]
HELLO = {"request_type": "hello", "protocol": "spellbench/v2", "request_id": "h-1", "protocol_minor": 0}


def test_the_fake_engine_passes_every_check() -> None:
    report = check_engine(FAKE, format="pauper-bo1", decks=["Burn", "Elves"], games=2)
    assert report.passed, report.render()
    names = {check.name for check in report.checks}
    assert {"hello", "protocol_mismatch", "malformed_json", "malformed_request_non_object", "unsupported_rule",
            "game_id_reuse", "never_cached", "step_check_order", "retransmission", "game_already_terminal", "games"} <= names
    assert [check.name for check in report.checks] == list(CHECK_NAMES) == PLAN_CHECKS
    assert report.render().split("\n") == [f"PASS {name}" for name in PLAN_CHECKS]


def test_replay_sends_a_string_row_as_its_raw_line(tmp_path: Path) -> None:
    engine = EngineProcess(FAKE, timeout_s=30)
    try:
        hello = {"request_type": "hello", "protocol": "spellbench/v2", "request_id": "h-1", "protocol_minor": 0}
        hello_ok, error = engine.send_raw(hello), engine.send_line(b"{not json")
    finally:
        engine.close()
    assert error["error"]["code"] == "malformed_json"
    rows = [("host_to_engine", hello), ("engine_to_host", hello_ok), ("host_to_engine", "{not json"), ("engine_to_host", error)]
    path = tmp_path / "raw.transcript.jsonl"
    path.write_bytes(b"".join(wire.canonical_json_line({"dir": direction, "message": message}) for direction, message in rows))
    assert replay_engine_transcript(FAKE, path) == []     # sent as the JSON string '"{not json"' it would be malformed_request (R3-11)


def test_a_hostile_engine_fails_the_games_check_with_its_rule() -> None:
    report = check_engine([sys.executable, str(TESTS / "hostile_v2_engine.py"), "stale-reference"], format="pauper-bo1", decks=["Burn"], games=1)
    failed = {check.name: check.detail for check in report.checks if not check.passed}
    assert "games" in failed and "host_validator:V4" in failed["games"]
    assert set(failed) == {"games"}                        # the fault is in the seat decision, which only the games validate
    assert "game 1 of 1 (Burn, first as p0 against uniform): halted host_validator:V4: " in failed["games"]


def test_the_cli(capsys) -> None:
    assert cli.main(["conformance", "engine", "--format", "pauper-bo1", "--deck", "Burn", "--games", "1", "--", *FAKE]) == 0
    out = capsys.readouterr().out
    assert "PASS games" in out
    assert out.split("\n") == [f"PASS {name}" for name in PLAN_CHECKS] + [""]


# ---------------------------------------------------------------------------
# Broken engines: the fake engine with one rule broken, each failing the check that holds the rule
# ---------------------------------------------------------------------------

PATCHED = '''\
import dataclasses, json, os, re, sys
sys.path.insert(0, {tests!r})
import fake_v2_engine
from fake_v2_engine import _Engine, _error
from spellbench import wire
import spellbench.messages as messages


def parsed(line):
    try:
        value = json.loads(line)
    except Exception:
        return None
    return value if isinstance(value, dict) else None


_handle = _Engine.handle
_answer_reset = _Engine._answer_reset
_answer_step = _Engine._answer_step
_respond = _Engine._respond
_read_line = wire.read_line

{patch}

sys.exit(fake_v2_engine.serve(sys.argv[1:]))
'''


def patched(tmp_path: Path, patch: str, *args: str) -> list[str]:
    """The fake engine with one behavior changed by ``patch`` (source run before it serves), then ``args``."""
    script = tmp_path / "patched_engine.py"
    script.write_text(PATCHED.format(tests=str(TESTS), patch=textwrap.dedent(patch)), encoding="utf-8")
    return [sys.executable, str(script), *args]


def only(argv: list[str], name: str, *, format: str = "pauper-bo1", decks: tuple[str, ...] = ("Burn",),
         timeout_s: float = 20.0) -> CheckResult:
    """The result of check ``name``, run alone against ``argv``."""
    report = check_engine(argv, format=format, decks=list(decks), games=1, timeout_s=timeout_s, only=[name])
    assert [check.name for check in report.checks] == [name]
    return report.checks[0]


def error(code: str, request_id: str) -> str:
    return f"error {code} with request_id {json.dumps(request_id)}"


def expected(label: str, wanted: str, got: str) -> str:
    return f"{label}: expected {wanted}, got {got}"


def answer(kind: str, request_id: str) -> str:
    return f"a {kind} answer with request_id {json.dumps(request_id)}"


PLAY = "a decision or a terminal"


@dataclass(frozen=True)
class Broken:
    """A fake engine that breaks one rule, the check that must fail, and the text naming the fault there."""

    check: str
    patch: str
    fragment: str
    args: tuple[str, ...] = ()


def _step_patch(body: str) -> str:
    return "def answer_step(self, request):\n" + textwrap.indent(textwrap.dedent(body), "    ") + \
        "    return _answer_step(self, request)\n_Engine._answer_step = answer_step\n"


def _reset_patch(body: str) -> str:
    return "def answer_reset(self, request):\n" + textwrap.indent(textwrap.dedent(body), "    ") + \
        "    return _answer_reset(self, request)\n_Engine._answer_reset = answer_reset\n"


def _handle_patch(body: str) -> str:
    return "def handle(self, line):\n    value = parsed(line)\n" + textwrap.indent(textwrap.dedent(body), "    ") + \
        "    return _handle(self, line)\n_Engine.handle = handle\n"


def _non_object_patch(first_bytes: bytes) -> str:
    return _handle_patch(f"""
        if line.lstrip()[:1] and line.lstrip()[:1] in {first_bytes!r}:
            return _error("", "malformed_json", "not an object")
    """)


# Request ids in each check: "h-1" is the process's first request (its hello; in protocol_mismatch the hello of
# another protocol), then one per request in the check's order.
BROKEN: dict[str, Broken] = {
    # hello (spec 9.1)
    "hello-log-line": Broken("hello", """
        sys.stdout.buffer.write(b"loading the card pool\\n")
        sys.stdout.buffer.flush()
    """, "hello: the answer is not strict JSON (line is not strict JSON: Expecting value: line 1 column 1 (char 0)): b'loading the card pool'"),
    "hello-unknown-field": Broken("hello", """
        _answer_hello = _Engine._answer_hello
        def answer_hello(self, request):
            message = json.loads(_answer_hello(self, request))
            message["x_debug"] = 1
            return wire.canonical_json_line(message)
        _Engine._answer_hello = answer_hello
    """, "hello: expected a hello_ok, but the answer is invalid: invalid hello_ok from engine: hello_ok: fields mismatch: missing=[] extra=['x_debug']"),
    # protocol_mismatch (spec 4.1)
    "protocol-malformed": Broken("protocol_mismatch", _handle_patch("""
        if value is not None and value.get("protocol") == "spellbench/v1":
            return _error(value["request_id"], "malformed_request", "unsupported protocol")
    """), expected('a hello with protocol "spellbench/v1" before any hello', error("protocol_mismatch", "h-1"),
                   error("malformed_request", "h-1"))),
    "protocol-hello-only": Broken("protocol_mismatch", _handle_patch("""
        if value is not None and value.get("request_type") != "hello" and value.get("protocol") == "spellbench/v1":
            line = wire.canonical_json_dumps({**value, "protocol": "spellbench/v2"})
    """), expected('a reset with protocol "spellbench/v1"', error("protocol_mismatch", "h-3"), answer("decision", "h-3"))),
    # malformed_json (spec 2, 4.1, 9.8)
    "json-wrong-request-id": Broken("malformed_json", """
        def handle(self, line):
            answer = _handle(self, line)
            message = json.loads(answer)
            if message.get("error", {}).get("code") == "malformed_json":
                message["request_id"] = "h-0"
                return wire.canonical_json_line(message)
            return answer
        _Engine.handle = handle
    """, expected("a line that is not JSON", error("malformed_json", ""), error("malformed_json", "h-0"))),
    "json-duplicate-key": Broken("malformed_json", "wire._reject_duplicate_keys = dict",
                                 expected("a duplicate key", error("malformed_json", ""), answer("hello_ok", "h-2"))),
    "json-fraction": Broken("malformed_json", """
        _reject_float = wire._reject_float
        wire._reject_float = lambda text: float(text) if "." in text else _reject_float(text)
    """, expected("a number with a fraction", error("malformed_json", ""), error("malformed_request", "h-3"))),
    "json-exponent": Broken("malformed_json", """
        _reject_float = wire._reject_float
        wire._reject_float = lambda text: int(float(text)) if "e" in text.lower() and "." not in text else _reject_float(text)
    """, expected("a number with an exponent", error("malformed_json", ""), answer("hello_ok", "h-4"))),
    "json-big-integer": Broken("malformed_json", "wire._parse_int = int",
                               expected("an integer beyond 2^53 - 1", error("malformed_json", ""), error("malformed_request", "h-5"))),
    "json-deep": Broken("malformed_json", "wire.MAX_NESTING = 10000",
                        expected("nesting deeper than 64 levels", error("malformed_json", ""), error("malformed_request", "h-6"))),
    "json-invalid-utf8": Broken("malformed_json", """
        _loads = wire.strict_json_loads
        wire.strict_json_loads = lambda line: _loads(line.decode("utf-8", "replace") if isinstance(line, bytes) else line)
    """, expected("invalid UTF-8", error("malformed_json", ""), answer("hello_ok", "h-7\ufffd"))),
    "json-lone-surrogate": Broken("malformed_json", r"""
        _loads = wire.strict_json_loads
        wire.strict_json_loads = lambda line: _loads(re.sub(rb"\\u[dD][89a-fA-F][0-9a-fA-F]{2}", rb"\\ufffd", line))
    """, expected("an unpaired surrogate escape", error("malformed_json", ""), answer("hello_ok", "h-8\ufffd"))),
    "json-long-line-read": Broken("malformed_json",
                                  "wire.read_line = lambda stream, max_line_bytes=16 * 2**20: _read_line(stream, max_line_bytes=max_line_bytes)",
                                  expected("a line over 8 MiB", error("malformed_json", ""), error("malformed_request", "h-9"))),
    "json-dies-after-long-line": Broken("malformed_json", """
        over = []
        def read_line(stream, max_line_bytes=wire.MAX_LINE_BYTES):
            if over:
                return None
            try:
                return _read_line(stream, max_line_bytes=max_line_bytes)
            except wire.LineTooLongError:
                over.append(True)
                raise
        wire.read_line = read_line
    """, "the next request after the line over 8 MiB: the engine process failed: "),
    # malformed_request (spec 4.1, 4.2, 9.8)
    "request-unknown-field": Broken("malformed_request", """
        def _object(value, fields, context):
            checked = messages.as_object(value, context)
            missing = [name for name in fields if name not in checked]
            if missing:
                messages.fail(context, f"missing fields {missing}")
            return checked
        messages._object = _object
    """, expected("an unknown field", error("malformed_request", "h-2"), answer("hello_ok", "h-2"))),
    "request-unknown-rules-field": Broken("malformed_request", """
        _check = messages.Rules._check
        messages.Rules._check = staticmethod(
            lambda value, context: _check({key: item for key, item in value.items() if key in messages._RULES_FIELDS}, context))
    """, expected("an unknown field in reset.rules", error("malformed_request", "h-3"), answer("decision", "h-3"))),
    "request-unknown-type": Broken("malformed_request", _handle_patch("""
        known = ("hello", "reset", "step", "validate_deck", "probe_resample")
        if value is not None and isinstance(value.get("request_type"), str) and value["request_type"] not in known:
            return _error(value["request_id"], "unsupported_request", "no such request")
    """), expected("an unknown request_type", error("malformed_request", "h-4"), error("unsupported_request", "h-4"))),
    "request-missing-protocol": Broken("malformed_request", _handle_patch("""
        if value is not None and "protocol" not in value and isinstance(value.get("request_id"), str):
            return _error(value["request_id"], "protocol_mismatch", "no protocol")
    """), expected("a missing protocol", error("malformed_request", "h-5"), error("protocol_mismatch", "h-5"))),
    "request-protocol-not-a-string": Broken("malformed_request", _handle_patch("""
        if value is not None and "protocol" in value and not isinstance(value["protocol"], str):
            return _error(value["request_id"], "protocol_mismatch", "protocol is not a string")
    """), expected("a protocol that is not a string", error("malformed_request", "h-6"), error("protocol_mismatch", "h-6"))),
    "request-missing-request-id": Broken("malformed_request", _handle_patch("""
        if value is not None and "request_id" not in value:
            return wire.canonical_json_line({"response_type": "error", "protocol": "spellbench/v2", "request_id": None,
                                             "error": {"code": "malformed_request", "message": "no request_id"}})
    """), expected("a missing request_id", error("malformed_request", ""),
                   "an invalid error response (error.request_id: must be a string, got NoneType)")),
    "request-id-not-a-string": Broken("malformed_request", _handle_patch("""
        if value is not None and "request_id" in value and not isinstance(value["request_id"], str):
            return _error(json.dumps(value["request_id"]), "malformed_request", "request_id is not a string")
    """), expected("a request_id that is not a string", error("malformed_request", ""), error("malformed_request", "7"))),
    "request-missing-field": Broken("malformed_request", _handle_patch("""
        if value is not None and value.get("request_type") == "hello" and "protocol_minor" not in value:
            line = wire.canonical_json_dumps({**value, "protocol_minor": 0})
    """), expected("a missing field", error("malformed_request", "h-7"), answer("hello_ok", "h-7"))),
    "request-mistyped-field": Broken("malformed_request", _handle_patch("""
        if value is not None and isinstance(value.get("protocol_minor"), str) and value["protocol_minor"].isdigit():
            line = wire.canonical_json_dumps({**value, "protocol_minor": int(value["protocol_minor"])})
    """), expected("a mistyped field", error("malformed_request", "h-8"), answer("hello_ok", "h-8"))),
    "request-short-line-reader": Broken("malformed_request",
                                        "wire.read_line = lambda stream, max_line_bytes=64 * 1024: _read_line(stream, max_line_bytes=max_line_bytes)",
                                        expected("an unknown field on a line of 8 MiB minus 16 bytes", error("malformed_request", "h-9"),
                                                 error("malformed_json", ""))),
    "request-shallow-nesting": Broken("malformed_request", "wire.MAX_NESTING = 32",
                                      expected("an unknown field at a nesting depth of 64", error("malformed_request", "h-10"),
                                               error("malformed_json", ""))),
    # malformed_request_non_object (spec 9.8; R1-3)
    "non-object-array": Broken("malformed_request_non_object", _non_object_patch(b"["),
                               expected("the line [1,2]", error("malformed_request", ""), error("malformed_json", ""))),
    "non-object-string": Broken("malformed_request_non_object", _non_object_patch(b'"'),
                                expected('the line "spellbench/v2"', error("malformed_request", ""), error("malformed_json", ""))),
    "non-object-number": Broken("malformed_request_non_object", _non_object_patch(b"0123456789-"),
                                expected("the line 42", error("malformed_request", ""), error("malformed_json", ""))),
    "non-object-null": Broken("malformed_request_non_object", _non_object_patch(b"n"),
                              expected("the line null", error("malformed_request", ""), error("malformed_json", ""))),
    # unsupported_rule (spec 9.2; R3-10)
    "rule-probe-accepted": Broken("unsupported_rule", _reset_patch("""
        request = dataclasses.replace(request, rules=dataclasses.replace(request.rules, probe=False))
    """), expected("a reset with rules.probe true", error("unsupported_rule", "h-2"), answer("decision", "h-2"))),
    "rule-probe-malformed": Broken("unsupported_rule", _reset_patch("""
        if request.rules.probe:
            return _error(request.request_id, "malformed_request", "the probe is reserved")
    """), expected("a reset with rules.probe true", error("unsupported_rule", "h-2"), error("malformed_request", "h-2"))),
    "rule-extension-accepted": Broken("unsupported_rule", _reset_patch("""
        request = dataclasses.replace(request, rules=dataclasses.replace(request.rules, extensions=()))
    """), expected("a reset enabling the undeclared extension x_spellbench_conformance_undeclared",
                   error("unsupported_rule", "h-3"), answer("decision", "h-3"))),
    "rule-mulligan-accepted": Broken("unsupported_rule", _reset_patch("""
        request = dataclasses.replace(request, rules=dataclasses.replace(request.rules, mulligan="none"))
    """), expected('a reset with rules.mulligan "london", outside rules_supported', error("unsupported_rule", "h-4"),
                   answer("decision", "h-4"))),
    "rule-starting-player-accepted": Broken("unsupported_rule", _reset_patch("""
        rules = dataclasses.replace(request.rules, starting_player="host_assigned", starting_seat="p0")
        request = dataclasses.replace(request, rules=rules)
    """), expected('a reset with rules.starting_player "toss_winner_chooses", outside rules_supported',
                   error("unsupported_rule", "h-5"), answer("decision", "h-5"))),
    # game_id_reuse (spec 9.2)
    "reuse-accepted": Broken("game_id_reuse", _reset_patch("""
        self._used_game_ids.clear()
    """), expected("a reset reusing the finished game's game_id", error("malformed_request", "h-7"), answer("decision", "h-7"))),
    "reuse-refuses-every-second-game": Broken("game_id_reuse", _reset_patch("""
        if self._used_game_ids:
            return _error(request.request_id, "malformed_request", "one game per process")
    """), expected("a reset with a fresh game_id after that", PLAY, error("malformed_request", "h-8"))),
    # never_cached (spec 4.1)
    "cached-parse-failure": Broken("never_cached", """
        failed = {}
        def handle(self, line):
            value = parsed(line)
            request_id = value.get("request_id") if value is not None else None
            if isinstance(request_id, str) and request_id in failed:
                return failed[request_id]
            answer = _handle(self, line)
            if isinstance(request_id, str) and b'"malformed_request"' in answer:
                failed[request_id] = answer
            return answer
        _Engine.handle = handle
    """, expected("a valid reset under the request_id of a reset that failed parsing", PLAY, error("malformed_request", "h-2"))),
    "parse-failure-reserves-its-id": Broken("never_cached", """
        failed = {}
        def handle(self, line):
            value = parsed(line)
            request_id = value.get("request_id") if value is not None else None
            if isinstance(request_id, str) and request_id in failed and failed[request_id] != line:
                return _error(request_id, "request_id_reuse_mismatch", "this request_id was used with another payload")
            answer = _handle(self, line)
            if isinstance(request_id, str) and b'"malformed_request"' in answer:
                failed[request_id] = line
            return answer
        _Engine.handle = handle
    """, expected("a valid reset under the request_id of a reset that failed parsing", PLAY,
                  error("request_id_reuse_mismatch", "h-2"))),
    "cached-step-parse-failure": Broken("never_cached", """
        failed = {}
        def handle(self, line):
            value = parsed(line)
            step = value is not None and value.get("request_type") == "step"
            request_id = value.get("request_id") if value is not None else None
            if step and request_id in failed:
                return failed[request_id]
            answer = _handle(self, line)
            if step and b'"malformed_request"' in answer:
                failed[request_id] = answer
            return answer
        _Engine.handle = handle
    """, expected("a valid step under the request_id of a step that failed parsing", PLAY, error("malformed_request", "h-3"))),
    # step_check_order (spec 9.4; R1-20)
    "order-expected-step-before-game-id": Broken("step_check_order", _step_patch("""
        game = self._game
        if game is not None and not game.over and request.expected_step != game.step:
            return _error(request.request_id, "expected_step_mismatch", "wrong step")
    """), expected("a step naming another game with a wrong expected_step", error("game_id_mismatch", "h-4"),
                   error("expected_step_mismatch", "h-4"))),
    "order-range-before-expected-step": Broken("step_check_order", _step_patch("""
        game = self._game
        if game is not None and game.pending is not None and request.selection.candidate_id >= len(game.pending.semantics):
            return _error(request.request_id, "candidate_id_out_of_range", "no such candidate")
    """), expected("a step with a wrong expected_step and an out-of-range candidate_id", error("expected_step_mismatch", "h-5"),
                   error("candidate_id_out_of_range", "h-5"))),
    "order-terminal-before-game-id": Broken("step_check_order", _step_patch("""
        if self._game is not None and self._game.over:
            return _error(request.request_id, "game_already_terminal", "over")
    """), expected("after the terminal, a step naming another game", error("game_id_mismatch", "h-10"),
                   error("game_already_terminal", "h-10"))),
    "order-expected-step-before-terminal": Broken("step_check_order", _step_patch("""
        game = self._game
        if game is not None and game.over and request.game_id == game.game_id and request.expected_step != game.step:
            return _error(request.request_id, "expected_step_mismatch", "wrong step")
    """), expected("after the terminal, a step with a wrong expected_step", error("game_already_terminal", "h-11"),
                   error("expected_step_mismatch", "h-11"))),
    "order-game-id-before-reset": Broken("step_check_order", _step_patch("""
        if self._game is None:
            return _error(request.request_id, "game_id_mismatch", "no such game")
    """), expected("before any reset, a step naming a game with a wrong expected_step", error("step_before_reset", "h-2"),
                   error("game_id_mismatch", "h-2"))),
    # step_before_reset (spec 9.4, 9.8)
    "before-reset-game-id": Broken("step_before_reset", _step_patch("""
        if self._game is None:
            return _error(request.request_id, "game_id_mismatch", "no such game")
    """), expected("a step before any reset", error("step_before_reset", "h-2"), error("game_id_mismatch", "h-2"))),
    "before-reset-refused-reset-counts": Broken("step_before_reset", _reset_patch("""
        self.reset_seen = True
    """) + _step_patch("""
        if self._game is None and getattr(self, "reset_seen", False):
            return _error(request.request_id, "game_id_mismatch", "the game that was reset")
    """), expected("a step after a refused reset", error("step_before_reset", "h-4"), error("game_id_mismatch", "h-4"))),
    "before-reset-probe-refused": Broken("step_before_reset", """
        _probe = _Engine._answer_probe_resample
        def answer_probe(self, request):
            if self._game is None:
                return _error(request["request_id"], "probe_refused", "no probe game")
            return _probe(self, request)
        _Engine._answer_probe_resample = answer_probe
    """, expected("a probe_resample before any reset", error("step_before_reset", "h-3"), error("probe_refused", "h-3")),
        ("--probe",)),
    # unsupported_format (spec 9.2)
    "format-malformed": Broken("unsupported_format", _reset_patch("""
        if request.format not in fake_v2_engine.FORMATS:
            return _error(request.request_id, "malformed_request", "unknown format")
    """), expected('a reset with format "spellbench-conformance-no-such-format"', error("unsupported_format", "h-2"),
                   error("malformed_request", "h-2"))),
    "format-accepted": Broken("unsupported_format", _reset_patch("""
        request = dataclasses.replace(request, format="pauper-bo1")
    """), expected('a reset with format "spellbench-conformance-no-such-format"', error("unsupported_format", "h-2"),
                   answer("decision", "h-2"))),
    # unsupported_deck (spec 9.2)
    "deck-malformed": Broken("unsupported_deck", _reset_patch("""
        if any(self._refusal(deck.catalog_id, deck.decklist) is not None for deck in request.seats):
            return _error(request.request_id, "malformed_request", "no such deck")
    """), expected('a reset with the unknown catalog_id "spellbench-conformance-no-such-deck" in seat p0',
                   error("unsupported_deck", "h-2"), error("malformed_request", "h-2"))),
    "deck-p1-unchecked": Broken("unsupported_deck", _reset_patch("""
        if request.seats[1].catalog_id is not None and request.seats[1].catalog_id not in self._decks:
            request = dataclasses.replace(request, seats=(request.seats[0], request.seats[0]))
    """), expected('a reset with the unknown catalog_id "spellbench-conformance-no-such-deck" in seat p1',
                   error("unsupported_deck", "h-3"), answer("decision", "h-3"))),
    "deck-decklist-substituted": Broken("unsupported_deck", _reset_patch("""
        burn = messages.WireDeck(fake_v2_engine.deck_id(fake_v2_engine.SCORING_DECKLIST), catalog_id="Burn")
        request = dataclasses.replace(request, seats=tuple(burn if deck.decklist is not None else deck for deck in request.seats))
    """), expected('a reset whose p0 deck is a decklist of the made-up card "Spellbench Conformance No Such Card"',
                   error("unsupported_deck", "h-4"), answer("decision", "h-4"))),
    # unsupported_request (spec 9.7)
    "probe-malformed": Broken("unsupported_request", """
        _Engine._answer_probe_resample = lambda self, request: _error(request["request_id"], "malformed_request", "what is this")
    """, expected("a probe_resample during a game", error("unsupported_request", "h-3"), error("malformed_request", "h-3"))),
    "probe-engine-says-unsupported": Broken("unsupported_request", """
        _probe = _Engine._answer_probe_resample
        def answer_probe(self, request):
            self._probe = False
            return _probe(self, request)
        _Engine._answer_probe_resample = answer_probe
    """, expected("a probe_resample during a game", error("probe_refused", "h-3"), error("unsupported_request", "h-3")),
        ("--probe",)),
    # game_already_active (spec 9.2)
    "active-replaced": Broken("game_already_active", _reset_patch("""
        self._game = None
    """), expected("a reset while a game is active", error("game_already_active", "h-3"), answer("decision", "h-3"))),
    "active-refusal-ends-the-game": Broken("game_already_active", """
        def answer_reset(self, request):
            answer = _answer_reset(self, request)
            if b'"game_already_active"' in answer:
                self._game.over = True
            return answer
        _Engine._answer_reset = answer_reset
    """, expected("the pending decision, answered after that", PLAY, error("game_already_terminal", "h-4"))),
    # game_id_mismatch (spec 9.4)
    "game-id-ignored": Broken("game_id_mismatch", _step_patch("""
        if self._game is not None:
            request = dataclasses.replace(request, game_id=self._game.game_id)
    """), expected("a step naming another game", error("game_id_mismatch", "h-3"), answer("decision", "h-3"))),
    # expected_step_mismatch (spec 9.4)
    "expected-step-ignored": Broken("expected_step_mismatch", _step_patch("""
        if self._game is not None:
            request = dataclasses.replace(request, expected_step=self._game.step)
    """), expected("a step with an expected_step ahead of the pending decision", error("expected_step_mismatch", "h-3"),
                   answer("decision", "h-3"))),
    "expected-step-stale-accepted": Broken("expected_step_mismatch", _step_patch("""
        if self._game is not None and request.expected_step < self._game.step:
            request = dataclasses.replace(request, expected_step=self._game.step)
    """), expected("a step with the stale expected_step 0", error("expected_step_mismatch", "h-5"), answer("decision", "h-5"))),
    # candidate_id_out_of_range (spec 9.4)
    "candidate-wraps": Broken("candidate_id_out_of_range", _step_patch("""
        game = self._game
        if game is not None and game.pending is not None:
            count = len(game.pending.semantics)
            selection = messages.Selection(request.selection.candidate_id % count, request.selection.semantic_echo)
            request = dataclasses.replace(request, selection=selection)
    """), expected("a step with candidate_id 2, past the 2 candidates", error("candidate_id_out_of_range", "h-3"),
                   answer("decision", "h-3"))),
    "candidate-signed-32-bit": Broken("candidate_id_out_of_range", _step_patch("""
        game = self._game
        if game is not None and game.pending is not None and request.selection.candidate_id >= 2 ** 31:
            if wire.canonical_json_dumps(request.selection.semantic_echo) != game.pending.semantics[-1]:
                return _error(request.request_id, "semantic_echo_mismatch", "the echo differs from the last candidate")
    """), expected("a step with candidate_id 4294967295, past the 2 candidates", error("candidate_id_out_of_range", "h-4"),
                   error("semantic_echo_mismatch", "h-4"))),
    # semantic_echo_mismatch (spec 9.4)
    "echo-ignored": Broken("semantic_echo_mismatch", _step_patch("""
        game = self._game
        if game is not None and game.pending is not None and request.selection.candidate_id < len(game.pending.semantics):
            echo = json.loads(game.pending.semantics[request.selection.candidate_id])
            request = dataclasses.replace(request, selection=messages.Selection(request.selection.candidate_id, echo))
    """), expected("a step echoing another candidate's semantic", error("semantic_echo_mismatch", "h-3"),
                   answer("decision", "h-3"))),
    # retransmission (spec 4.1)
    "retransmission-not-cached": Broken("retransmission", """
        def handle(self, line):
            self._cache = None
            return _handle(self, line)
        _Engine.handle = handle
    """, "the reset sent again byte for byte: expected the first answer again, got " + error("malformed_request", "h-2")),
    "reuse-answered-from-the-cache": Broken("retransmission", _handle_patch("""
        if value is not None and self._cache is not None and self._cache[0] == value.get("request_id"):
            return self._cache[2]
    """), expected("the reset changed under the same request_id", error("request_id_reuse_mismatch", "h-2"),
                   answer("decision", "h-2"))),
    "reuse-played-as-new": Broken("retransmission", _handle_patch("""
        if value is not None and self._cache is not None and self._cache[0] == value.get("request_id") and self._cache[1] != line:
            self._cache = None
    """), expected("the reset changed under the same request_id", error("request_id_reuse_mismatch", "h-2"),
                   error("malformed_request", "h-2"))),                  # replayed as a reset, so its game_id is reused
    "retransmitted-step-applied-again": Broken("retransmission", _handle_patch("""
        if (value is not None and value.get("request_type") == "step" and self._cache is not None
                and self._cache[0] == value.get("request_id") and self._cache[1] == line and self._game.pending is not None):
            self._game.answer(0)
    """), expected("the next step", PLAY, error("expected_step_mismatch", "h-4"))),
    # game_already_terminal (spec 9.4)
    "terminal-forgotten": Broken("game_already_terminal", """
        def respond(self, request_id, result):
            answer = _respond(self, request_id, result)
            if self._game is not None and self._game.over:
                self._game = None
            return answer
        _Engine._respond = respond
    """, expected("a step after the terminal", error("game_already_terminal", "h-7"), error("step_before_reset", "h-7"))),
}


def _refused_step_still_counts(condition: str) -> str:
    """A step refused under ``condition`` (Python over ``request`` and ``game``) still moves the game on: a side effect."""
    return f"""
def answer_step(self, request):
    answer = _answer_step(self, request)
    game = self._game
    if b'"response_type":"error"' in answer and game is not None and game.pending is not None and ({condition}):
        game.answer(0)
    return answer
_Engine._answer_step = answer_step
"""


def _renumbered(field: str, value: str, condition: str) -> str:
    """Decisions whose ``field`` becomes ``value`` (Python) when ``condition`` holds for ``message``."""
    return f"""
def respond(self, request_id, result):
    message = json.loads(_respond(self, request_id, result))
    if message.get("response_type") == "decision" and ({condition}):
        message[{field!r}] = {value}
    return wire.canonical_json_line(message)
_Engine._respond = respond
"""


BROKEN.update({
    # the follow-up of each fault: the pending decision is still answered as usual (spec 9.4: an error has no effect)
    "game-id-refusal-moves-on": Broken("game_id_mismatch", _refused_step_still_counts("True"),
                                       expected("the pending decision, answered after that", PLAY,
                                                error("expected_step_mismatch", "h-4"))),
    "ahead-refusal-moves-on": Broken("expected_step_mismatch", _refused_step_still_counts("request.expected_step > game.step"),
                                     expected("the pending decision, answered after that", PLAY,
                                              error("expected_step_mismatch", "h-4"))),
    "stale-refusal-moves-on": Broken("expected_step_mismatch", _refused_step_still_counts("request.expected_step < game.step"),
                                     expected("the next decision, answered after that", PLAY,
                                              error("expected_step_mismatch", "h-6"))),
    "range-refusal-moves-on": Broken("candidate_id_out_of_range",
                                     _refused_step_still_counts("request.selection.candidate_id >= 2 ** 31"),
                                     expected("the pending decision, answered after that", PLAY,
                                              error("expected_step_mismatch", "h-5"))),
    "echo-refusal-moves-on": Broken("semantic_echo_mismatch", _refused_step_still_counts("True"),
                                    expected("the pending decision, answered after that", PLAY,
                                             error("expected_step_mismatch", "h-4"))),
    # retransmission of the step alone, and the binding of the answers it reads itself (spec 4.1, 9.3)
    "step-retransmission-played-again": Broken("retransmission", _handle_patch("""
        if value is not None and value.get("request_type") == "step":
            self._cache = None
    """), "the step sent again byte for byte: expected the first answer again, got " + error("expected_step_mismatch", "h-3")
        + """ ("the pending decision's step is 1"); the first difference is at $.error: expected (absent), got """),
    "retransmission-answer-differs": Broken("retransmission", _handle_patch("""
        if value is not None and self._cache is not None and self._cache[:2] == (value.get("request_id"), line):
            message = json.loads(self._cache[2])
            message["seat_decision"]["candidates"][0]["display_text"] = "Pass again"
            return wire.canonical_json_line(message)
    """), 'the reset sent again byte for byte: expected the first answer again, got ' + answer("decision", "h-2")
        + '; the first difference is at $.seat_decision.candidates[0].display_text: expected null, got "Pass again"'),
    "step-reuse-answered-from-the-cache": Broken("retransmission", _handle_patch("""
        if (value is not None and value.get("request_type") == "step" and self._cache is not None
                and self._cache[0] == value.get("request_id")):
            return self._cache[2]
    """), expected("the step changed under the same request_id", error("request_id_reuse_mismatch", "h-3"),
                   answer("decision", "h-3"))),
    "retransmission-step-renumbered": Broken("retransmission", _renumbered("step", "2", 'message["step"] == 1'),
                                             "the step: the decision has step 2, not 1 (spec 9.3)"),
    "retransmission-game-renamed": Broken("retransmission", _renumbered("game_id", '"g-renamed"', "True"),
                                          'the reset: the decision names game "g-renamed", not "g-'),
    "retransmission-request-id": Broken("retransmission", _renumbered("request_id", '"h-0"', "True"),
                                        'the reset: the decision answers request_id "h-0", not "h-2" (spec 4.1)'),
    "retransmission-no-provenance": Broken("retransmission", """
        def respond(self, request_id, result):
            message = json.loads(_respond(self, request_id, result))
            message.pop("provenance")
            return wire.canonical_json_line(message)
        _Engine._respond = respond
    """, "the reset: the decision is invalid: decision: fields mismatch: missing=['provenance'] extra=[]"),
    # answers the runner cannot read at all
    "protocol-answered-with-an-empty-object": Broken("protocol_mismatch", _handle_patch("""
        if value is not None and value.get("protocol") == "spellbench/v1":
            return b"{}\\n"
    """), expected('a hello with protocol "spellbench/v1" before any hello', error("protocol_mismatch", "h-1"),
                   "an answer without a response_type: {}")),
    "hello-answered-with-a-long-line": Broken("hello", """
        _Engine._answer_hello = lambda self, request: b"x" * (9 * 2**20) + b"\\n"
    """, "hello: the answer is a line over 8 MiB (spec 2)"),
})


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_a_broken_engine_fails_the_check_of_its_rule(tmp_path: Path, case: str) -> None:
    broken = BROKEN[case]
    result = only(patched(tmp_path, broken.patch, *broken.args), broken.check)
    assert not result.passed
    assert broken.fragment in result.detail, result.detail


def test_every_protocol_check_has_a_broken_engine() -> None:
    assert {broken.check for broken in BROKEN.values()} == set(CHECK_NAMES) - {"games"}


def test_the_hello_check_names_a_format_or_deck_the_engine_lacks() -> None:
    assert only(FAKE, "hello", format="pauper-bo3").detail == \
        "format 'pauper-bo3' is not in hello_ok.formats ['pauper-bo1'] (spec 9.1)"
    assert only(FAKE, "hello", decks=("Burn", "Nope", "Elves", "Nor")).detail == \
        "hello_ok.catalog lacks 'Nope', 'Nor' (spec 9.1, 12.1)"
    assert only(FAKE, "game_already_active", decks=("Nope",)).detail == \
        "deck 'Nope' is not in hello_ok.catalog, so no game can be reset (spec 9.2)"


def test_an_engine_with_the_probe_is_held_to_probe_refused() -> None:
    report = check_engine([*FAKE, "--probe"], format="pauper-bo1", decks=["Burn"], games=1,
                          only=["unsupported_request", "step_before_reset", "unsupported_rule"])
    assert report.passed, report.render()
    assert [check.name for check in report.checks] == ["unsupported_rule", "step_before_reset", "unsupported_request"]


def test_an_engine_with_the_probe_is_sent_no_probe_reset(tmp_path: Path) -> None:
    """``probe: true`` is unsupported only for an engine without the probe (spec 9.2): this one would play it."""
    engine = patched(tmp_path, BROKEN["rule-probe-accepted"].patch, "--probe")
    assert only(engine, "unsupported_rule").passed


# The fake engine's own games pose no pregame decision, so it refuses london and toss for them (spec 7.6); this one
# plays every rule it declares, so unsupported_rule may only probe values outside rules_supported.
PLAYS_DECLARED_RULES = """
_rule = _Engine._unsupported_rule
def unsupported_rule(self, rules, hook):
    supported = self._hello.profile.rules_supported
    if rules.mulligan in supported["mulligan"] and rules.starting_player in supported["starting_player"]:
        rules = dataclasses.replace(rules, mulligan="none", starting_player="host_assigned", starting_seat="p0")
    return _rule(self, rules, hook)
_Engine._unsupported_rule = unsupported_rule
"""


@pytest.mark.parametrize("args", [(), ("--london",), ("--toss",), ("--london", "--toss")])
def test_unsupported_rule_probes_only_values_outside_rules_supported(tmp_path: Path, args: tuple[str, ...]) -> None:
    result = only(patched(tmp_path, PLAYS_DECLARED_RULES, *args), "unsupported_rule")
    assert result.passed, result.detail


def test_the_echo_check_answers_single_candidate_decisions_until_one_offers_two(tmp_path: Path) -> None:
    first_has_one = """
        def respond(self, request_id, result):
            message = json.loads(_respond(self, request_id, result))
            if message.get("response_type") == "decision" and message["step"] == 0:
                message["seat_decision"]["candidates"] = message["seat_decision"]["candidates"][:1]
            return wire.canonical_json_line(message)
        _Engine._respond = respond
    """
    assert only(patched(tmp_path, first_has_one), "semantic_echo_mismatch").passed
    looping = only(FAKE, "semantic_echo_mismatch", decks=("Loop",))
    assert looping.detail == ("no decision offered two candidates before the game ended at step_count 2000, "
                              "so no echo could name another candidate (spec 9.4)")


def test_a_check_that_needs_a_decision_says_so_when_the_reset_ends_the_game(tmp_path: Path) -> None:
    degenerate = patched(tmp_path, _reset_patch("request = dataclasses.replace(request, max_steps=0)\n"))
    assert only(degenerate, "game_already_active").detail == (
        "a reset: the reset ended the game at once (a truncated terminal), so no decision was pending; "
        "this check needs a deck whose game poses one")
    assert only(degenerate, "game_already_terminal").passed          # a terminal from the reset is a terminal too


def test_a_game_that_runs_past_its_caps_fails_the_play_out(tmp_path: Path) -> None:
    uncapped = patched(tmp_path, _reset_patch("request = dataclasses.replace(request, max_steps=10**6, max_decisions=10**6)\n"))
    assert only(uncapped, "game_already_terminal", decks=("Loop",)).detail == \
        "the game: the game did not end within 2000 answers, its max_steps (spec 9.2)"


@pytest.mark.parametrize("change,detail", [
    ('message["seat_decision"]["candidates"] = []', "the decision at step 0 has no candidates (spec 9.3)"),
    ('message["seat_decision"]["candidates"][0].pop("semantic")',
     "the decision at step 0 has no semantic object for candidate 0 (spec 7.1)"),
])
def test_a_decision_the_runner_cannot_answer_fails_the_check(tmp_path: Path, change: str, detail: str) -> None:
    broken = patched(tmp_path, f"""
def respond(self, request_id, result):
    message = json.loads(_respond(self, request_id, result))
    if message.get("response_type") == "decision":
        {change}
    return wire.canonical_json_line(message)
_Engine._respond = respond
""")
    assert only(broken, "game_id_mismatch").detail == detail


def test_the_made_up_format_and_extension_avoid_names_the_engine_declares(tmp_path: Path) -> None:
    declares_them = patched(tmp_path, """
fake_v2_engine.FORMATS = ("pauper-bo1", "spellbench-conformance-no-such-format")
_init = _Engine.__init__
def init(self, *args, **kwargs):
    _init(self, *args, **kwargs)
    extension = messages.ExtensionDecl("x_spellbench_conformance_undeclared", False)
    profile = dataclasses.replace(self._hello.profile, extensions=(extension,))
    self._hello = dataclasses.replace(self._hello, formats=fake_v2_engine.FORMATS, profile=profile)
_Engine.__init__ = init
""")
    report = check_engine(declares_them, format="pauper-bo1", decks=["Burn"], games=1,
                          only=["unsupported_rule", "unsupported_format", "step_before_reset"])
    assert report.passed, report.render()


BURN_ID = deck_id([{"name": "Lightning Bolt", "count": 4}, {"name": "Mountain", "count": 18}])
DOMAIN = card_name_domain(["Lightning Bolt", "Mountain"])


@pytest.mark.parametrize("args,mulligan", [((), "none"), (("--london",), "london")])
def test_the_protocol_resets_carry_a_benchmarks_rules_and_caps_of_2000(tmp_path: Path, args: tuple[str, ...],
                                                                       mulligan: str) -> None:
    log = tmp_path / "lines.log"
    engine = patched(tmp_path, PLAYS_DECLARED_RULES + LOG_PATCH.replace("LOG_PATH", repr(str(log))), *args)
    assert only(engine, "game_already_active", decks=("Burn", "Elves")).passed
    [lines] = read_log(log).values()
    resets = [json.loads(line) for line in lines[:-1] if json.loads(line)["request_type"] == "reset"]
    game_ids = [reset.pop("game_id") for reset in resets]
    secrets = [reset.pop("game_secret") for reset in resets]
    assert len(set(game_ids)) == len(set(secrets)) == 2
    assert all(len(game_id) == 18 and game_id.startswith("g-") and int(game_id[2:], 16) >= 0 for game_id in game_ids)
    assert all(len(secret) == 64 and secret == secret.lower() and int(secret, 16) >= 0 for secret in secrets)
    burn = {"deck_id": BURN_ID, "catalog_id": "Burn"}
    assert resets == [{"request_type": "reset", "protocol": "spellbench/v2", "request_id": f"h-{number}",
                       "format": "pauper-bo1", "seats": [{"seat": "p0", "deck": burn}, {"seat": "p1", "deck": burn}],
                       "rules": {"opponent_decklist": "visible", "mulligan": mulligan, "starting_player": "host_assigned",
                                 "starting_seat": "p0", "card_name_domain": DOMAIN, "extensions": [], "probe": False},
                       "max_decisions": 2000, "max_steps": 2000} for number in (2, 3)]


# ---------------------------------------------------------------------------
# The runner: fresh processes, exceptions, timeouts, the report
# ---------------------------------------------------------------------------

LOG_PATCH = r"""
TOKEN = os.urandom(8).hex().encode()
def read_line(stream, max_line_bytes=wire.MAX_LINE_BYTES):
    line = _read_line(stream, max_line_bytes=max_line_bytes)
    with open(LOG_PATH, "ab") as log:
        log.write(b"%s %s\n" % (TOKEN, b"EOF" if line is None else line[:4096].hex().encode()))
    return line
wire.read_line = read_line
"""


def logged(tmp_path: Path, log: Path, *args: str) -> list[str]:
    """The fake engine, logging each line it reads (hex, after a token naming the process) and its end of input."""
    return patched(tmp_path, LOG_PATCH.replace("LOG_PATH", repr(str(log))), *args)


def read_log(log: Path) -> dict[bytes, list[bytes]]:
    processes: dict[bytes, list[bytes]] = {}
    for entry in log.read_bytes().split(b"\n"):
        if entry:
            token, line = entry.split(b" ")
            processes.setdefault(token, []).append(line if line == b"EOF" else bytes.fromhex(line.decode("ascii")))
    return processes


def test_each_check_runs_in_a_fresh_process_that_it_closes(tmp_path: Path) -> None:
    log = tmp_path / "lines.log"
    report = check_engine(logged(tmp_path, log), format="pauper-bo1", decks=["Burn"], games=1)
    assert report.passed, report.render()
    processes = read_log(log)
    assert len(processes) == 22                  # a process per protocol check, then the games' preflight and game
    for lines in processes.values():
        assert json.loads(lines[0])["request_type"] == "hello"
        assert lines[-1] == b"EOF"               # the runner closed its input: the engine ended cleanly
        assert lines.count(b"EOF") == 1


def test_an_exception_inside_a_check_fails_only_that_check(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self, **kwargs):
        raise RuntimeError("boom\n  in a second line" + "!" * 2000)

    monkeypatch.setattr(EngineProcess, "step", boom)
    report = check_engine(FAKE, format="pauper-bo1", decks=["Burn"], games=1)
    failed = {check.name: check.detail for check in report.checks if not check.passed}
    assert set(failed) == {"game_id_reuse", "step_check_order", "game_already_active", "game_id_mismatch",
                           "expected_step_mismatch", "candidate_id_out_of_range", "semantic_echo_mismatch",
                           "game_already_terminal", "games"}
    assert set(failed.values()) == {("RuntimeError: boom in a second line" + "!" * 2000)[:997] + "..."}
    assert [check.name for check in report.checks] == PLAN_CHECKS


def test_ctrl_c_stops_the_run_after_closing_the_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "lines.log"

    def interrupt(self, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(EngineProcess, "hello", interrupt)
    with pytest.raises(KeyboardInterrupt):
        check_engine(logged(tmp_path, log), format="pauper-bo1", decks=["Burn"], games=1, only=["hello", "games"])
    assert list(read_log(log).values()) == [[b"EOF"]]          # one process, closed without a request


def silent_engine(tmp_path: Path) -> list[str]:
    """An engine that reads every request and answers none; it ends when its input closes."""
    script = tmp_path / "silent_engine.py"
    script.write_text(
        "import os, sys, threading, time\n"
        "def drain():\n"
        "    for _ in sys.stdin.buffer:\n"
        "        pass\n"
        "    os._exit(0)\n"
        "threading.Thread(target=drain, daemon=True).start()\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    return [sys.executable, str(script)]


def test_a_hung_engine_fails_every_check_within_its_timeout(tmp_path: Path) -> None:
    started = time.monotonic()
    report = check_engine(silent_engine(tmp_path), format="pauper-bo1", decks=["Burn"], games=1, timeout_s=0.3)
    assert time.monotonic() - started < 45
    details = {check.name: check.detail for check in report.checks}
    assert not any(check.passed for check in report.checks)
    assert details["protocol_mismatch"] == \
        'a hello with protocol "spellbench/v1" before any hello: no answer within 0.3 s (the request timeout)'
    for name in set(CHECK_NAMES) - {"protocol_mismatch", "games"}:
        assert details[name] == "hello: no answer within 0.3 s (the request timeout)", name
    assert details["games"].startswith("preflight: engine hello failed: timeout waiting for peer stdout")


def test_render_is_one_line_per_check() -> None:
    report = ConformanceReport((CheckResult("hello", True, "fake-v2-engine 0.2.0"),
                                CheckResult("games", False, "line one\nline two\r\n\tthree")))
    assert report.render() == "PASS hello\nFAIL games: line one line two three"
    long = ConformanceReport((CheckResult("games", False, "x" * 5000),))
    assert long.render() == "FAIL games: " + "x" * 997 + "..."
    assert not report.passed
    assert ConformanceReport((CheckResult("hello", True, ""), CheckResult("games", True, ""))).passed
    assert not ConformanceReport(()).passed


@pytest.mark.parametrize("changes", [
    {"argv": []}, {"argv": "python"}, {"argv": ["python", ""]}, {"format": ""}, {"format": 1}, {"decks": []},
    {"decks": "Burn"}, {"decks": ["Burn", "Burn"]}, {"decks": [""]}, {"games": 0}, {"games": True}, {"games": 1.0},
    {"timeout_s": 0}, {"timeout_s": -1.0}, {"timeout_s": float("inf")}, {"timeout_s": float("nan")}, {"timeout_s": True},
    {"timeout_s": 86401}, {"only": []}, {"only": "hello"}, {"only": ["hello", "no_such_check"]},
])
def test_check_engine_refuses_arguments_no_check_can_use(changes: dict) -> None:
    arguments = {"argv": FAKE, "format": "pauper-bo1", "decks": ["Burn"], "games": 1, **changes}
    with pytest.raises(ValueError):
        check_engine(arguments.pop("argv"), **arguments)


# ---------------------------------------------------------------------------
# The games check (spec 11.3, 11.5)
# ---------------------------------------------------------------------------


def test_the_games_are_first_against_uniform_seat_swapped_with_the_decks_in_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    class NamedDriver(BuiltinDriver):
        def __init__(self, spec) -> None:
            super().__init__(spec)
            self.name = spec.name

    played = []
    real = conformance.play_game

    def recording(setup, *, engine, seats):
        played.append((setup.game_index, seats["p0"].name, seats["p1"].name, setup.wire_decks[0].catalog_id,
                       setup.wire_decks[1].catalog_id, setup.game_id))
        return real(setup, engine=engine, seats=seats)

    monkeypatch.setattr(conformance, "BuiltinDriver", NamedDriver)
    monkeypatch.setattr(conformance, "play_game", recording)
    report = check_engine(FAKE, format="pauper-bo1", decks=["Burn", "Elves"], games=3, only=["games"])
    assert report.passed, report.render()
    assert [row[:5] for row in played] == [(0, "first", "uniform", "Burn", "Burn"), (1, "uniform", "first", "Burn", "Burn"),
                                           (2, "first", "uniform", "Elves", "Elves")]
    assert check_engine(FAKE, format="pauper-bo1", decks=["Burn"], games=1, only=["games"]).passed
    assert played[3][:5] == (0, "first", "uniform", "Burn", "Burn")
    assert played[3][5] != played[0][5]             # a fresh run secret: other game ids (spec 11.6)


def test_the_games_check_names_a_host_engine_fault() -> None:
    result = only([*HOSTILE, "garbage-json"], "games")
    assert result.detail.startswith("game 1 of 1 (Burn, first as p0 against uniform): halted host_engine_fault:malformed: "
                                    "the engine's answer to step 0 was not a valid protocol message")
    assert "line is not strict JSON" in result.detail      # the fault itself, from the game's diagnostics


def test_the_games_check_fails_a_forfeit_naming_its_cause(monkeypatch: pytest.MonkeyPatch) -> None:
    def forfeit(setup, *, engine, seats):
        return GameResult(outcome="p0_win", classification="forfeit", winner="p0", reason="forfeit:agent_error",
                          adjudication={"kind": "forfeit", "cause": "agent_error", "loser_seat": "p1",
                                        "detail": "the builtin bot raised during choose"},
                          step_count=1, decision_count=1, decisions_checked=2, last_selection_seat=None,
                          game_digest="sha256:" + "0" * 64, violation=None, diagnostics=())

    monkeypatch.setattr(conformance, "play_game", forfeit)
    assert only(FAKE, "games").detail == ("game 1 of 1 (Burn, first as p0 against uniform): forfeit:agent_error: "
                                          "p1 (uniform) forfeited: the builtin bot raised during choose")


@pytest.mark.parametrize("deck,ending", [("Halt", "1 halted"), ("Burn", "1 natural")])
def test_games_the_engine_itself_ends_pass(deck: str, ending: str) -> None:
    result = only(FAKE, "games", decks=(deck,))          # an engine's own halted terminal is not a host halt (spec 9.5)
    assert result.passed and result.detail == f"played 1 game: {ending}"


def test_the_games_check_fails_a_truncation_below_the_caps() -> None:
    assert only(FAKE, "games", decks=("Truncate",)).detail == (
        "game 1 of 1 (Truncate, first as p0 against uniform): halted host_validator:V3: a truncated terminal after "
        "1 answered decisions and 1 completed groups, below max_steps 100000 and max_decisions 10000")


@pytest.mark.parametrize("second_start,detail", [
    ("sys.exit(7)", "game 1 of 1 (Burn, first as p0 against uniform): hello failed: "),
    ('VERSION = "0.2.1"', "game 1 of 1 (Burn, first as p0 against uniform): engine identity drifted between processes: "),
])
def test_each_game_process_must_answer_hello_as_the_first_did(tmp_path: Path, second_start: str, detail: str) -> None:
    """Preflight starts the engine once for Burn; the game starts it again, which this engine counts (spec 11.3 V10)."""
    starts = tmp_path / "starts"
    engine = patched(tmp_path, f"""
with open({str(starts)!r}, "ab") as count:
    count.write(b"x")
VERSION = fake_v2_engine.ENGINE_VERSION
if os.path.getsize({str(starts)!r}) == 2:
    {second_start}
_init = _Engine.__init__
def init(self, *args, **kwargs):
    _init(self, *args, **kwargs)
    self._hello = dataclasses.replace(self._hello, engine=dataclasses.replace(self._hello.engine, version=VERSION))
    self._provenance = self._hello.engine.provenance()
_Engine.__init__ = init
""")
    result = only(engine, "games")
    assert result.detail.startswith(detail), result.detail
    assert starts.read_bytes() == b"xx"


def test_the_games_check_reports_a_preflight_refusal() -> None:
    result = only(FAKE, "games", decks=("Refuse",))
    assert result.detail.startswith("preflight: engine 'fake-v2-engine' '0.2.0' could not start a game with decks "
                                    "['Refuse', 'Refuse']: unsupported_deck: ")


# ---------------------------------------------------------------------------
# Replaying a golden transcript's engine rows (spec 16; Decision 7, R3-11)
# ---------------------------------------------------------------------------


def transcript(path: Path, rows: list[tuple[str, object]]) -> Path:
    path.write_bytes(b"".join(wire.canonical_json_line({"dir": direction, "message": message}) for direction, message in rows))
    return path


def canned(tmp_path: Path, answer_line: bytes) -> list[str]:
    """An engine answering every line with ``answer_line``, written as bytes (no text-mode line endings)."""
    script = tmp_path / "canned_engine.py"
    script.write_text("import sys\n"
                      "for _ in sys.stdin.buffer:\n"
                      f"    sys.stdout.buffer.write({answer_line!r} + b'\\n')\n"
                      "    sys.stdout.buffer.flush()\n", encoding="utf-8")
    return [sys.executable, str(script)]


def test_replay_sends_object_rows_as_canonical_json_and_string_rows_unchanged(tmp_path: Path) -> None:
    log = tmp_path / "lines.log"
    raw = '{not json: Lim-D\u00fbl\'s "Vault"'
    path = tmp_path / "sent.transcript.jsonl"
    path.write_bytes(json.dumps({"dir": "host_to_engine", "message": HELLO}).encode() + b"\n"       # keys unsorted, spaced
                     + b'{"dir":"engine_to_host","message":{}}\n'
                     + json.dumps({"dir": "host_to_engine", "message": raw}).encode() + b"\n"        # \u escapes in the file
                     + b'{"dir":"engine_to_host","message":{}}\n')
    replay_engine_transcript(logged(tmp_path, log), path)
    assert list(read_log(log).values()) == [[wire.canonical_json_dumps(HELLO), raw.encode("utf-8"), b"EOF"]]


def test_replay_compares_answers_as_parsed_json(tmp_path: Path) -> None:
    engine = canned(tmp_path, b'{ "b" : 1,\t"a" : [ true, null ] }')        # any layout is the engine's (spec 4.3)
    same = transcript(tmp_path / "same.transcript.jsonl", [("host_to_engine", HELLO), ("engine_to_host", {"a": [True, None], "b": 1})])
    assert replay_engine_transcript(engine, same) == []
    other = transcript(tmp_path / "other.transcript.jsonl", [("host_to_engine", HELLO), ("engine_to_host", {"a": [1, None], "b": 1})])
    assert replay_engine_transcript(engine, other) == ["line 2: the answer to hello h-1 differs at $.a[0]: expected 1, got true"]


def test_replay_names_each_answer_that_differs(tmp_path: Path) -> None:
    engine = EngineProcess(FAKE, timeout_s=30)
    try:
        hello_ok = engine.send_raw(HELLO)
    finally:
        engine.close()
    doctored = {**hello_ok, "engine": {**hello_ok["engine"], "version": "9.9.9"}}
    rows = [("host_to_agent", {"request_type": "hello"}), ("agent_to_host", {"response_type": "hello_ok"}),
            ("host_to_engine", HELLO), ("host_to_agent", {"request_type": "choose"}), ("engine_to_host", doctored),
            ("host_to_engine", "[1,2]"), ("engine_to_host", {"response_type": "error"})]
    mismatches = replay_engine_transcript(FAKE, transcript(tmp_path / "doctored.transcript.jsonl", rows))
    assert mismatches == ['line 5: the answer to hello h-1 differs at $.engine.version: expected "9.9.9", got "0.2.0"',
                          "line 7: the answer to the raw line '[1,2]' differs at $.error: expected (absent), got "
                          '{"code":"malformed_request","message":"top-level JSON value is not an object"}']


def test_replay_of_a_hung_engine_stops_at_its_timeout(tmp_path: Path) -> None:
    path = transcript(tmp_path / "hang.transcript.jsonl", [("host_to_engine", HELLO), ("engine_to_host", {})])
    started = time.monotonic()
    assert replay_engine_transcript(silent_engine(tmp_path), path, timeout_s=0.3) == \
        ["line 1: hello h-1 got no answer within 0.3 s (the request timeout)"]
    assert time.monotonic() - started < 10


def test_replay_reports_an_engine_that_cannot_start(tmp_path: Path) -> None:
    path = transcript(tmp_path / "one.transcript.jsonl", [("host_to_engine", HELLO), ("engine_to_host", {})])
    mismatches = replay_engine_transcript([str(tmp_path / "no-such-engine")], path)
    assert len(mismatches) == 1 and mismatches[0].startswith("the engine could not start: ")
    assert replay_engine_transcript([str(tmp_path / "no-such-engine")], transcript(tmp_path / "agents.transcript.jsonl", [
        ("host_to_agent", {"request_type": "hello"}), ("agent_to_host", {"response_type": "hello_ok"})])) == []


@pytest.mark.parametrize("lines", [
    [b"{not json"],
    [b'{"dir":"host_to_engine","message":{},"x":1}'],
    [b'{"dir":"host_to_bot","message":{}}'],
    [b'{"dir":"host_to_engine","message":3}', b'{"dir":"engine_to_host","message":{}}'],
    [b'{"dir":"engine_to_host","message":{}}'],
    [b'{"dir":"host_to_engine","message":{}}'],
    [b'{"dir":"host_to_engine","message":{}}', b'{"dir":"host_to_engine","message":{}}', b'{"dir":"engine_to_host","message":{}}'],
    [b'{"dir":"host_to_engine","message":"a\\nb"}', b'{"dir":"engine_to_host","message":{}}'],
])
def test_replay_refuses_a_malformed_transcript(tmp_path: Path, lines: list[bytes]) -> None:
    path = tmp_path / "bad.transcript.jsonl"
    path.write_bytes(b"\n".join(lines) + b"\n")
    with pytest.raises(ValueError):
        replay_engine_transcript(FAKE, path)


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def test_the_cli_exits_1_when_a_check_fails(tmp_path: Path, capsys) -> None:
    missing = str(tmp_path / "no-such-engine")
    assert cli.main(["conformance", "engine", "--format", "pauper-bo1", "--deck", "Burn", "--", missing]) == 1
    lines = capsys.readouterr().out.split("\n")
    assert lines[-1] == "" and len(lines) == len(PLAN_CHECKS) + 1
    for line, name in zip(lines, PLAN_CHECKS):
        assert line.startswith(f"FAIL {name}: "), line
    assert lines[0].startswith("FAIL hello: the engine could not start: ")


def test_the_cli_hands_its_options_to_check_engine(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    calls = []

    def recording(argv, **options):
        calls.append((list(argv), options))
        return ConformanceReport((CheckResult("hello", True, ""), CheckResult("games", False, "two\nlines")))

    monkeypatch.setattr(conformance, "check_engine", recording)
    assert cli.main(["conformance", "engine", "--deck", "Burn", "--format", "pauper-bo1", "--deck", "Elves", "--games", "6",
                     "--timeout-s", "2.5", "--", "engine", "--deck", "--"]) == 1
    assert calls == [(["engine", "--deck", "--"], {"format": "pauper-bo1", "decks": ["Burn", "Elves"], "games": 6,
                                                   "timeout_s": 2.5})]
    assert capsys.readouterr().out == "PASS hello\nFAIL games: two lines\n"
    calls.clear()
    monkeypatch.setattr(conformance, "check_engine",
                        lambda argv, **options: calls.append(options) or ConformanceReport((CheckResult("hello", True, ""),)))
    assert cli.main(["conformance", "engine", "--format", "f", "--deck", "d", "--", "e"]) == 0
    assert calls == [{"format": "f", "decks": ["d"]}]        # the defaults are check_engine's


@pytest.mark.parametrize("args", [
    ["conformance"],
    ["conformance", "bot", "--format", "f", "--deck", "d", "--", "e"],
    ["conformance", "engine", "--format", "f", "--deck", "d"],
    ["conformance", "engine", "--format", "f", "--deck", "d", "--"],
    ["conformance", "engine", "--deck", "d", "--", "e"],
    ["conformance", "engine", "--format", "f", "--", "e"],
    ["conformance", "engine", "--format", "f", "--format", "g", "--deck", "d", "--", "e"],
    ["conformance", "engine", "--format", "f", "--deck", "d", "--games", "0", "--", "e"],
    ["conformance", "engine", "--format", "f", "--deck", "d", "--games", "two", "--", "e"],
    ["conformance", "engine", "--format", "f", "--deck", "d", "--games", "1", "--games", "2", "--", "e"],
    ["conformance", "engine", "--format", "f", "--deck", "d", "--timeout-s", "0", "--", "e"],
    ["conformance", "engine", "--format", "f", "--deck", "d", "--timeout-s", "nan", "--", "e"],
    ["conformance", "engine", "--format", "f", "--deck", "d", "--timeout-s", "soon", "--", "e"],
    ["conformance", "engine", "--format", "f", "--deck", "d", "--seed", "1", "--", "e"],
    ["conformance", "engine", "--format", "f", "--deck", "--", "e"],
    ["conformance", "engine", "--format", "f", "--deck", "d", "--deck", "d", "--", "e"],
])
def test_the_cli_answers_a_usage_error_with_2(args: list[str], capsys) -> None:
    assert cli.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "usage: spellbench conformance engine --format FORMAT --deck CATALOG_ID" in captured.err


@pytest.mark.parametrize("option,value,error", [
    ("--games", "0", "error: games must be an integer of at least 1"),
    ("--timeout-s", "0", "error: timeout_s must be a number of seconds above 0 and at most 86400"),
    ("--timeout-s", "inf", "error: timeout_s must be a number of seconds above 0 and at most 86400"),
])
def test_the_cli_leaves_value_ranges_to_check_engine(option: str, value: str, error: str, capsys) -> None:
    assert cli.main(["conformance", "engine", "--format", "f", "--deck", "d", option, value, "--", "e"]) == 2
    assert capsys.readouterr().err.split("\n")[0] == error


def test_the_cli_escapes_what_its_output_cannot_encode(monkeypatch: pytest.MonkeyPatch) -> None:
    report = ConformanceReport((CheckResult("hello", False, "got 'h-7\ufffd' from Lim-D\u00fbl's Vault"),))
    monkeypatch.setattr(conformance, "check_engine", lambda argv, **options: report)
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252", newline="\n"))    # a Windows pipe
    assert cli.main(["conformance", "engine", "--format", "f", "--deck", "d", "--", "e"]) == 1
    sys.stdout.flush()
    assert raw.getvalue() == "FAIL hello: got 'h-7\\ufffd' from Lim-D\u00fbl's Vault\n".encode("cp1252")
