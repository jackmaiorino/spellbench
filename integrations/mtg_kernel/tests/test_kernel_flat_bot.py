from __future__ import annotations

import json
import sys
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


def bot_argv(tmp_path: Path, mode: str = "ok", log: Path | None = None) -> list[str]:
    argv = [
        sys.executable, str(BOT), "--scorer", sys.executable, "--scorer-arg", str(FAKE),
        "--scorer-arg=--mode", f"--scorer-arg={mode}", "--config", str(tmp_path / "unused.json"),
        "--name", "g115-test", "--version", "1.0.0",
    ]
    return argv + (["--decision-log", str(log)] if log is not None else [])


def make_decision(rows: list[int] | None, *, step: int = 0) -> Decision:
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
            "card_db_hash": "064a7c989255ab3c", "acting_seat": "p0", "step": step,
            "row_candidate_ids": rows, "tensor": {key: [] for key in sorted(bot_module.TENSOR_KEYS)},
        }
    return Decision.from_json({
        "response_type": "decision", "protocol": "spellbench/v1", "request_id": f"e-{step}",
        "game_id": GAME_ID, "step": step, "acting_seat": "p0",
        "group": {"group_id": step, "substep_index": 0, "substep_count": 1},
        "state_summary": {"turn": 1, "phase_step": "precombat_main", "active_seat": "p0",
                          "priority_seat": "p0", "seats": seats, "stack_count": 0},
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


def test_missing_extension_is_an_internal_error(tmp_path: Path) -> None:
    with AgentProcess(bot_argv(tmp_path), timeout_s=30) as agent:
        start(agent)
        with pytest.raises(RemoteError) as caught:
            agent.choose(make_decision(None))
    assert caught.value.code == "internal_error"


def test_row_map_outside_the_candidates_is_refused(tmp_path: Path) -> None:
    with AgentProcess(bot_argv(tmp_path), timeout_s=30) as agent:
        start(agent)
        with pytest.raises(RemoteError) as caught:
            agent.choose(make_decision([0, 5]))
    assert caught.value.code == "internal_error"


def test_wrong_engine_card_registry_fails_game_start(tmp_path: Path) -> None:
    old = dict(KERNEL_ENGINE, rules_snapshot_id="mtg-kernel-rules/0.0.4-spike/carddb-64c82a261e078f1a",
               card_pool_identity="mtg-kernel-pauper-pool-v1/carddb-64c82a261e078f1a")
    with AgentProcess(bot_argv(tmp_path), timeout_s=30) as agent:
        agent.hello()
        with pytest.raises(RemoteError) as caught:
            agent.game_start(game_id=GAME_ID, seat="p0", format="pauper-bo1",
                             decks=[{"catalog_id": "Burn"}, {"catalog_id": "Burn"}], engine=old)
    assert caught.value.code == "internal_error"


@pytest.mark.parametrize("mode", ["no-ready", "wrong-digest"])
def test_bot_exits_before_hello_when_the_scorer_never_becomes_ready(tmp_path: Path, mode: str) -> None:
    with AgentProcess(bot_argv(tmp_path, mode=mode), timeout_s=30) as agent:
        with pytest.raises(TransportError):
            agent.hello()


def test_scorer_death_mid_game_is_an_internal_error(tmp_path: Path) -> None:
    with AgentProcess(bot_argv(tmp_path, mode="die-after-1"), timeout_s=30) as agent:
        start(agent)
        agent.choose(make_decision([1, 2, 0], step=0))
        with pytest.raises(RemoteError) as caught:
            agent.choose(make_decision([1, 2, 0], step=1))
    assert caught.value.code == "internal_error"
