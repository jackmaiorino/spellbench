from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import kernel_flat_bot as bot_module  # noqa: E402
from spellbench import wire  # noqa: E402
from spellbench.agent_client import AgentProcess  # noqa: E402
from spellbench.errors import RemoteError, TransportError  # noqa: E402
from spellbench.models import Decision  # noqa: E402

HERE = Path(__file__).resolve().parent
BOT = HERE.parent / "kernel_flat_bot.py"
FAKE = HERE / "fake_scorer.py"
GAME_ID = "m0000p0000g0"
KERNEL_ENGINE = {
    "name": "mtg-kernel", "version": "0.0.4-spike", "source_revision": None,
    "rules_snapshot_id": "mtg-kernel-rules/0.0.4-spike/carddb-064a7c989255ab3c",
    "card_pool_identity": "mtg-kernel-pauper-pool-v1/carddb-064a7c989255ab3c",
}
OBJ = {"object_id": "obj-000001", "card_name": "Mountain", "owner_seat": "p0", "controller_seat": "p0", "zone": "hand"}
BOLT = dict(OBJ, object_id="obj-000002", card_name="Lightning Bolt")


def bot_argv(tmp_path: Path, mode: str = "ok", log: Path | None = None, extra: tuple[str, ...] = ()) -> list[str]:
    argv = [
        sys.executable, str(BOT), "--scorer", sys.executable, "--scorer-arg", str(FAKE),
        "--scorer-arg=--mode", f"--scorer-arg={mode}", "--config", str(tmp_path / "unused.json"),
        "--name", "g115-test", "--version", "1.0.0",
    ]
    return argv + (["--decision-log", str(log)] if log is not None else []) + list(extra)


def make_decision(
    rows: list[int] | None, *, step: int = 0, acting_seat: str = "p0", changes: dict | None = None,
) -> Decision:
    """A decision for acting_seat; changes overrides fields of its x_kernel_flat_v4."""
    candidates = [
        {"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None},
        {"candidate_id": 1, "semantic": {"kind": "play_land", "source": OBJ}, "display_text": None},
        {"candidate_id": 2, "semantic": {"kind": "cast_spell", "source": BOLT}, "display_text": None},
    ]
    seats = [
        {"seat": seat, "life": 20, "hand_count": 7, "library_count": 53, "graveyard_count": 0, "battlefield_count": 0}
        for seat in ("p0", "p1")
    ]
    extensions = {}
    if rows is not None:
        extensions["x_kernel_flat_v4"] = {
            "schema": "mtg-kernel-spellbench-flat-v4/v1",
            "feature_contract_digest": bot_module.FEATURE_CONTRACT_DIGEST,
            "feature_encoding_digest": bot_module.FEATURE_ENCODING_DIGEST,
            "card_db_hash": "064a7c989255ab3c", "acting_seat": acting_seat, "step": step,
            "row_candidate_ids": rows, "tensor": {key: [] for key in sorted(bot_module.TENSOR_KEYS)},
            **(changes or {}),
        }
    return Decision.from_json({
        "response_type": "decision", "protocol": "spellbench/v1", "request_id": f"e-{step}",
        "game_id": GAME_ID, "step": step, "acting_seat": acting_seat,
        "group": {"group_id": step, "substep_index": 0, "substep_count": 1},
        "state_summary": {"turn": 1, "phase_step": "precombat_main", "active_seat": "p0",
                          "priority_seat": acting_seat, "seats": seats, "stack_count": 0},
        "candidates": candidates, "candidates_sha256": wire.candidates_sha256(candidates),
        "provenance": {"engine_name": "mtg-kernel", "engine_version": "0.0.4-spike",
                       "rules_snapshot_id": KERNEL_ENGINE["rules_snapshot_id"],
                       "card_pool_identity": KERNEL_ENGINE["card_pool_identity"]},
        "extensions": extensions,
    })


def start(agent: AgentProcess, engine: dict = KERNEL_ENGINE) -> None:
    agent.hello()
    agent.game_start(game_id=GAME_ID, seat="p0", format="pauper-bo1",
                     decks=[{"catalog_id": "Burn"}, {"catalog_id": "Burn"}], engine=engine)


def spawn(argv: list[str]) -> tuple[AgentProcess, wire.SubprocessPeer]:
    """An agent client that keeps its peer: the bot states its reasons on stderr."""
    peer = wire.SubprocessPeer(argv, timeout_s=30)
    return AgentProcess(peer=peer), peer


def stderr_names(peer: wire.SubprocessPeer, reason: str) -> bool:
    """Whether the bot's stderr names reason (its reader thread may trail stdout)."""
    deadline = time.monotonic() + 10
    while reason not in peer.stderr_text():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.02)
    return True


