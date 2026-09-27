"""The committed protocol v1 run stays checkable after v1 code is gone."""

from __future__ import annotations

import ast
import hashlib
import shutil
from pathlib import Path

import pytest

import spellbench
from spellbench.arena import legacy_v1, store
from spellbench.arena.validate import validate_tournament_dir

REPO = Path(__file__).resolve().parents[2]
LAUNCH_RUN = REPO / "benchmarks" / "pauper-kernel" / "runs" / "2026-09-26"
# Every committed v1 run, including any that sub-project C commits before P merges.
V1_RUNS = sorted(path.parent for path in REPO.glob("benchmarks/*/runs/*/manifest.json")
                 if b'"schema":"spellbench-tournament/v1"' in path.read_bytes())
DECKLIST = {"decklist": [{"name": "Lightning Bolt", "count": 60}]}
DECKLIST_LABEL = "decklist " + hashlib.sha256(store.canonical_bytes(DECKLIST)).hexdigest()[:12]


@pytest.mark.parametrize("run", V1_RUNS, ids=lambda path: f"{path.parents[1].name}/{path.name}")
def test_every_committed_v1_run_validates_through_the_legacy_path(run: Path) -> None:
    assert legacy_v1.validate_v1_run(run) == []
    assert validate_tournament_dir(run) == []


def test_a_tampered_v1_run_fails(tmp_path: Path) -> None:
    copy = tmp_path / "run"
    shutil.copytree(LAUNCH_RUN, copy)
    ledger = copy / "matches.jsonl"
    ledger.write_bytes(ledger.read_bytes().replace(b'"reason":"game_over"', b'"reason":"game over"', 1))
    failures = legacy_v1.validate_v1_run(copy)
    assert any("digest mismatch: matches.jsonl" in failure for failure in failures)


def test_a_later_package_version_still_validates_the_v1_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    # A later release bumps spellbench.__version__; the gate compares with the
    # version that made the v1 runs. Patch any copy the module could have bound too.
    monkeypatch.setattr(spellbench, "__version__", "0.3.0")
    monkeypatch.setattr(legacy_v1, "__version__", "0.3.0", raising=False)
    assert legacy_v1.validate_v1_run(LAUNCH_RUN) == []


@pytest.mark.parametrize("package_version", ["0.2.0", "0.3.0"])
def test_a_v1_run_made_by_another_arena_version_gets_one_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, package_version: str
) -> None:
    monkeypatch.setattr(spellbench, "__version__", package_version)
    copy = tmp_path / "run"
    shutil.copytree(LAUNCH_RUN, copy)
    manifest = store.read_json(copy / "manifest.json")
    manifest["tournament"]["arena_version"] = "0.1.0"
    (copy / "manifest.json").write_bytes(store.canonical_bytes(manifest) + b"\n")
    assert legacy_v1.validate_v1_run(copy) == [
        f"this run was made by spellbench arena 0.1.0; this is {package_version}: "
        "rerun the benchmark, or validate with arena 0.1.0"
    ]


def test_read_v1_run_gives_the_site_what_it_shows() -> None:
    run = legacy_v1.read_v1_run(LAUNCH_RUN)
    assert run.name == "2026-09-26" and run.format == "pauper-bo1"
    assert run.deck_labels == ("Wildfire", "Rally", "Affinity", "Elves", "Spy", "Burn", "CawGates", "Faeries")
    assert run.pairs_per_deck == 4
    assert run.engine["name"] == "mtg-kernel" and run.board["status"] == "ok"
    assert run.owners == {"uniform": "spellbench", "heuristic": "spellbench", "first": "spellbench"}


@pytest.mark.parametrize(("second", "label"), [({"catalog_id": "Burn"}, "Burn"), (DECKLIST, f"Burn vs {DECKLIST_LABEL}")],
                         ids=["mirror", "decklist"])
def test_read_v1_run_labels_a_fixed_deck_pair(tmp_path: Path, second: dict, label: str) -> None:
    copy = tmp_path / "run"
    shutil.copytree(LAUNCH_RUN, copy)
    config = store.read_json(copy / "config.json")
    del config["deck_pool"]
    config.update(decks=[{"catalog_id": "Burn"}, second], pairs_per_matchup=3)
    (copy / "config.json").write_bytes(store.canonical_bytes(config) + b"\n")
    run = legacy_v1.read_v1_run(copy)
    assert (run.deck_labels, run.pairs_per_deck) == ((label,), 3)


def test_ledger_rows_expose_the_pair_slot() -> None:
    rows = legacy_v1.parse_ledger(store.read_jsonl(LAUNCH_RUN / "matches.jsonl", schema=legacy_v1.LEDGER_SCHEMA_V1))
    assert [row.pair_slot for row in rows[:2]] == [0, 1]


def test_the_legacy_module_imports_no_protocol_v1_code() -> None:
    tree = ast.parse(Path(legacy_v1.__file__).read_text(encoding="utf-8"))
    imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
    assert not {"models", "runner", "bots", "engine_client", "agent_client", "agent_server"} & (imported | names)
