"""The London entrant registration and the rated-identity check: honest labels, and no equal Nones."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


add = load("add_london_entrant")
identity = load("rated_identity_check")


def test_a_chain_state_label_names_the_state_and_whether_the_lean_was_active() -> None:
    assert add.chain_label("arm M m1", 4096, 32768) == (
        "arm M m1 at 4,096 updates (keep lean still active in training)", True)
    assert add.chain_label("arm M m1", 32767, 32768)[1] is True
    assert add.chain_label("arm M m1", 32768, 32768)[1] is True  # its last update still had a nonzero offset
    assert add.chain_label("arm M m1", 32769, 32768)[1] is False
    assert add.chain_label("arm M m1", 36864, 32768) == (
        "arm M m1 at 36,864 updates (keep lean already zero in training)", False)


def base_args(tmp_path: Path, *extra: str) -> list[str]:
    checkpoint = tmp_path / "ck.json"
    checkpoint.write_text("{}", encoding="utf-8")
    base = tmp_path / "base.json"
    base.write_text(json.dumps({"selection": "s", "source": {"play_import": {}}}), encoding="utf-8")
    return ["--name", "arm-m-m1-u0004096", "--checkpoint-json", str(checkpoint), "--scorer", str(tmp_path / "none.exe"),
            "--base-config", str(base), "--inputs-dir", str(tmp_path / "in"), *extra]


@pytest.mark.parametrize("extra", [
    ["--chain", "arm M m1"],                                            # no update count
    ["--fork-updates", "4096"],                                          # no chain name
    ["--chain", "arm M m1", "--fork-updates", "4096", "--label", "x"],   # the label is derived
    ["--chain", "arm M m1", "--fork-updates", "4096", "--keep-seven-test"],
])
def test_a_chain_entrant_derives_its_label_and_refuses_a_hand_written_one(tmp_path, extra) -> None:
    with pytest.raises(SystemExit):
        add.main(base_args(tmp_path, *extra))


def test_the_keep7_name_rule_holds_in_both_directions_here_too(tmp_path) -> None:
    args = base_args(tmp_path)
    args[1] = "learned-keep7-bot"
    with pytest.raises(SystemExit):
        add.main(args)
    args[1] = "learned-bot"
    with pytest.raises(SystemExit):
        add.main([*args, "--keep-seven-test"])


def test_the_identity_check_rejects_a_file_it_cannot_hash(tmp_path, capsys) -> None:
    board, local = tmp_path / "benchmark.json", tmp_path / "local.json"
    board.write_text(json.dumps({"evaluation_engine_inputs": ["${MTG_KERNEL_V2_BRIDGE}"]}), encoding="utf-8")
    local.write_text(json.dumps({"MTG_KERNEL_V2_BRIDGE": str(tmp_path / "missing.exe")}), encoding="utf-8")
    out = tmp_path / "before.json"
    args = ["--rated-board", str(board), "--rated-local", str(local)]
    assert identity.main(["snapshot", *args, "--out", str(out)]) == 1
    assert "no hash" in capsys.readouterr().out and not out.exists()
    # A snapshot that already holds a null is refused at compare time, even if the file is unreadable both times.
    out.write_text(json.dumps(identity.snapshot(board, local)), encoding="utf-8")
    assert identity.main(["compare", str(out), *args]) == 1
    assert "no hash" in capsys.readouterr().out
    # With the file present the snapshot is written (the repository's own pins are real files).
    (tmp_path / "missing.exe").write_bytes(b"x")
    assert identity.main(["snapshot", *args, "--out", str(out)]) == 0


def test_the_keep6_name_rule_and_the_rule_flag_go_together_and_never_with_keep7(tmp_path) -> None:
    args = base_args(tmp_path, "--keep-after-mulligan-rule")      # the flag under a learned name
    with pytest.raises(SystemExit):
        add.main(args)
    args = base_args(tmp_path)
    args[1] = "learned-keep6-bot"                                  # the name part without the flag
    with pytest.raises(SystemExit):
        add.main(args)
    args = base_args(tmp_path, "--keep-after-mulligan-rule", "--keep-seven-test")
    args[1] = "x-keep6-keep7"
    with pytest.raises(SystemExit):
        add.main(args)


def test_a_keep_after_mulligan_chain_entrant_is_registered_with_the_rule_in_its_label(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(add, "probe", lambda scorer, config: {"model_state_sha256": "e" * 64, "model": {"adam_step": 1}})
    args = base_args(tmp_path, "--chain", "arm P p1", "--fork-updates", "20480", "--keep-after-mulligan-rule")
    args[1] = "arm-p-p1-u0020480-keep6"
    assert add.main(args) == 0
    [entry] = json.loads((tmp_path / "in" / "london-entrants.json").read_text(encoding="utf-8"))["entrants"]
    assert entry["keep_after_mulligan_rule"] is True and entry["keep_seven_test"] is False
    assert entry["label"] == ("arm P p1 at 20,480 updates: mulligan decision at seven from the network "
                              "(partly trained, level still unstable); keeps any six by rule")
    assert entry["chain"]["lean_active_when_saved"] is True and "STOPGAP" in entry["description"]