def assert_choose_refused(argv: list[str], decision: Decision, reason: str) -> None:
    """The bot answers the decision with internal_error, never a choice, for reason."""
    agent, peer = spawn(argv)
    with agent:
        start(agent)
        with pytest.raises(RemoteError) as caught:
            agent.choose(decision)
    assert caught.value.code == "internal_error"
    assert stderr_names(peer, reason), peer.stderr_text()


def assert_exits_before_hello(argv: list[str], reason: str) -> None:
    agent, peer = spawn(argv)
    with agent:
        with pytest.raises(TransportError):
            agent.hello()
    assert stderr_names(peer, reason), peer.stderr_text()


def test_seat_stream_seed_matches_the_pinned_vectors() -> None:
    assert bot_module.seat_stream_seed(0, GAME_ID, "p0") == 6130830677676653025
    assert bot_module.seat_stream_seed(0, GAME_ID, "p1") == 14732225731661844387
    rng = bot_module.SplitMix64(6130830677676653025)
    assert [rng.next(), rng.next()] == [14661015056425920609, 10495553203978975665]


def test_choose_maps_the_scorer_row_through_row_candidate_ids(tmp_path: Path) -> None:
    with AgentProcess(bot_argv(tmp_path, log=tmp_path / "log"), timeout_s=30) as agent:
        start(agent)
        selection = agent.choose(make_decision([1, 2, 0]))
    # First draw 14661015056425920609 % 3 == 0: row 0, which is candidate 1.
    assert selection.candidate_id == 1
    lines = (tmp_path / "log" / f"{GAME_ID}.p0.jsonl").read_text(encoding="utf-8").splitlines()
    header, entry = json.loads(lines[0]), json.loads(lines[1])
    assert header["schema"] == "spellbench-kernel-bot-log/v1"
    assert header["stream_seed"] == 6130830677676653025
    assert header["selection"] == "sampled-wide-v1"
    assert (entry["sample_seed"], entry["selected_row"], entry["candidate_id"]) == (14661015056425920609, 0, 1)


def test_argmax_selection_sends_no_seed_and_maps_the_row(tmp_path: Path) -> None:
    # The argmax fake answers the last row, and refuses a request that carries a seed.
    with AgentProcess(bot_argv(tmp_path, mode="argmax", log=tmp_path / "log"), timeout_s=30) as agent:
        start(agent)
        selection = agent.choose(make_decision([1, 2, 0]))
    assert selection.candidate_id == 0
    lines = (tmp_path / "log" / f"{GAME_ID}.p0.jsonl").read_text(encoding="utf-8").splitlines()
    header, entry = json.loads(lines[0]), json.loads(lines[1])
    assert header["selection"] == "argmax-first-v1"
    assert (entry["sample_seed"], entry["selected_row"], entry["candidate_id"]) == (None, 2, 0)


def test_missing_extension_is_an_internal_error(tmp_path: Path) -> None:
    # The arena records only "choose failed: BotError"; the reason, naming the flag, is on stderr.
    assert_choose_refused(bot_argv(tmp_path), make_decision(None), "run the bridge with --x-kernel-flat-v4")


def test_row_map_outside_the_candidates_is_refused(tmp_path: Path) -> None:
    with AgentProcess(bot_argv(tmp_path), timeout_s=30) as agent:
        start(agent)
        with pytest.raises(RemoteError) as caught:
            agent.choose(make_decision([0, 5]))
    assert caught.value.code == "internal_error"


