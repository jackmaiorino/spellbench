"""Manifest v2: information rules, the validator verdict, the secrets, the rated rule (spec 11.3, 11.6, 12.2)."""

from __future__ import annotations

import hashlib

import pytest

from spellbench import __version__
from spellbench.arena import manifest
from spellbench.arena.config import TournamentConfig
from spellbench.arena.ledger import parse_ledger
from spellbench.arena.manifest import (
    CommitmentProof, EngineFile, commitment_record, information_rules, is_rated, isolation_record, isolation_refusals,
    manifest_body, run_status, validator_record,
)
from spellbench.arena.throughput import Allocation, MachineFacts, PlayedGame, plan_allocation, spot_check_game
from spellbench.bench import pinning
from spellbench.messages import EngineIdentity, EngineProfile, Rules
from spellbench.run_secret import RunSecret

from test_host_declarations import PROFILE_JSON, RULES_JSON
from test_ledger import VALID, row

DIGEST = "sha256:" + "0" * 64
MACHINE = MachineFacts(memory_bytes=2**36, gpus=(), free_bytes=(("pin_root", 2**42), ("run_dir", 2**42)))


def _play(workers: int, indices: tuple[int, ...]) -> tuple[float, tuple[PlayedGame, ...]]:
    """A fake qualification where every game finishes at once, so the schedule always projects small."""
    games = tuple(PlayedGame(index, 0.01, DIGEST, 10) for index in indices)
    return 0.01 * len(indices), games


def _small_allocation(games_total: int = 4) -> Allocation:
    """A ratable small allocation, built with the final constructors (Task 5): plan one, then pass its spot
    check (the brief's ``Allocation(kind="small", ...)`` and ``Trial(1, 2, 10, digest)`` no longer validate;
    Task 5's allocation carries its qualification rules, a machine snapshot, a budget and a spot check)."""
    allocation = plan_allocation(games_total=games_total, cap=4, per_game_cores=1, play=_play, placement=None,
                                 cpu_count=4, host="h", machine=MACHINE)
    game = spot_check_game(games_total)
    return allocation.with_spot_check(game, recorded_digest=DIGEST, replayed_digest=DIGEST)


SMALL = _small_allocation()
PROOF = CommitmentProof(commit="a" * 40, timestamp="https://github.com/o/r/issues/1#issuecomment-1")
PINNED = (EngineFile(index=0, file_name="engine", sha256="b" * 64, bytes=10),)


def test_information_rules_have_the_spec_12_2_shape() -> None:
    record = information_rules(Rules.from_json(RULES_JSON), EngineProfile.from_json(PROFILE_JSON), [])
    assert set(record) == {"rules", "engine_defaults", "observation", "native_id_extensions", "fairness_label"}
    assert record["rules"] == RULES_JSON and record["fairness_label"] == "validator only"
    assert record["observation"] == PROFILE_JSON["observation"]


def test_the_validator_record() -> None:
    rows = parse_ledger([row(), {**VALID["validator halt"], "game_index": 1}])
    violation = {"game_index": 1, "game_id": rows[1].game_id, "rule": "V4", "detail": "stale reference"}
    assert validator_record(rows[:1], []) == {"version": "spellbench-live-validator/2.0", "verdict": "pass",
                                               "decisions_checked": 4, "violations": []}
    failed = validator_record(rows, [violation])
    assert failed["verdict"] == "fail" and failed["decisions_checked"] == 9 and failed["violations"] == [violation]


@pytest.mark.parametrize(
    ("status", "verdict", "proof", "allocation", "files", "rated"),
    [
        ("complete", "pass", PROOF, SMALL, PINNED, True),
        ("complete", "pass", None, SMALL, PINNED, False),                         # commitment not proven public
        ("complete", "pass", PROOF, Allocation.unmeasured(1, cpu_count=4, host="h"), PINNED, False),
        ("complete", "pass", PROOF, SMALL, (), False),                            # no pinned engine files (R3-7)
        ("invalid", "fail", PROOF, SMALL, PINNED, False),
        ("aborted", "pass", PROOF, SMALL, PINNED, False),
    ],
)
def test_the_rated_rule(status, verdict, proof, allocation, files, rated) -> None:
    assert is_rated(status=status, verdict=verdict, commitment_proof=proof, allocation=allocation, engine_files=files) is rated


def test_run_status_comes_from_the_rows_and_violations_alone() -> None:
    assert run_status(scheduled=4, rows=4, violations=0) == "complete"      # even when interrupted after the last game (R3-13)
    assert run_status(scheduled=4, rows=2, violations=1) == "invalid"
    assert run_status(scheduled=4, rows=2, violations=0) == "aborted"


