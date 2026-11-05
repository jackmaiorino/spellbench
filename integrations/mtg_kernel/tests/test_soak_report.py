"""soak_report.py: the W1 AC5 soak computation (gate packet 10.20 R4).

Fixtures (tests/fixtures/w1_soak): two unrated smoke runs of the entrant
(kernel c0bd173da, spellbench 7622ab437), their decision logs trimmed to the
records the reports read, with their ledgers and engine-side receipts. ``k1``
is the 4k-k1 run (4 ledger games, 2 qualification logs), ``k4`` the 16k-k4
run (2 ledger games, one ``R1:same_name_batch`` fault, 2 qualification logs).
"""
from __future__ import annotations

import hashlib
import json
import random
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import entrant_availability
import soak_report

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "w1_soak"
NAMES = {"k1": "w1-4k-k1", "k4": "w1-16k-k4"}


def run(label: str, root: Path = FIXTURES, **kwargs):
    base = root / label
    return soak_report.soak_report([base / "decisions"], base / "matches.jsonl", NAMES[label], base / "receipts",
                                   **kwargs)


def copy_fixture(label: str, tmp_path: Path) -> Path:
    shutil.copytree(FIXTURES / label, tmp_path / label)
    return tmp_path


def test_k1_matches_the_recorded_smoke():
    result = run("k1", expect_games=4)
    assert result["checks_pass"], result["checks"]
    assert result["ac5_bound"]["units"] == 361 and result["ac5_bound"]["faults"] == 0
    assert result["ac5_bound"]["cp_upper_95"] == pytest.approx(0.008264, abs=1e-6)
    assert result["ac5_bound"]["pass"] is True
    assert result["r3b_own"] == 4 and result["r3_opponent"] == 0
    assert result["own_share"] == pytest.approx(4 / 365)
    assert result["own_share_over_2pct"] is False
    assert result["receipts_reconcile"] is True
    assert result["outcomes"] == {"win": 4, "loss": 0, "draw": 0, "halted": 0, "truncated": 0}
    assert result["refusals_by_subclass"] == {"R3b:own_library_search": 4}
    assert result["bootstrap"]["upper_95"] == 0.0


def test_qualification_logs_are_not_units():
    everything = entrant_availability.report([FIXTURES / "k1" / "decisions"])
    result = run("k1")
    assert everything["games"] == 6 and result["counted_games"] == 4
    assert everything["eligible"] > result["ac5_bound"]["units"]
    assert result["logs"]["excluded"] == 2 and result["availability"]["logs"]["unledgered"] == []


def test_k4_counts_the_r1_subclass_as_a_fault_and_fails_the_bound():
    result = run("k4")
    assert result["checks_pass"], result["checks"]
    assert (result["ac5_bound"]["units"], result["ac5_bound"]["faults"]) == (203, 1)
    assert result["ac5_bound"]["cp_upper_95"] == pytest.approx(0.023154, abs=1e-6)
    assert result["ac5_bound"]["pass"] is False
    assert result["faults_by_reason"] == {"R1": 1}
    assert result["refusals_by_subclass"]["R1:same_name_batch"] == 1
    assert result["own_share_over_2pct"] is True
    per_game = result["bootstrap"]["per_game"]
    assert sum(g["faults"] for g in per_game) == 1 and sum(g["units"] for g in per_game) == 203


def test_r3_and_r3b_are_not_units_and_other_refusals_are_faults():
    # The bot's rule, which the report sums: R3 opponent and R3b own are not faults; every other code is.
    import kernel_search_bot as bot
    assert not bot.is_fault("R3") and not bot.is_fault("R3b")
    for code in ("R1", "R1b", "R2", "R4", "R5", "R6", "R7", "R8", "R8b", "order_map_missing", "no_match",
                 "group_lost", "composition_cap", "no_completions", "missing_preview_keys", "tree_fault",
                 "R9-unknown"):
        assert bot.is_fault(code)
    result = run("k1")
    assert result["ac5_bound"]["units"] == result["availability"]["eligible"]


def test_the_bound_passes_at_one_percent(monkeypatch):
    monkeypatch.setattr(entrant_availability, "upper_bound_95", lambda faults, n: 0.01)
    assert run("k1")["ac5_bound"]["pass"] is True
    monkeypatch.setattr(entrant_availability, "upper_bound_95", lambda faults, n: 0.0100001)
    assert run("k1")["ac5_bound"]["pass"] is False


