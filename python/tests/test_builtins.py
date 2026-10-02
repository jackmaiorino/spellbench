"""The builtin bots on v2: uniform seeded from agent_seed, first, heuristic."""

from __future__ import annotations

import importlib
import io
import subprocess
import sys

import pytest

from spellbench import wire
from spellbench.bot import Decision, GameOver, GameStart
from spellbench.builtins import BUILTIN_BOTS, BUILTIN_VERSIONS, create_builtin_bot
from spellbench.builtins.uniform import DERIVATION_VERSION, MASK64, SplitMix64, stream_seed

# Bots read leniently, so short semantics are enough here (Task 7's samples land in the same wave).
SAMPLES = {
    "pass": {"kind": "pass"},
    "play_land": {"kind": "play_land", "face": 0},
    "cast_spell": {"kind": "cast_spell", "method": "normal"},
    "activate_ability": {"kind": "activate_ability", "ability_index": 0},
    "activate_mana_ability": {"kind": "activate_mana_ability", "ability_index": 0, "mana_choice": "R"},
    "mulligan": {"kind": "mulligan", "hand_size": 7, "mulligans_taken": 0, "keep": True},
    "declare_attack": {"kind": "declare_attack", "defender": {"player": "p1"}},
    "declare_block": {"kind": "declare_block", "attacker": None},
    "choose_option": {"kind": "choose_option", "option_index": 0, "option_count": 2},
    "choose_boolean": {"kind": "choose_boolean", "value": True},
}


def _decision(*kinds: str) -> Decision:
    candidates = [{"candidate_id": index, "semantic": SAMPLES[kind], "display_text": None} for index, kind in enumerate(kinds)]
    return Decision.from_request({"game_id": "g-1", "decision": {"candidates": candidates}})


def _start(bot, *, agent_seed: int, seat: str = "p0") -> None:
    bot.on_game_start(GameStart.from_request({"game_id": "g-1", "seat": seat, "agent_seed": agent_seed}))


def test_versions_are_2_0_0() -> None:
    assert BUILTIN_VERSIONS == {"first": "2.0.0", "heuristic": "2.0.0", "uniform": "2.0.0"}


def test_uniform_follows_the_agent_seed() -> None:
    decision = _decision(*sorted(SAMPLES)[:8])

    def picks(agent_seed: int, seed: int = 11) -> list[int]:
        bot = create_builtin_bot("uniform", seed=seed)
        _start(bot, agent_seed=agent_seed)
        return [bot.choose(decision) for _ in range(40)]

    assert picks(8103969398531465) == picks(8103969398531465)
    assert picks(8103969398531465) != picks(1382627979884484)
    assert picks(8103969398531465) != picks(8103969398531465, seed=12)
    assert set(picks(5)) <= set(range(8))


def test_uniform_needs_a_game() -> None:
    with pytest.raises(RuntimeError):
        create_builtin_bot("uniform").choose(_decision("pass"))


@pytest.mark.parametrize(
    ("kinds", "expected"),
    [
        (("pass", "play_land", "cast_spell"), 1),
        (("pass", "cast_spell", "activate_ability"), 1),
        (("pass", "activate_mana_ability"), 1),
        (("mulligan",), 0),
        (("declare_block",), 0),
        (("pass", "choose_option"), 0),
    ],
)
def test_heuristic_priorities(kinds: tuple[str, ...], expected: int) -> None:
    bot = create_builtin_bot("heuristic")
    _start(bot, agent_seed=1)
    assert bot.choose(_decision(*kinds)) == expected


def test_heuristic_attacks_and_does_not_block() -> None:
    attack = dict(SAMPLES["declare_attack"])
    candidates = [{"candidate_id": 0, "semantic": {**attack, "defender": None}, "display_text": None},
                  {"candidate_id": 1, "semantic": attack, "display_text": None}]
    bot = create_builtin_bot("heuristic")
    _start(bot, agent_seed=1)
    assert bot.choose(Decision.from_request({"game_id": "g-1", "decision": {"candidates": candidates}})) == 1


