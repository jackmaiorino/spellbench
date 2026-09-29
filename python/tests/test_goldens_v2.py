"""The v2 goldens: current, canonical, valid, and complete (spec 16; Decision 7).

Beyond the generator's byte check, each golden is checked against what its name and index entry claim, from
the rows alone and without the generator's tables: every error golden ends with its own code, every game's
digest is the spec 11.8 chain of its rows, the games are game 0 of the spec 16 vectors on a clock that reads
0, each seat's session is whole, and only the offending lines of Decision 7 are strings. A golden generated
wrong, not only one edited by hand, fails here.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from spellbench import wire
from spellbench.agent_messages import AGENT_ERROR_CODES
from spellbench.candidates import V2_KINDS
from spellbench.errors import MalformedJsonError
from spellbench.messages import ENGINE_ERROR_CODES

from golden_helpers import DIRECTIONS, GOLDENS_V2_DIR, golden_index, load_transcript_v2

TOOL = Path(__file__).resolve().parents[1] / "tools" / "generate_goldens_v2.py"
SUFFIX = ".transcript.jsonl"
ENGINE_REQUESTS = {"hello", "reset", "step", "validate_deck", "probe_resample"}
ENGINE_RESPONSES = {"hello_ok", "decision", "terminal", "deck_ok", "error"}
AGENT_REQUESTS = {"hello", "game_start", "choose", "game_over"}
AGENT_RESPONSES = {"hello_ok", "ack", "choice", "error"}
RESERVED_RESPONSES = {"probe_result"}               # spec 9.7: reserved, so no v2.0 engine produces it
ANSWERS = {"host_to_engine": "engine_to_host", "host_to_agent": "agent_to_host"}
# Each game and how it ends (outcome, classification, winner, reason), as the plan defines it.
GAMES = {
    "game_scoring": ("p0_win", "natural", "p0", "score"),
    "game_kinds_tour": ("draw", "natural", None, "scenario_complete"),
    "game_board_tour": ("draw", "natural", None, "scenario_complete"),
    "game_knowledge_tour": ("draw", "natural", None, "scenario_complete"),
    "game_forfeit_invalid_selection": ("p1_win", "forfeit", "p1", "forfeit:invalid_selection"),
    "game_halt_host_validator_v4": ("halted", "halted", None, "host_validator:V4"),
    "game_mandatory_loop": ("draw", "natural", None, "mandatory_loop"),
    "game_stalling_forfeit": ("p1_win", "forfeit", "p1", "forfeit:stalling"),
}
# The code tables of spec 9.8 and 10.5, in table order: the goldens are held to the spec, not to a module's copy.
SPEC_ENGINE_CODES = ("malformed_json", "malformed_request", "protocol_mismatch", "request_id_reuse_mismatch",
                     "step_before_reset", "game_already_active", "game_id_mismatch", "expected_step_mismatch",
                     "candidate_id_out_of_range", "semantic_echo_mismatch", "unsupported_format", "unsupported_deck",
                     "deck_id_mismatch", "unsupported_rule", "unsupported_request", "probe_refused",
                     "game_already_terminal")
SPEC_AGENT_CODES = ("malformed_json", "malformed_request", "protocol_mismatch", "unknown_game", "game_already_active",
                    "decision_pending", "internal_error")
ENGINE_ERRORS = {f"engine_error_{code}": code for code in SPEC_ENGINE_CODES}
ENGINE_ERRORS["engine_error_malformed_request_non_object"] = "malformed_request"
AGENT_ERRORS = {f"agent_error_{code}": code for code in SPEC_AGENT_CODES}
# Decision 7: the goldens whose offending host line is not a JSON object, kept as a string.
RAW_LINES = {"engine_error_malformed_json": "{not json", "agent_error_malformed_json": "{not json",
             "engine_error_malformed_request_non_object": "[1,2]"}
# Spec 16, the vector run secret: game 0 (spec 9.2, 10.2 examples) and game 1.
VECTORS = wire.strict_json_loads((GOLDENS_V2_DIR / "test_vectors.json").read_bytes())
REWIND_NOTE = ("a rewind abandons the rewound priority action's own group and every group completed after it; they do "
               "not count toward decision_count, and group_id is never reused")


def _stem(name: str) -> str:
    return name[: -len(SUFFIX)]


def _canonical_minus_id(message: dict[str, Any]) -> bytes:
    return wire.canonical_json_dumps({key: value for key, value in message.items() if key != "request_id"})


def _agent_messages(rows, request_type: str) -> list[dict]:
    return [message for direction, message in rows if direction == "host_to_agent"
            and isinstance(message, dict) and message["request_type"] == request_type]


def _seat_sessions(rows) -> dict[str, list[tuple[dict, dict]]]:
    """Each seat's (request, answer) pairs, told apart as a replay tells them: game_start by its seat, choose by the
    acting seat, and hello and game_over p0 first (Task 35)."""
    pairs: dict[str, list] = {"p0": [], "p1": []}
    hellos = overs = 0
    pending = None
    for direction, message in rows:
        if direction == "host_to_agent":
            kind = message["request_type"]
            if kind == "hello":
                seat, hellos = ("p0", "p1")[hellos], hellos + 1
            elif kind == "game_start":
                seat = message["seat"]
            elif kind == "choose":
                seat = message["decision"]["acting_seat"]
            else:
                seat, overs = ("p0", "p1")[overs], overs + 1
            pending = (seat, message)
        elif direction == "agent_to_host":
            seat, request = pending
            pairs[seat].append((request, message))
            pending = None
    return pairs


def _spec_11_8_digest(rows) -> str:
    """The game digest of spec 11.8, recomputed from a game's rows without ``digests.GameDigest``.

    The reset request (minus ``request_id``) seeds the chain; each engine answer and each step request follow in
    order; the host's ending is appended when it is not the engine's own terminal (a forfeit, a host halt or the
    mandatory-loop draw).
    """
    engine = [(direction, message) for direction, message in rows if direction in ("host_to_engine", "engine_to_host")]
    start = next(index for index, (direction, message) in enumerate(engine)
                 if direction == "host_to_engine" and message["request_type"] == "reset")
    d = hashlib.sha256(b"spellbench/v2/game-digest" + _canonical_minus_id(engine[start][1])).digest()
    terminal = None
    for direction, message in engine[start + 1:]:
        if direction == "host_to_engine":
            assert message["request_type"] == "step", message        # a game sends only steps after its reset
        d = hashlib.sha256(d + _canonical_minus_id(message)).digest()
        if message.get("response_type") == "terminal":
            terminal = message
    endings = [{key: over["terminal"][key] for key in ("classification", "outcome", "reason", "winner")}
               for over in _agent_messages(rows, "game_over")]
    assert endings and all(ending == endings[0] for ending in endings)
    if terminal is None or endings[0] != {key: terminal[key] for key in endings[0]}:
        d = hashlib.sha256(d + wire.canonical_json_dumps({"adjudication": endings[0]})).digest()
    return "sha256:" + d.hex()


# -- the plan's four tests -----------------------------------------------------------------------------------


def test_the_generator_check_passes() -> None:
    result = subprocess.run([sys.executable, str(TOOL), "--check"], capture_output=True, timeout=600)
    assert result.returncode == 0, result.stdout.decode() + result.stderr.decode()


def test_files_are_canonical_lines_and_indexed() -> None:
    names = sorted(path.name for path in GOLDENS_V2_DIR.glob("*" + SUFFIX))
    assert names == sorted(golden_index())
    for name in names:
        raw = (GOLDENS_V2_DIR / name).read_bytes()
        assert raw == b"".join(wire.canonical_json_line(wire.strict_json_loads(line)) for line in raw.splitlines()), name
    raw = (GOLDENS_V2_DIR / "index.json").read_bytes()
    assert raw == wire.canonical_json_line(wire.strict_json_loads(raw))            # one canonical line (Decision 7)


def test_every_game_has_a_digest_and_the_goldens_cover_the_protocol() -> None:
    kinds, engine_codes, agent_codes = set(), set(), set()
    for name, entry in golden_index().items():
        rows = load_transcript_v2(name)
        if name.startswith("game_"):
            assert entry["game_digest"].startswith("sha256:"), name
        for direction, message in rows:
            if not isinstance(message, dict):
                continue
            if direction == "host_to_agent" and message.get("request_type") == "choose":
                kinds |= {c["semantic"]["kind"] for c in message["decision"]["candidates"]}
            if message.get("response_type") == "error":
                (engine_codes if direction == "engine_to_host" else agent_codes).add(message["error"]["code"])
    assert kinds == V2_KINDS
    assert engine_codes == ENGINE_ERROR_CODES and agent_codes == AGENT_ERROR_CODES


def test_the_goldens_cover_every_message_type() -> None:
    seen: dict[str, set[str]] = {direction: set() for direction in DIRECTIONS}
    for name in golden_index():
        for direction, message in load_transcript_v2(name):
            if isinstance(message, dict):
                seen[direction].add(message.get("request_type") or message.get("response_type"))
    assert ENGINE_REQUESTS <= seen["host_to_engine"] and ENGINE_RESPONSES <= seen["engine_to_host"]
    assert AGENT_REQUESTS <= seen["host_to_agent"] and AGENT_RESPONSES <= seen["agent_to_host"]
    assert not RESERVED_RESPONSES & seen["engine_to_host"]                          # spec 16 (R3-26)
    assert json.loads((GOLDENS_V2_DIR / "index.json").read_bytes())["notes"]        # the Decision 4 reading (R2-23)


# -- a golden is what its name and index entry say -------------------------------------------------------------


def test_the_goldens_are_exactly_the_planned_set() -> None:
    assert ENGINE_ERROR_CODES == set(SPEC_ENGINE_CODES) and AGENT_ERROR_CODES == set(SPEC_AGENT_CODES)
    expected = {*GAMES, *ENGINE_ERRORS, "engine_validate_deck", *AGENT_ERRORS}
    assert sorted(_stem(name) for name in golden_index()) == sorted(expected)


def test_each_error_golden_ends_with_the_error_its_name_gives() -> None:
    """The last row answers the offending request with the golden's code, and no earlier answer is an error."""
    for stem, code in {**ENGINE_ERRORS, **AGENT_ERRORS}.items():
        rows = load_transcript_v2(stem + SUFFIX)
        sent = "host_to_engine" if stem.startswith("engine_") else "host_to_agent"
        answer = ANSWERS[sent]
        assert {direction for direction, _ in rows} == {sent, answer}, stem       # the one role's rows only
        direction, last = rows[-1]
        assert direction == answer and last["response_type"] == "error" and last["error"]["code"] == code, stem
        assert not [message for direction, message in rows[:-1] if isinstance(message, dict)
                    and message.get("response_type") == "error"], stem
        offending = [message for direction, message in rows if direction == sent][-1]
        # Spec 4.1: the error echoes the request's id, or "" for a line whose id cannot be read.
        assert last["request_id"] == ("" if isinstance(offending, str) else offending["request_id"]), stem
    rows = load_transcript_v2("engine_validate_deck" + SUFFIX)
    answers = [m["error"]["code"] if m["response_type"] == "error" else m["response_type"]
               for direction, m in rows if direction == "engine_to_host"]
    requests = [m["request_type"] for direction, m in rows if direction == "host_to_engine"]
    assert (requests, answers) == (["hello"] + ["validate_deck"] * 3, ["hello_ok", "deck_ok", "deck_ok", "unsupported_deck"])