def test_bootstrap_is_the_declared_procedure():
    pairs = [(0, 90), (1, 80), (0, 100), (2, 70), (0, 95)]
    expected_rng = random.Random(20261105)
    ratios = []
    for _ in range(10_000):
        draw = [pairs[expected_rng.randrange(5)] for _ in range(5)]
        ratios.append(sum(f for f, _ in draw) / sum(u for _, u in draw))
    ratios.sort()
    assert soak_report.cluster_bootstrap_upper(pairs) == ratios[9499]
    assert soak_report.cluster_bootstrap_upper(pairs) == soak_report.cluster_bootstrap_upper(list(pairs))
    assert soak_report.cluster_bootstrap_upper([(0, 10)] * 3) == 0.0
    assert soak_report.cluster_bootstrap_upper([(0, 0)]) == 1.0
    assert soak_report.cluster_bootstrap_upper([]) is None


def test_nearest_rank():
    assert soak_report.nearest_rank(list(range(1, 33)), 0.99) == 32
    assert soak_report.nearest_rank(list(range(1, 101)), 0.99) == 99
    assert soak_report.nearest_rank([3.0], 0.5) == 3.0
    assert soak_report.nearest_rank([], 0.99) is None


def test_wall_subset_takes_the_smallest_hashes():
    ids = [f"g-{i:016x}" for i in range(100)]
    subset = soak_report.wall_subset(ids)
    digests = sorted((hashlib.sha256(f"w1-ac5-wall:{g}".encode()).hexdigest(), g) for g in ids)
    assert [s["game_id"] for s in subset] == [g for _, g in digests[:32]]
    assert [s["sha256"] for s in subset] == [d for d, _ in digests[:32]]
    assert len(soak_report.wall_subset(ids[:4])) == 4
    assert soak_report.wall_subset(list(reversed(ids))) == subset


def _set_wall(tmp: Path, label: str, game: str, seconds: float) -> None:
    for path in (tmp / label / "decisions").glob(f"{game}.*.jsonl"):
        lines = path.read_text(encoding="utf-8").splitlines()
        final = json.loads(lines[-1])
        final["charged_wall_us"] = int(seconds * 1e6)
        lines[-1] = json.dumps(final)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_wall_check_uses_the_rerun_logs_and_the_criterion(tmp_path):
    rerun = copy_fixture("k1", tmp_path)
    games = sorted(json.loads(line)["game_id"] for line in (FIXTURES / "k1" / "matches.jsonl").read_text().splitlines())
    base = dict(wall_logs=[rerun / "k1" / "decisions"])
    assert run("k1", **base)["wall"]["check"]["pass"] is True
    # One game over T with no cause: p99 (the maximum at this size) fails too.
    _set_wall(rerun, "k1", games[0], 600.0)
    check = run("k1", **base)["wall"]["check"]
    assert check["over_t_without_cause"] == [games[0]]
    assert check["p99_at_or_below_t"] is False and check["max_at_or_below_1_5t"] is True and not check["pass"]
    # A cause does not rescue p99 above T.
    assert run("k1", wall_causes={games[0]: "noted"}, **base)["wall"]["check"]["pass"] is False
    # At exactly T the game is not over it.
    _set_wall(rerun, "k1", games[0], 500.0)
    check = run("k1", **base)["wall"]["check"]
    assert check["p99_at_or_below_t"] is True and check["over_t"] == [] and check["pass"]
    _set_wall(rerun, "k1", games[0], 800.0)
    check = run("k1", **base)["wall"]["check"]
    assert check["max_at_or_below_1_5t"] is False
    # The soak host's walls are reported apart from the rerun's.
    assert run("k1", **base)["wall"]["soak_host"]["max"] < 500


def test_wall_check_fails_when_a_subset_game_was_not_rerun(tmp_path):
    rerun = copy_fixture("k1", tmp_path)
    game = soak_report.wall_subset([json.loads(line)["game_id"] for line in
                                    (FIXTURES / "k1" / "matches.jsonl").read_text().splitlines()])[0]["game_id"]
    for path in (rerun / "k1" / "decisions").glob(f"{game}.*.jsonl"):
        path.unlink()
    result = run("k1", wall_logs=[rerun / "k1" / "decisions"])
    assert result["wall"]["check"]["missing_games"] == [game]
    assert result["wall"]["check"]["pass"] is False
    assert result["checks"]["wall_subset_rerun_complete"] is False and not result["checks_pass"]