def test_first_takes_the_first_candidate_and_serves_over_stdio() -> None:
    assert create_builtin_bot("first").choose(_decision("pass", "play_land")) == 0
    lines = b"".join(wire.canonical_json_line({"request_type": kind, "protocol": "spellbench/v2", "request_id": f"r-{i}", **extra})
                     for i, (kind, extra) in enumerate([("hello", {}), ("game_start", {"game_id": "g-1"}),
                                                        ("choose", {"game_id": "g-1", "decision": {"candidates": [{"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None}]}}),
                                                        ("game_over", {"game_id": "g-1", "terminal": {}})]))
    result = subprocess.run([sys.executable, "-m", "spellbench.builtins.first"], input=lines, capture_output=True, timeout=30)
    assert result.returncode == 0 and b'"name":"first"' in result.stdout and b'"version":"2.0.0"' in result.stdout
    assert result.stderr == b""  # no runpy warning: the package has not imported the module -m runs


# The exact behavior each builtin promises; the uniform bot is the rating anchor, so its picks are pinned.


def _offered(*pairs: tuple[int, dict]) -> Decision:
    """A decision from (candidate_id, semantic) pairs, so ids can differ from list positions."""
    candidates = [{"candidate_id": candidate_id, "semantic": semantic, "display_text": None} for candidate_id, semantic in pairs]
    return Decision.from_request({"game_id": "g-1", "decision": {"candidates": candidates}})


def test_the_table_names_each_bot_and_refuses_unknown_names() -> None:
    assert {name: (bot.name, bot.version) for name, bot in BUILTIN_BOTS.items()} == {
        name: (name, version) for name, version in BUILTIN_VERSIONS.items()
    }
    with pytest.raises(ValueError, match="unknown builtin bot"):
        create_builtin_bot("random")
    with pytest.raises(ValueError, match="nonnegative"):
        create_builtin_bot("uniform", seed=-1)
    package = importlib.import_module("spellbench.builtins")  # the tables are built on first access (PEP 562)
    assert package.BUILTIN_BOTS is BUILTIN_BOTS and "BUILTIN_VERSIONS" in vars(package)  # then kept as attributes
    assert not hasattr(package, "no_such_name")  # a plain AttributeError, so from-imports of the bot modules work


def test_splitmix64_is_the_reference_generator() -> None:
    stream = SplitMix64(1234567)  # the published SplitMix64 test vector, as mtg-kernel's determinism.py computes it
    assert [stream.next() for _ in range(5)] == [6457827717110365317, 3203168211198807973, 9817491932198370423,
                                                  4593380528125082431, 16408922859458223821]
    assert stream_seed(8103969398531465, 11) == 8103969398531465 ^ 11 and stream_seed(5, (1 << 64) | 5) == 0
    assert DERIVATION_VERSION == "spellbench-arena-uniform-v2"


def test_uniform_is_the_documented_derivation() -> None:
    ids = (9, 4, 7, 0, 12)  # candidate ids, not positions, are answered
    decision = _offered(*((candidate_id, {"kind": "choose_option", "option_index": index, "option_count": 5})
                          for index, candidate_id in enumerate(ids)))
    bot = create_builtin_bot("uniform", seed=11)
    for agent_seed in (8103969398531465, 1382627979884484, None):  # None: no agent_seed, read as 0
        request = {"game_id": "g-1", "seat": "p1"} if agent_seed is None else {"game_id": "g-1", "seat": "p1", "agent_seed": agent_seed}
        bot.on_game_start(GameStart.from_request(request))  # the same bot object, reseeded at every game_start
        stream = SplitMix64(((agent_seed or 0) ^ 11) & MASK64)
        assert [bot.choose(decision) for _ in range(30)] == [ids[stream.next() % len(ids)] for _ in range(30)]
        bot.on_game_over(GameOver.from_request({"game_id": "g-1", "terminal": {}}))


@pytest.mark.parametrize(
    ("semantics", "expected"),
    [
        ((SAMPLES["pass"], SAMPLES["activate_ability"], SAMPLES["cast_spell"], SAMPLES["play_land"]), 3),
        ((SAMPLES["pass"], SAMPLES["activate_ability"], SAMPLES["cast_spell"]), 2),
        ((SAMPLES["pass"], SAMPLES["activate_ability"], SAMPLES["activate_mana_ability"]), 1),
        (({**SAMPLES["mulligan"], "keep": False}, SAMPLES["mulligan"]), 1),
        (({"kind": "declare_block", "attacker": {"object_id": "o-1"}}, SAMPLES["declare_block"]), 1),
    ],
)
def test_heuristic_prefers_kinds_over_positions(semantics: tuple[dict, ...], expected: int) -> None:
    bot = create_builtin_bot("heuristic")
    _start(bot, agent_seed=1)
    assert bot.choose(_offered(*enumerate(semantics))) == expected


@pytest.mark.parametrize("seat", ["p0", "p1"])
def test_heuristic_names_its_own_seat_to_start(seat: str) -> None:
    decision = _offered(*((index, {"kind": "choose_starting_player", "player": player}) for index, player in enumerate(("p0", "p1"))))
    bot = create_builtin_bot("heuristic")
    _start(bot, agent_seed=1, seat=seat)
    assert bot.choose(decision) == ("p0", "p1").index(seat)


def test_heuristic_and_first_answer_candidate_ids_not_positions() -> None:
    lands = _offered((7, SAMPLES["pass"]), (3, SAMPLES["cast_spell"]), (5, SAMPLES["play_land"]))
    nothing_preferred = _offered((7, SAMPLES["pass"]), (3, SAMPLES["choose_option"]))
    heuristic = create_builtin_bot("heuristic")
    _start(heuristic, agent_seed=1)
    assert (heuristic.choose(lands), heuristic.choose(nothing_preferred)) == (5, 7)
    assert create_builtin_bot("first").choose(nothing_preferred) == 7


@pytest.mark.parametrize(("name", "args", "seed"), [("heuristic", [], 0), ("uniform", ["--seed", "11"], 11)])
def test_each_module_serves_its_bot_over_stdio(name: str, args: list[str], seed: int) -> None:
    start = {"game_id": "g-1", "seat": "p0", "agent_seed": 8103969398531465}
    choose = {"game_id": "g-1", "decision": {"candidates": [
        {"candidate_id": index, "semantic": SAMPLES[kind], "display_text": None} for index, kind in enumerate(sorted(SAMPLES))]}}
    requests = [("hello", {}), ("game_start", start), *[("choose", choose)] * 5, ("game_over", {"game_id": "g-1", "terminal": {}})]
    lines = b"".join(wire.canonical_json_line({"request_type": kind, "protocol": "spellbench/v2", "request_id": f"r-{i}", **extra})
                     for i, (kind, extra) in enumerate(requests))
    result = subprocess.run([sys.executable, "-m", f"spellbench.builtins.{name}", *args], input=lines, capture_output=True, timeout=30)
    assert (result.returncode, result.stderr) == (0, b"")
    answers = [wire.strict_json_loads(line) for line in result.stdout.splitlines()]
    in_process = create_builtin_bot(name, seed=seed)
    in_process.on_game_start(GameStart.from_request(start))
    assert answers[0]["bot"] == {"name": name, "version": "2.0.0"}
    assert [answer["selection"]["candidate_id"] for answer in answers[2:7]] == [
        in_process.choose(Decision.from_request(choose)) for _ in range(5)]


@pytest.mark.parametrize("name", ["first", "heuristic", "uniform"])
def test_each_module_answers_hello_under_an_error_warnings_filter(name: str) -> None:
    hello = wire.canonical_json_line({"request_type": "hello", "protocol": "spellbench/v2", "request_id": "r-0", "protocol_minor": 0})
    result = subprocess.run([sys.executable, "-W", "error", "-m", f"spellbench.builtins.{name}"], input=hello, capture_output=True, timeout=30)
    assert (result.returncode, result.stderr) == (0, b"")
    [answer] = [wire.strict_json_loads(line) for line in result.stdout.splitlines()]
    assert answer["bot"] == {"name": name, "version": "2.0.0"}


@pytest.mark.parametrize("kind", [["x"], {"x": 1}, "pay_mana", "some_future_kind"])
def test_heuristic_reads_odd_kinds_leniently(kind: object) -> None:
    # Unhashable, reserved (spec 7.7) and unknown kinds match no preference and never raise,
    # since an exception in choose is an internal_error forfeit (spec 10.5).
    bot = create_builtin_bot("heuristic")
    _start(bot, agent_seed=1)
    assert bot.choose(_offered((0, {"kind": kind}))) == 0
    assert bot.choose(_offered((0, {"kind": kind}), (1, SAMPLES["activate_ability"]))) == 1


@pytest.mark.parametrize(
    ("name", "args"),
    [("uniform", ["--seed"]), ("uniform", ["--seed", "x"]), ("uniform", ["--seed", "-1"]),
     ("first", ["--seed", "5"]), ("heuristic", ["--seed", "5"])],
)
def test_a_bad_argument_gets_the_usage_line(name: str, args: list[str], monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", [name, *args])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO()))  # a bot that serves anyway reads EOF and returns 0
    assert importlib.import_module(f"spellbench.builtins.{name}").main() == 2
    assert "usage" in capsys.readouterr().err