TENSOR = {key: [] for key in sorted(bot_module.TENSOR_KEYS)}
IDENTITY = "x_kernel_flat_v4 identity does not match the model"
SEAT = "x_kernel_flat_v4 is not for this seat"
NOT_A_MAP = "row_candidate_ids is not an injective map into the candidates"
TENSOR_FIELDS = "tensor fields differ from the V4 wire"
# x_kernel_flat_v4 field changes the bot must refuse, each with the reason it states.
REFUSED_EXTENSIONS = {
    "schema": ({"schema": "mtg-kernel-spellbench-flat-v4/v2"}, IDENTITY),
    "contract-digest": ({"feature_contract_digest": "0" * 64}, IDENTITY),
    "encoding-digest": ({"feature_encoding_digest": "0" * 64}, IDENTITY),
    "card-db": ({"card_db_hash": "64c82a261e078f1a"}, IDENTITY),
    "seat": ({"acting_seat": "p1"}, SEAT),
    "step": ({"step": 1}, "x_kernel_flat_v4 is not for this step"),
    "rows-duplicate": ({"row_candidate_ids": [1, 1]}, NOT_A_MAP),
    "rows-empty": ({"row_candidate_ids": []}, NOT_A_MAP),
    "rows-not-a-list": ({"row_candidate_ids": 1}, NOT_A_MAP),
    "rows-bool": ({"row_candidate_ids": [True, 2]}, NOT_A_MAP),
    "rows-negative": ({"row_candidate_ids": [-1, 0]}, NOT_A_MAP),
    "rows-past-end": ({"row_candidate_ids": [0, 3]}, NOT_A_MAP),
    "tensor-missing-key": ({"tensor": {key: [] for key in TENSOR if key != "state"}}, TENSOR_FIELDS),
    "tensor-extra-key": ({"tensor": dict(TENSOR, opponent_hand=[])}, TENSOR_FIELDS),
    "tensor-key-list": ({"tensor": sorted(TENSOR)}, TENSOR_FIELDS),
}


@pytest.mark.parametrize("case", sorted(REFUSED_EXTENSIONS))
def test_an_extension_that_does_not_fit_the_model_or_the_decision_is_refused(tmp_path: Path, case: str) -> None:
    changes, reason = REFUSED_EXTENSIONS[case]
    assert_choose_refused(bot_argv(tmp_path), make_decision([1, 2, 0], changes=changes), reason)


def test_a_decision_for_the_other_seat_is_refused(tmp_path: Path) -> None:
    # Decision and extension agree on p1, but this bot plays p0.
    assert_choose_refused(bot_argv(tmp_path), make_decision([1, 2, 0], acting_seat="p1"), SEAT)


# fake_scorer.py answer modes the bot must refuse, each with the reason it states.
REFUSED_ANSWERS = {
    "error-record": "scorer answered 'mtg-kernel-spellbench-scorer-error/v1' code 'native_inference'",
    "wrong-schema": "scorer answered 'mtg-kernel-spellbench-scorer-choice/v2' code None",
    "wrong-request-id": "scorer answered 'mtg-kernel-spellbench-scorer-choice/v1' code None",
    "wrong-hash": "scorer hashed a different request",
    "row-past-end": "scorer choice does not match the row map",
    "row-negative": "scorer choice does not match the row map",
    "row-bool": "scorer choice does not match the row map",
    "wrong-candidate": "scorer choice does not match the row map",
}


@pytest.mark.parametrize("mode", sorted(REFUSED_ANSWERS))
def test_a_scorer_answer_that_does_not_fit_the_request_is_refused(tmp_path: Path, mode: str) -> None:
    assert_choose_refused(bot_argv(tmp_path, mode=mode), make_decision([1, 2, 0]), REFUSED_ANSWERS[mode])