def test_expected_game_count_and_main_exit(tmp_path):
    assert run("k1", expect_games=128)["checks"]["games_expected"] is False
    base = FIXTURES / "k1"
    args = [str(base / "decisions"), "--ledger", str(base / "matches.jsonl"), "--entrant", NAMES["k1"],
            "--receipts", str(base / "receipts"), "--json", str(tmp_path / "out.json")]
    assert soak_report.main(args) == 0
    assert json.loads((tmp_path / "out.json").read_text())["ac5_bound"]["units"] == 361
    assert soak_report.main(args + ["--expect-games", "128"]) == 1


def test_a_missing_receipt_fails_reconciliation(tmp_path):
    root = copy_fixture("k1", tmp_path)
    next((root / "k1" / "receipts").glob("*.bridge.json")).unlink()
    result = run("k1", root=root)
    assert result["receipts_reconcile"] is False and not result["checks_pass"]


def test_clock_forfeits_are_counted(tmp_path):
    root = copy_fixture("k1", tmp_path)
    ledger = root / "k1" / "matches.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    row = rows[0]
    seat = next(s["seat"] for s in row["seats"] if s["name"] == NAMES["k1"])
    row.update(classification="forfeit", winner="p1" if seat == "p0" else "p0",
               adjudication={"kind": "forfeit", "cause": "timeout", "loser_seat": seat, "detail": "bank"})
    ledger.write_text("".join(json.dumps(r) + "\n" for r in rows))
    result = run("k1", root=root)
    assert result["clock_forfeits"] == 1
    assert result["forfeits"] == [{"game_id": row["game_id"], "cause": "timeout", "entrant_lost": True}]
    assert result["outcomes"]["loss"] == 1 and result["outcomes"]["win"] == 3


def test_duplicate_ledger_rows_do_not_make_up_the_game_count(tmp_path):
    root = copy_fixture("k1", tmp_path)
    ledger = root / "k1" / "matches.jsonl"
    ledger.write_text(ledger.read_text() * 32)
    result = run("k1", root=root, expect_games=128)
    assert result["checks"]["ledger_games_unique"] is False
    assert result["checks"]["games_expected"] is False and not result["checks_pass"]


def test_a_missing_wall_measurement_fails(tmp_path):
    rerun = copy_fixture("k1", tmp_path)
    path = sorted((rerun / "k1" / "decisions").glob("*.jsonl"))[0]
    lines = path.read_text().splitlines()
    final = json.loads(lines[-1])
    del final["charged_wall_us"]
    lines[-1] = json.dumps(final)
    path.write_text("\n".join(lines) + "\n")
    game = final["game_id"]
    result = run("k1", wall_logs=[rerun / "k1" / "decisions"])
    assert game in result["wall"]["check"]["unmeasured_games"]
    assert game in result["wall"]["check"]["missing_games"] and not result["wall"]["check"]["pass"]
    soak = run("k1", root=rerun)
    assert soak["checks"]["every_game_wall_measured"] is False and not soak["checks_pass"]


def test_conflicting_rerun_logs_fail(tmp_path):
    fast = copy_fixture("k1", tmp_path / "fast")
    slow = copy_fixture("k1", tmp_path / "slow")
    for path in (slow / "k1" / "decisions").glob("*.jsonl"):
        _set_wall(slow, "k1", path.name.split(".")[0], 900.0)
    for order in ([fast, slow], [slow, fast]):
        check = run("k1", wall_logs=[d / "k1" / "decisions" for d in order])["wall"]["check"]
        assert check["duplicate_logs"] and check["pass"] is False


def test_t_is_the_design_constant(tmp_path):
    root = copy_fixture("k1", tmp_path)
    for path in (root / "k1" / "decisions").glob("*.jsonl"):
        lines = path.read_text().splitlines()
        out = []
        for line in lines:
            record = json.loads(line)
            if record.get("kind") == "entrant":
                record["entrant"]["game_time_basis_seconds"] = 600
            out.append(json.dumps(record))
        path.write_text("\n".join(out) + "\n")
    result = run("k1", root=root, wall_logs=[root / "k1" / "decisions"])
    assert result["checks"]["t_is_the_design_t"] is False and not result["checks_pass"]
    assert result["wall"]["check"]["t_seconds"] == 500.0


def _ledger_ids(label: str) -> list[str]:
    return [json.loads(line)["game_id"] for line in (FIXTURES / label / "matches.jsonl").read_text().splitlines()]