def test_only_the_offending_lines_are_strings() -> None:
    """Decision 7: exactly the malformed_json and non-object host lines are strings; every other message is an object."""
    strings = {}
    for name in golden_index():
        for direction, message in load_transcript_v2(name):
            if isinstance(message, str):
                assert direction in ANSWERS, name                        # a line the host sent, never an answer
                strings.setdefault(_stem(name), []).append(message)
            else:
                assert isinstance(message, dict), name
    assert strings == {stem: [line] for stem, line in RAW_LINES.items()}


def test_every_game_digest_is_the_spec_11_8_chain_of_its_rows() -> None:
    index = golden_index()
    digests = {}
    for stem in GAMES:
        rows = load_transcript_v2(stem + SUFFIX)
        steps = [m["request_id"] for direction, m in rows if direction == "host_to_engine" and m["request_type"] == "step"]
        assert len(steps) == len(set(steps)), stem                      # no retransmission, so no step is chained twice
        digests[stem] = _spec_11_8_digest(rows)
        assert index[stem + SUFFIX]["game_digest"] == digests[stem], stem
    assert len(set(digests.values())) == len(digests)
    for name, entry in index.items():
        if not name.startswith("game_"):
            assert entry["game_digest"] is None, name


def test_each_game_ends_as_its_name_says() -> None:
    for stem, (outcome, classification, winner, reason) in GAMES.items():
        overs = _agent_messages(load_transcript_v2(stem + SUFFIX), "game_over")
        assert len(overs) == 2, stem                                     # spec 11.2: game_over to both agents
        for over in overs:
            terminal = over["terminal"]
            assert (terminal["outcome"], terminal["classification"], terminal["winner"], terminal["reason"]) == \
                (outcome, classification, winner, reason), stem