def test_wrong_engine_card_registry_fails_game_start(tmp_path: Path) -> None:
    old = dict(KERNEL_ENGINE, rules_snapshot_id="mtg-kernel-rules/0.0.4-spike/carddb-64c82a261e078f1a",
               card_pool_identity="mtg-kernel-pauper-pool-v1/carddb-64c82a261e078f1a")
    with AgentProcess(bot_argv(tmp_path), timeout_s=30) as agent:
        agent.hello()
        with pytest.raises(RemoteError) as caught:
            agent.game_start(game_id=GAME_ID, seat="p0", format="pauper-bo1",
                             decks=[{"catalog_id": "Burn"}, {"catalog_id": "Burn"}], engine=old)
    assert caught.value.code == "internal_error"


def test_another_engine_fails_game_start(tmp_path: Path) -> None:
    agent, peer = spawn(bot_argv(tmp_path))
    with agent:
        with pytest.raises(RemoteError) as caught:
            start(agent, dict(KERNEL_ENGINE, name="xmage"))
    assert caught.value.code == "internal_error"
    assert stderr_names(peer, "engine xmage"), peer.stderr_text()


@pytest.mark.parametrize("mode", ["no-ready", "wrong-digest"])
def test_bot_exits_before_hello_when_the_scorer_never_becomes_ready(tmp_path: Path, mode: str) -> None:
    with AgentProcess(bot_argv(tmp_path, mode=mode), timeout_s=30) as agent:
        with pytest.raises(TransportError):
            agent.hello()


@pytest.mark.parametrize(
    ("mode", "extra", "reason"),
    [
        pytest.param("load-error", (), "'code': 'checkpoint_load'", id="load-error"),
        pytest.param("wrong-encoding", (), "scorer serves a different feature contract", id="wrong-encoding"),
        pytest.param("unknown-selection", (), "unknown scorer selection 'greedy-v1'", id="unknown-selection"),
        pytest.param("wrong-sampler", (), "scorer sampler 'f32-q8-expq63-hamilton-splitmix64-wide-v2'",
                     id="wrong-sampler"),
        pytest.param("wrong-float-encoding", (), "scorer float encoding 'ieee754-binary16-u16-bits'",
                     id="wrong-float-encoding"),
        pytest.param("ok", ("--expect-model-state", "1" * 64),
                     f"scorer loaded model state {'0' * 64}, expected {'1' * 64}", id="other-model-state"),
    ],
)
def test_bot_exits_before_hello_unless_the_scorer_serves_the_pinned_model(
    tmp_path: Path, mode: str, extra: tuple[str, ...], reason: str,
) -> None:
    assert_exits_before_hello(bot_argv(tmp_path, mode=mode, extra=extra), reason)


def test_the_expected_model_state_admits_its_model(tmp_path: Path) -> None:
    with AgentProcess(bot_argv(tmp_path, extra=("--expect-model-state", "0" * 64)), timeout_s=30) as agent:
        start(agent)
        assert agent.choose(make_decision([1, 2, 0])).candidate_id == 1


def test_a_bare_scorer_name_is_found_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if os.name == "nt":  # a .cmd is found only through PATHEXT, which CreateProcess does not apply
        (bin_dir / "kernel-fake-scorer.cmd").write_text(f'@"{sys.executable}" "{FAKE}" %*\n', encoding="utf-8")
    else:
        launcher = bin_dir / "kernel-fake-scorer"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    argv = [
        sys.executable, str(BOT), "--scorer", "kernel-fake-scorer", "--config", str(tmp_path / "unused.json"),
        "--name", "g115-test", "--version", "1.0.0",
    ]
    with AgentProcess(argv, timeout_s=30) as agent:
        start(agent)
        assert agent.choose(make_decision([1, 2, 0])).candidate_id == 1


def test_scorer_death_mid_game_is_an_internal_error(tmp_path: Path) -> None:
    with AgentProcess(bot_argv(tmp_path, mode="die-after-1"), timeout_s=30) as agent:
        start(agent)
        agent.choose(make_decision([1, 2, 0], step=0))
        with pytest.raises(RemoteError) as caught:
            agent.choose(make_decision([1, 2, 0], step=1))
    assert caught.value.code == "internal_error"