def _qualification_log(root: Path, label: str) -> Path:
    ids = set(_ledger_ids(label))
    return next(p for p in (root / label / "decisions").glob("*.jsonl") if p.name.split(".")[0] not in ids)


def test_a_rerun_with_other_entrant_constants_fails(tmp_path):
    rerun = copy_fixture("k1", tmp_path)
    for path in (rerun / "k1" / "decisions").glob("*.jsonl"):
        out = []
        for line in path.read_text().splitlines():
            record = json.loads(line)
            if record.get("kind") == "entrant":
                record["entrant"]["budget"] = 1
            out.append(json.dumps(record))
        path.write_text("\n".join(out) + "\n")
    result = run("k1", wall_logs=[rerun / "k1" / "decisions"])
    check = result["wall"]["check"]
    assert len(check["not_the_soak_game"]) == 4 and check["pass"] is False
    assert result["checks"]["wall_rerun_same_game"] is False and not result["checks_pass"]


def test_an_incomplete_extra_rerun_log_fails(tmp_path):
    rerun = copy_fixture("k1", tmp_path / "a")
    aborted = copy_fixture("k1", tmp_path / "b")
    for path in (aborted / "k1" / "decisions").glob("*.jsonl"):
        lines = path.read_text().splitlines()
        path.write_text("\n".join(lines[:-1]) + "\n")
    check = run("k1", wall_logs=[rerun / "k1" / "decisions", aborted / "k1" / "decisions"])["wall"]["check"]
    assert check["duplicate_logs"] and check["pass"] is False
    alone = run("k1", wall_logs=[aborted / "k1" / "decisions"])["wall"]["check"]
    assert len(alone["incomplete_logs"]) == 4 and alone["pass"] is False


def test_a_torn_qualification_log_is_excluded_and_a_torn_counted_log_fails(tmp_path):
    root = copy_fixture("k1", tmp_path)
    qualification = _qualification_log(root, "k1")
    qualification.write_text(qualification.read_text() + '{"kind": "sear')
    result = run("k1", root=root, expect_games=4)
    assert result["checks_pass"], result["checks"]
    assert result["ac5_bound"]["units"] == 361
    counted = next((root / "k1" / "decisions").glob(f"{_ledger_ids('k1')[0]}.*.jsonl"))
    counted.write_text(counted.read_text() + '{"kind": "sear')
    result = run("k1", root=root)
    assert result["checks"]["counted_logs_parse"] is False and not result["checks_pass"]
    assert result["logs"]["problems"]["malformed"] == [counted.name]


def _edit_logs(root: Path, label: str, edit) -> None:
    for path in (root / label / "decisions").glob("*.jsonl"):
        records = [json.loads(line) for line in path.read_text().splitlines()]
        edit(records)
        path.write_text("".join(json.dumps(r) + "\n" for r in records))


def test_a_rerun_with_another_model_state_or_an_early_end_fails(tmp_path):
    other_model = copy_fixture("k1", tmp_path / "model")
    _edit_logs(other_model, "k1", lambda records: records[0].update(model_state_sha256="0" * 64))
    check = run("k1", wall_logs=[other_model / "k1" / "decisions"])["wall"]["check"]
    assert len(check["not_the_soak_game"]) == 4 and check["pass"] is False

    other_seed = copy_fixture("k1", tmp_path / "seed")
    _edit_logs(other_seed, "k1", lambda records: records[0].update(stream_seed=records[0]["stream_seed"] + 1))
    assert run("k1", wall_logs=[other_seed / "k1" / "decisions"])["wall"]["check"]["pass"] is False

    def stop_early(records):
        records[-1]["eligible"] = 1
        records[-1]["charged_wall_us"] = 1
    early = copy_fixture("k1", tmp_path / "early")
    _edit_logs(early, "k1", stop_early)
    result = run("k1", wall_logs=[early / "k1" / "decisions"])
    assert len(result["wall"]["check"]["not_the_soak_game"]) == 4 and result["wall"]["check"]["pass"] is False
    assert result["checks"]["wall_rerun_same_game"] is False


def test_a_game_seating_the_entrant_twice_fails(tmp_path):
    root = copy_fixture("k1", tmp_path)
    ledger = root / "k1" / "matches.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    for seat in rows[0]["seats"]:
        seat["name"] = NAMES["k1"]
    ledger.write_text("".join(json.dumps(r) + "\n" for r in rows))
    result = run("k1", root=root)
    assert result["checks"]["entrant_one_seat_per_game"] is False and not result["checks_pass"]