def test_the_games_are_game_0_of_the_spec_16_vectors() -> None:
    """Every reset is game 0 of the vector secret; the scoring game's is the spec 9.2 example, with its chain value."""
    for stem in GAMES:
        rows = load_transcript_v2(stem + SUFFIX)
        (reset,) = [m for direction, m in rows if direction == "host_to_engine" and m["request_type"] == "reset"]
        assert (reset["game_id"], reset["game_secret"]) == (VECTORS["game_id"]["0"], VECTORS["game_secret"]["0"]), stem
        assert reset["game_id"] == "g-f67d7fe78c792984"
        seeds = {m["seat"]: m["agent_seed"] for m in _agent_messages(rows, "game_start")}
        assert seeds == {"p0": VECTORS["agent_seed"]["0:p0"], "p1": VECTORS["agent_seed"]["0:p1"]}, stem
    rows = load_transcript_v2("game_scoring" + SUFFIX)
    reset = next(m for direction, m in rows if direction == "host_to_engine" and m["request_type"] == "reset")
    example = VECTORS["first_digest_chain_value"]
    assert {key: value for key, value in reset.items() if key != "request_id"} == example["reset"]
    assert hashlib.sha256(b"spellbench/v2/game-digest" + _canonical_minus_id(reset)).hexdigest() == example["d"]


