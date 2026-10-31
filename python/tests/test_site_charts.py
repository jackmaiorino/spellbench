"""Hero charts: drawn from leaderboards and filed human sessions, never from hand-entered numbers."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from spellbench.site import charts


def row(name, elo, ci=(None, None), *, wins=10, losses=10, draws=0, rated=True, games=None):
    return {"name": name, "elo_milli": round(elo * 1000), "rated": rated, "wins": wins, "losses": losses,
            "draws": draws, "games": games if games is not None else wins + losses + draws,
            "ci95_elo_milli": None if ci[0] is None else [round(ci[0] * 1000), round(ci[1] * 1000)]}


def board(*rows, anchor="uniform"):
    return {"anchor": {"name": anchor, "bot_id": "a" * 64}, "status": "ok", "rows": list(rows),
            "evaluation": {"caveat": "Ladder rating: fixture caveat"}}


BOARD = board(row("uniform", 1000, (1000, 1000)), row("heuristic", 1120, (1060, 1180)),
              row("strong", 1500, (1440, 1560)), row("perfect", 1800, wins=20, losses=0),
              row("unplayed", 1300, rated=False))


def ledger_row(human_seat, winner, classification="natural", opponent="strong"):
    seats = [{"seat": "p0", "name": "human" if human_seat == "p0" else opponent},
             {"seat": "p1", "name": opponent if human_seat == "p0" else "human"}]
    return {"seats": seats, "winner": winner, "classification": classification}


def session(rows, name="s1"):
    return charts.HumanSession(name, "human", "fixture clock: bank 30 min", tuple(rows))


def test_benchmark_chart_draws_every_rated_row_with_bounds_and_the_heuristic_line():
    svg = charts.benchmark_chart("fixture", "Fixture board", BOARD, label="snapshots/2026-10-01",
                                 references=("uniform", "heuristic"))
    assert svg.startswith("<svg") and svg.count("<g><title>") == 4
    assert "unplayed" not in svg
    assert "&gt; 1800 (bound)" in svg  # all wins: a lower bound, not an interval
    assert "1500 [1440, 1560]" in svg
    assert 'class="ref"' in svg and "heuristic is not on this board" not in svg
    assert "strong (reference)" not in svg and "heuristic (reference)" in svg
    assert "UNRATED PREVIEW" not in svg
    assert charts.benchmark_chart("fixture", "t", BOARD, label="x") == charts.benchmark_chart(
        "fixture", "t", BOARD, label="x")  # deterministic


def test_missing_heuristic_and_previews_are_labelled():
    plain = board(row("uniform", 1000, (1000, 1000)), row("strong", 1500, (1440, 1560)))
    svg = charts.benchmark_chart("fixture", "t", plain, label="runs/2026-10-01", preview=True)
    assert "heuristic is not on this board" in svg and "UNRATED PREVIEW" in svg


def test_human_records_count_natural_results_and_other_endings_apart():
    rows = [ledger_row("p0", "p0"), ledger_row("p1", "p1")] + [ledger_row("p0", "p1", "forfeit")] * 6
    records = charts.human_records([session(rows)])
    assert len(records) == 1
    record = records[0]
    assert (record.wins, record.losses, record.draws, record.other) == (2, 0, 0, {"forfeit": 6})
    svg = charts.benchmark_chart("fixture", "t", BOARD, label="x", sessions=[session(rows)])
    assert "human 2-0 (+6 forfeit)" in svg and "fixture clock: bank 30 min" in svg
    assert "(human, descriptive)" not in svg  # fewer than HUMAN_ESTIMATE_GAMES natural games


def test_human_estimate_needs_enough_games_and_bounds_a_perfect_record():
    wins = [ledger_row("p0", "p0")] * 10
    svg = charts.benchmark_chart("fixture", "t", BOARD, label="x", sessions=[session(wins)])
    assert "human (human, descriptive)" in svg and "(bound), 10 games" in svg
    value, lower, upper, bound = charts.human_estimate([(1500.0, 1.0)] * 10)
    assert value is None and upper is None and bound == "lower" and 1500 < lower < 1900
    mixed = [(1500.0, 1.0)] * 6 + [(1500.0, 0.0)] * 4
    value, lower, upper, bound = charts.human_estimate(mixed)
    assert bound is None and lower < value < upper
    assert math.isclose(value, 1500 + 400 * math.log10(6 / 4), abs_tol=0.5)


def test_track_chart_reports_coverage_and_warnings(tmp_path):
    second = board(row("uniform", 1000, (1000, 1000)), row("strong", 1300, (1250, 1350)),
                   row("heuristic", 1100, (1050, 1150)))
    svg, warnings = charts.track_chart({"id": "t", "title": "Track"}, [("one", BOARD), ("two", second)])
    assert "2/2 boards" in svg and "1/2 boards" in svg and "approx." in svg
    assert "descriptive, not a common strength rating" in svg
    assert warnings == ()


def test_tracks_file_is_checked(tmp_path):
    assert charts.load_tracks(tmp_path) == []
    (tmp_path / "tracks.json").write_text(json.dumps({"schema": "spellbench-tracks/v1", "tracks": [
        {"id": "a", "title": "A", "benchmarks": []}]}), encoding="utf-8")
    with pytest.raises(charts.ChartError, match="nonempty benchmarks"):
        charts.load_tracks(tmp_path)


def test_filed_session_round_trips(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    rows = [ledger_row("p0", "p0"), ledger_row("p1", "p0")]
    (run / "matches.jsonl").write_bytes(b"".join(
        json.dumps(item, separators=(",", ":"), sort_keys=True).encode() + b"\n" for item in rows))
    target = tmp_path / "bench" / "human" / "s1"
    charts.write_session(run, target, human="human", conditions="fixture", note="evaluation only")
    loaded = charts.load_human_sessions(tmp_path / "bench")
    assert [s.name for s in loaded] == ["s1"]
    record = charts.human_records(loaded)[0]
    assert (record.wins, record.losses) == (1, 1)