def test_engine_files_live_in_the_arena_and_read_back_without_a_path() -> None:
    value = {"index": 1, "file_name": "engine.py", "sha256": "a" * 64, "bytes": 16}
    assert EngineFile.from_json(value).to_json() == value and EngineFile.from_json(value).path is None
    assert pinning.EngineFile is manifest.EngineFile                       # bench imports it from arena (R3-4)


def _config(*bots: dict) -> TournamentConfig:
    return TournamentConfig.from_json({"schema": "spellbench-tournament-config/v2", "tournament_dir": "t", "format": "pauper-bo1",
                                       "decks": [{"catalog_id": "Burn"}, {"catalog_id": "Burn"}], "engine": {"command": ["engine"]},
                                       "bots": [{"name": "uniform", "version": "2.0.0", "type": "builtin"}, *bots],
                                       "pairs_per_matchup": 1, "stats_seed": 1})


def test_isolation_labels_each_entry_and_refuses_unvetted_subprocess_bots() -> None:
    config = _config({"name": "kernel", "version": "1", "type": "subprocess", "owner": "jackmaiorino", "command": ["bot"]},
                     {"name": "stranger", "version": "1", "type": "subprocess", "owner": "someone", "command": ["bot"]},
                     {"name": "boxed", "version": "1", "type": "subprocess", "owner": "someone",
                      "command": ["${SPELLBENCH_SANDBOX}", "bot"]})
    assert isolation_record(config) == {"entries": [{"name": "uniform", "isolation": "builtin-in-process"},
                                                    {"name": "kernel", "isolation": "unsandboxed"},
                                                    {"name": "stranger", "isolation": "unsandboxed"},
                                                    {"name": "boxed", "isolation": "verified-sandbox"}],
                                        "self_reported": True}                                  # spec 11.7 (R3-9)
    (refusal,) = isolation_refusals(config)
    assert "stranger" in refusal and "sandbox" in refusal
    assert isolation_record(_config())["self_reported"] is False and isolation_refusals(_config()) == []


def test_the_commitment_record_and_the_proof() -> None:
    secret = RunSecret(bytes(range(32)))
    record = commitment_record(run_secret=secret, benchmark_id="pauper-kernel", run_label="2026-10-01")
    assert record["commitment"] == hashlib.sha256(bytes(range(32))).hexdigest() and "run_secret" not in record
    assert CommitmentProof.from_json(PROOF.to_json()) == PROOF
    with pytest.raises(ValueError):
        CommitmentProof(commit="xyz", timestamp="t")


def test_manifest_body_assembles_every_section() -> None:
    config = _config()
    entries = tuple(bot.registry_entry() for bot in config.bots)
    engine = EngineIdentity(name="engine", version="1", source_revision=None, rules_snapshot_id="r", card_pool_identity="p")
    profile = EngineProfile.from_json(PROFILE_JSON)
    info_rules = information_rules(Rules.from_json(RULES_JSON), profile, [])
    rows = parse_ledger([row()])
    secret = RunSecret(bytes(range(32)))
    body = manifest_body(config=config, entries=entries, anchor_bot_id=entries[0].bot_id, engine=engine, profile=profile,
                         protocol_minor=0, info_rules=info_rules, rows=rows, violations=[], scheduled=1,
                         leaderboard_status="ok", status="complete", benchmark_id="pauper-kernel", run_label="2026-10-01",
                         run_secret=secret, commitment_proof=PROOF, allocation=SMALL, engine_files=PINNED)
    assert set(body) == set(manifest.MANIFEST_KEYS) - {"files"}
    assert body["schema"] == manifest.TOURNAMENT_SCHEMA_V2
    assert body["protocol"] == {"name": "spellbench/v2", "minor": 0}
    assert body["tournament"]["bots"] == [entries[0].to_json()]
    assert body["tournament"]["rating_anchor"] == {"name": "uniform", "bot_id": entries[0].bot_id}
    assert body["tournament"]["arena_version"] == __version__
    assert body["engine"] == engine.to_json() and body["engine_profile"] == profile.to_json()
    assert body["information_rules"] == info_rules
    assert body["validator"] == validator_record(rows, [])
    assert body["isolation"] == isolation_record(config)
    assert body["secrets"] == {"commitment": secret.commitment(), "run_secret": secret.hex(),
                               "commitment_proof": PROOF.to_json()}
    assert body["run"] == {"benchmark_id": "pauper-kernel", "label": "2026-10-01", "status": "complete", "rated": True}
    assert body["allocation"] == SMALL.to_json()
    assert body["engine_files"] == [file.to_json() for file in PINNED]
    assert body["games"] == {"scheduled": 1, "total": 1, "natural": 1, "truncated": 0, "halted": 0, "forfeit": 0}
    assert body["leaderboard_status"] == "ok"