def test_each_request_is_answered_before_the_next_is_sent() -> None:
    """Spec 2: one answer per request, in order, and no pipelining; the decision_pending golden shows the one host bug."""
    for name in golden_index():
        rows = load_transcript_v2(name)
        if name == "agent_error_decision_pending" + SUFFIX:
            assert [direction for direction, _ in rows[-4:]] == ["host_to_agent"] * 2 + ["agent_to_host"] * 2
            assert rows[-4][1] == rows[-3][1] and rows[-3][1]["request_type"] == "choose"   # the choose, sent again
            assert (rows[-2][1]["response_type"], rows[-1][1]["error"]["code"]) == ("choice", "decision_pending")
            rows = rows[:-4]
        assert len(rows) % 2 == 0, name
        for (sent, request), (answered, answer) in zip(rows[::2], rows[1::2]):
            assert sent in ANSWERS and answered == ANSWERS[sent], name
            assert answer["request_id"] == ("" if isinstance(request, str) else request["request_id"]), name


def test_each_seat_plays_one_whole_session() -> None:
    """Each seat's requests are numbered r-0, r-1, ... as one agent process numbers them (spec 4.1): hello, its own
    game_start, its own chooses, then game_over, whose seat_step_count counts its accepted answers (spec 10.4)."""
    for stem in GAMES:
        rows = load_transcript_v2(stem + SUFFIX)
        for seat, pairs in _seat_sessions(rows).items():
            requests = [request for request, _ in pairs]
            assert [request["request_id"] for request in requests] == [f"r-{n}" for n in range(len(requests))], stem
            kinds = [request["request_type"] for request in requests]
            assert kinds[:2] == ["hello", "game_start"] and kinds[-1] == "game_over", (stem, seat)
            assert set(kinds[2:-1]) <= {"choose"} and requests[1]["seat"] == seat, (stem, seat)
            accepted = sum(1 for request, answer in pairs if request["request_type"] == "choose"
                           and answer["response_type"] == "choice"
                           and 0 <= answer["selection"]["candidate_id"] < len(request["decision"]["candidates"]))
            assert requests[-1]["terminal"]["seat_step_count"] == accepted, (stem, seat)


def test_every_clock_reads_a_zero_time_clock() -> None:
    """Each decision took 0 ms (``clock_ns`` reads 0): a choose shows the bank plus one increment per earlier answer."""
    for stem in GAMES:
        rows = load_transcript_v2(stem + SUFFIX)
        controls = {m["seat"]: m["time_control"] for m in _agent_messages(rows, "game_start")}
        answered = {"p0": 0, "p1": 0}
        for choose in _agent_messages(rows, "choose"):
            seat = choose["decision"]["acting_seat"]
            control = controls[seat]
            assert choose["clock"] == {"remaining_ms": control["bank_ms"] + control["increment_ms"] * answered[seat],
                                       "max_decision_ms": control["max_decision_ms"]}, stem
            answered[seat] += 1


