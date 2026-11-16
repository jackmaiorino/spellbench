"""The human-only London board generator and the entrant registry: a copy of the rated board, never over it."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("make_london_human_board", REPO / "tools" / "make_london_human_board.py")
make = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make)


def rated_board() -> dict:
    return {"schema": "x", "id": "pauper-ladder-v2", "title": "Rated", "summary": "s", "format": "pauper-bo1",
            "engine": {"name": "mtg-kernel", "command": ["${PYTHON}", "${MTG_KERNEL_V2_INFOSET_ENGINE}"]},
            "extensions": ["x_kernel_flat_v4", "x_public_history_v1", "x_kernel_infoset_v1"],
            "native_id_audits": {"x_kernel_flat_v4": "docs/a.md"},
            "ladder": {"band": 1}, "opponent_panel": ["uniform"], "evaluation_version": "v", "evaluation_targets": {},
            "bots": [{"name": "uniform", "evaluation_identity": "a"}, {"name": "heuristic", "evaluation_identity": "b"},
                     {"name": "g115", "evaluation_identity": "c", "type": "subprocess", "engine": "mtg-kernel",
                      "owner": "owner-x", "display": {"label": "g", "author": "author-x"}}]}


def entrant(name: str, keep7: bool = False, keep6: bool = False) -> dict:
    return {"name": name, "label": name, "scorer_config": f"E:/x/{name}.json", "checkpoint": f"E:/x/{name}.ckpt",
            "model_state_sha256": "e" * 64, "keep_seven_test": keep7, "keep_after_mulligan_rule": keep6}


def write(tmp_path: Path, entrants: list[dict]) -> tuple[Path, Path, Path]:
    (tmp_path / "rated").mkdir(exist_ok=True)
    board, local, registry = tmp_path / "rated" / "benchmark.json", tmp_path / "local.json", tmp_path / "registry.json"
    board.write_text(json.dumps(rated_board()), encoding="utf-8")
    local.write_text(json.dumps({"PYTHON": "py", "MTG_KERNEL_SCORER": "scorer", "MTG_KERNEL_PUBLIC_CATALOG": "catalog"}), encoding="utf-8")
    registry.write_text(json.dumps({"entrants": entrants}), encoding="utf-8")
    return board, local, registry


def test_the_copy_drops_the_ladder_swaps_the_engine_and_lists_only_anchors_and_london_bots(tmp_path) -> None:
    board_path, local_path, registry = write(tmp_path, [entrant("chains-a-c4-london-test"),
                                                        entrant("chains-a-c4-keep7-test", keep7=True)])
    board, values = make.make(board_path, local_path, registry, "E:/bridge.exe", "abc123")
    assert board["id"] == "pauper-london-human-v1"
    assert all(field not in board for field in make.LADDER_FIELDS)
    assert board["extensions"] == ["x_kernel_flat_v7", "x_public_history_v1"]
    assert "--known-cards" not in board["engine"]["command"]
    assert board["engine"]["command"][-2:] == ["--source-revision", "abc123"]
    assert [bot["name"] for bot in board["bots"]] == ["uniform", "heuristic", "chains-a-c4-london-test",
                                                      "chains-a-c4-keep7-test"]
    assert all("evaluation_identity" not in bot for bot in board["bots"])
    learned, keep7 = board["bots"][2:]
    assert "--test-keep-seven" not in learned["command"] and "--test-keep-seven" in keep7["command"]
    assert learned["command"][learned["command"].index("--expect-model-state") + 1] == "e" * 64
    assert values["MTG_KERNEL_LONDON_HUMAN_BRIDGE"] == "E:/bridge.exe"
    assert values["MTG_KERNEL_LONDON_CHAINS_A_C4_LONDON_TEST_SCORER_CONFIG"] == "E:/x/chains-a-c4-london-test.json"
    # Every placeholder of the board has a value.
    text = json.dumps(board)
    for name in {part.split("}")[0] for part in text.split("${")[1:]}:
        assert name in values, name


def test_names_that_share_a_placeholder_are_refused(tmp_path) -> None:
    board_path, local_path, registry = write(tmp_path, [entrant("chain-a"), entrant("chain_a")])
    with pytest.raises(SystemExit):
        make.make(board_path, local_path, registry, "E:/bridge.exe", "abc123")


def test_the_generator_never_writes_into_the_rated_boards_folder(tmp_path, capsys) -> None:
    board_path, local_path, registry = write(tmp_path, [entrant("chains-a-c4-london-test")])
    with pytest.raises(SystemExit):
        make.main(["--rated-board", str(board_path), "--rated-local", str(local_path), "--registry", str(registry),
                   "--out", str(board_path.parent), "--bridge", "b", "--engine-revision", "r"])
    out = tmp_path / "scratch" / "london"
    assert make.main(["--rated-board", str(board_path), "--rated-local", str(local_path), "--registry", str(registry),
                      "--out", str(out), "--bridge", "b", "--engine-revision", "r"]) == 0
    assert (out / "benchmark.json").exists() and (out / "local.json").exists()
    assert json.loads(board_path.read_text(encoding="utf-8"))["id"] == "pauper-ladder-v2"


def test_a_keep_seven_entrant_is_named_and_labelled_as_a_test_and_nothing_else_is(tmp_path) -> None:
    keep7 = dict(entrant("chains-a-c4-keep7-test", keep7=True), label="Basilisk 2")
    board_path, local_path, registry = write(tmp_path, [entrant("chains-a-c4-london-test"), keep7])
    board, _ = make.make(board_path, local_path, registry, "b", "r")
    assert board["bots"][2]["display"]["label"] == "chains-a-c4-london-test"
    assert board["bots"][3]["display"]["label"] == "Basilisk 2 (keeps seven, test)"
    # The suffix is derived, not doubled for a registry that already has it.
    keep7["label"] = "Basilisk 2 (keeps seven, test)"
    board_path, local_path, registry = write(tmp_path, [keep7])
    assert make.make(board_path, local_path, registry, "b", "r")[0]["bots"][2]["display"]["label"] == keep7["label"]


@pytest.mark.parametrize("bad", [dict(name="learned-bot", keep7=True), dict(name="learned-keep7-bot", keep7=False)])
def test_the_keep7_name_rule_holds_in_both_directions_in_the_generator(tmp_path, bad) -> None:
    board_path, local_path, registry = write(tmp_path, [entrant(bad["name"], keep7=bad["keep7"])])
    with pytest.raises(SystemExit):
        make.make(board_path, local_path, registry, "b", "r")


def test_a_learned_entrant_cannot_claim_to_keep_seven_in_its_label(tmp_path) -> None:
    claiming = dict(entrant("chains-a-c4-london-test"), label="Basilisk 2 (keeps seven, test)")
    board_path, local_path, registry = write(tmp_path, [claiming])
    with pytest.raises(SystemExit):
        make.make(board_path, local_path, registry, "b", "r")


def test_the_numeric_fill_flag_is_on_the_bot_commands_only_when_asked_for(tmp_path) -> None:
    board_path, local_path, registry = write(tmp_path, [entrant("chains-a-c4-london-test")])
    plain, _ = make.make(board_path, local_path, registry, "b", "r")
    assert "--allow-numeric-v4-fill" not in plain["bots"][2]["command"]
    flow, _ = make.make(board_path, local_path, registry, "b", "r", allow_numeric_fill=True)
    assert "--allow-numeric-v4-fill" in flow["bots"][2]["command"]


def test_the_generator_names_nobody_it_copies_the_rated_boards_own_fields(tmp_path) -> None:
    board_path, local_path, registry = write(tmp_path, [entrant("chains-a-c4-london-test")])
    board, _ = make.make(board_path, local_path, registry, "b", "r")
    assert (board["bots"][2]["owner"], board["bots"][2]["display"]["author"]) == ("owner-x", "author-x")
    # With no mtg-kernel entry on the rated board there is nothing to copy: the fields stay empty, never invented.
    bare = rated_board()
    bare["bots"] = bare["bots"][:2]
    board_path.write_text(json.dumps(bare), encoding="utf-8")
    board, _ = make.make(board_path, local_path, registry, "b", "r")
    assert (board["bots"][2]["owner"], board["bots"][2]["display"]["author"]) == (None, None)


def test_a_keep_after_mulligan_entrant_carries_its_flag_and_an_honest_derived_label(tmp_path) -> None:
    rule = dict(entrant("arm-p-keep6", keep6=True), label="arm P at 20,480 updates")
    board_path, local_path, registry = write(tmp_path, [entrant("chains-a-c4-london-test"), rule])
    board, _ = make.make(board_path, local_path, registry, "b", "r")
    learned, ruled = board["bots"][2:]
    assert "--keep-after-mulligan" not in learned["command"] and "--keep-after-mulligan" in ruled["command"]
    assert "--test-keep-seven" not in ruled["command"]
    assert ruled["display"]["label"] == ("arm P at 20,480 updates: mulligan decision at seven from the network "
                                         "(partly trained, level still unstable); keeps any six by rule")
    # A label that already carries the note is not doubled; the note is derived, never taken on trust.
    rule["label"] = ruled["display"]["label"]
    board_path, local_path, registry = write(tmp_path, [rule])
    again, _ = make.make(board_path, local_path, registry, "b", "r")
    assert again["bots"][2]["display"]["label"] == ruled["display"]["label"]


@pytest.mark.parametrize("bad", [dict(name="learned-bot", keep6=True), dict(name="learned-keep6-bot", keep6=False)])
def test_the_keep6_name_rule_holds_in_both_directions_in_the_generator(tmp_path, bad) -> None:
    board_path, local_path, registry = write(tmp_path, [entrant(bad["name"], keep6=bad["keep6"])])
    with pytest.raises(SystemExit):
        make.make(board_path, local_path, registry, "b", "r")


def test_the_rule_and_the_keep_seven_test_are_never_one_entrant_and_a_learned_label_cannot_claim_the_rule(tmp_path) -> None:
    both = entrant("x-keep6-keep7", keep7=True, keep6=True)
    board_path, local_path, registry = write(tmp_path, [both])
    with pytest.raises(SystemExit):
        make.make(board_path, local_path, registry, "b", "r")
    claiming = dict(entrant("chains-a-c4-london-test"), label="Basilisk 2, keeps any six by rule")
    board_path, local_path, registry = write(tmp_path, [claiming])
    with pytest.raises(SystemExit):
        make.make(board_path, local_path, registry, "b", "r")