def test_the_games_show_every_group_shape() -> None:
    """Spec 8 and 16: the multi-substep shapes, one decision per finish step, a full arrangement, and a rewind."""
    groups: dict[tuple[str, str, int], list[dict]] = {}
    rewinds = []
    for stem in GAMES:
        seen: dict[str, set[int]] = {"p0": set(), "p1": set()}
        by_seat: dict[str, list[dict]] = {"p0": [], "p1": []}
        for choose in _agent_messages(load_transcript_v2(stem + SUFFIX), "choose"):
            sd = choose["decision"]
            seat, group = sd["acting_seat"], sd["group"]
            groups.setdefault((stem, seat, group["group_id"]), []).append(sd)
            by_seat[seat].append(sd)
            if sd["context"]["rewind"]:
                rewinds.append((group["group_id"], seen[seat]))
            seen[seat] = seen[seat] | {group["group_id"]}
        for sds in by_seat.values():                     # a group goes on substep by substep, or a rewind ends it
            for sd, following in zip(sds, [*sds[1:], None]):
                group = sd["group"]
                if following is not None and group["substep_index"] + 1 < group["substep_count"]:
                    assert following["context"]["rewind"] or following["group"] == {
                        **group, "substep_index": group["substep_index"] + 1}, (stem, sd["seat_step"])
    shapes = {sds[0]["candidates"][0]["semantic"]["kind"] for sds in groups.values() if sds[0]["group"]["substep_count"] > 1}
    assert {"declare_attack", "declare_block", "choose_target", "select_object", "choose_spell_mode", "distribute",
            "arrange_card", "order_pick"} <= shapes
    for sds in groups.values():
        kinds = {c["semantic"]["kind"] for sd in sds for c in sd["candidates"]}
        if kinds & {"finish_target_selection", "finish_selection"}:
            assert [sd["group"]["substep_count"] for sd in sds] == [1] * len(sds)   # one group per decision (spec 8)
    full = [sds for sds in groups.values() if sds[0]["candidates"][0]["semantic"]["kind"] == "arrange_card"
            and [sd["group"]["substep_index"] for sd in sds] == list(range(sds[0]["group"]["substep_count"]))]
    assert any(len(sds) >= 3 and len(sds) % 2 == 1 for sds in full)      # 2n - 1 decisions, every one posed (spec 7.5)
    assert rewinds and all(group_id > max(before, default=-1) for group_id, before in rewinds)   # never reused (Decision 4)


def test_the_index_records_each_goldens_engine_and_replays() -> None:
    index = wire.strict_json_loads((GOLDENS_V2_DIR / "index.json").read_bytes())
    assert index["schema"] == "spellbench-goldens/v2" and index["notes"][0] == REWIND_NOTE
    for name, entry in index["transcripts"].items():
        stem, rows = _stem(name), load_transcript_v2(name)
        assert set(entry) == {"engine", "engine_args", "game_digest", "roles"}, name
        has_engine = any(direction == "host_to_engine" for direction, _ in rows)
        assert (entry["engine"] is not None) == has_engine, name
        if stem == "game_halt_host_validator_v4":
            assert (entry["engine"], entry["engine_args"]) == ("hostile_v2_engine.py", ["stale-reference"])
        elif has_engine:
            assert entry["engine"] == "fake_v2_engine.py", name
        else:
            assert entry["engine_args"] == [], name
        if stem in GAMES:
            roles = ["engine", "host"] if stem == "game_forfeit_invalid_selection" else ["bot_server", "engine", "host"]
        elif stem.startswith("engine_"):
            roles = ["engine"]
        else:
            roles = [] if stem == "agent_error_decision_pending" else ["bot_server"]
        assert entry["roles"] == roles, name
    assert index["transcripts"]["engine_error_probe_refused" + SUFFIX]["engine_args"] == ["--probe"]


def test_no_machine_value_leaks_into_a_golden() -> None:
    """No path, interpreter name or carriage return: the goldens are the same bytes on every machine."""
    values = (str(Path(__file__).resolve().parents[2]), sys.executable, tempfile.gettempdir(), os.path.expanduser("~"))
    leaks = {value for value in values if len(value) >= 8}              # a home of "/" would match every golden
    for path in [*GOLDENS_V2_DIR.glob("*" + SUFFIX), GOLDENS_V2_DIR / "index.json"]:
        raw = path.read_bytes()
        assert b"\r" not in raw, path.name
        for leak in leaks:
            assert leak.encode("utf-8") not in raw, (path.name, leak)


@pytest.mark.parametrize("stem", sorted(RAW_LINES))
def test_the_offending_line_is_answered_as_its_code_says(stem: str) -> None:
    """The string rows hold lines that are not JSON objects, so a replay that sends them as bytes draws the same code."""
    line = RAW_LINES[stem]
    try:
        wire.strict_json_loads(line.encode("utf-8"))
    except wire.NotAnObjectError:
        expected = "malformed_request"                               # valid JSON, not an object (spec 9.8)
    except MalformedJsonError:
        expected = "malformed_json"
    else:
        pytest.fail(f"{line!r} is a JSON object")
    assert load_transcript_v2(stem + SUFFIX)[-1][1]["error"]["code"] == expected
