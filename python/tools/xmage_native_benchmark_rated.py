"""Run the committed native benchmark through the existing arena safeguards.

This entrypoint is launched by xmage_native_qualified_job.py in its explicit
rated_benchmark mode. It refuses a raw call outside that job's owned Windows
containment. Results remain unpublished until the normal delivery workflow.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path

from spellbench.arena import runner, store
from spellbench.arena.schedule import schedule
from spellbench.bench import definition
from spellbench.bench.run import run_benchmark
from spellbench.run_secret import RunSecret

HOST_GUARD_SHA256 = "a736f9cc617db898aba1b150eb92193cae80dd500cbd5419a6e0867eeb5a9570"


def sha(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def require_guard(path: Path, work_id: str) -> None:
    if os.name != "nt" or os.environ.get("MTG_HOST_RESERVATION_TEST_ROOT"):
        raise ValueError("rated native execution requires production Windows containment")
    if path.name != "host_reservation_v1.py" or sha(path) != HOST_GUARD_SHA256:
        raise ValueError("rated native execution needs its pinned canonical host helper")
    spec = importlib.util.spec_from_file_location("rated_native_host_guard", path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    if helper.CANONICAL_ROOT != "C:/mtg-node/host-lock" or helper.SCHEMA != "mtg-host-reservation/v1":
        raise ValueError("rated native execution requires the canonical host reservation")
    token = os.environ.get(helper.TOKEN_ENV)
    status = helper.status(token)
    if (not token or status.get("state") != "held" or status.get("token_fate") != "holds"
            or status.get("test_root") is not False
            or status.get("record", {}).get("lane") != "spellbench-xmage-native"
            or status.get("record", {}).get("work_id") != work_id
            or os.getpid() not in helper.job_members(None)):
        raise ValueError("rated benchmark is outside its declared owned native job")


def play(benchmark_dir: Path, *, benchmark_sha256: str, run: str, proof: str,
         out: Path, host_guard: Path, host_work_id: str) -> dict:
    benchmark_dir = benchmark_dir.resolve()
    definition.run_sort_key(run)
    expected_out = benchmark_dir / definition.RUNS_DIR / run
    if out.resolve() != expected_out:
        raise ValueError("rated output must be this benchmark's committed run directory")
    if sha(benchmark_dir / "benchmark.json") != benchmark_sha256:
        raise ValueError("rated benchmark definition differs from its pin")
    if not isinstance(proof, str) or not proof.strip():
        raise ValueError("rated benchmark requires its public commitment timestamp proof")
    benchmark = definition.load_benchmark(benchmark_dir)
    if benchmark.opponent_panel:
        raise ValueError("native rated entrypoint requires the declared full benchmark schedule")
    config = runner.TournamentConfig.from_json(benchmark.tournament_config(str(expected_out)))
    expected_games = len(schedule(config, RunSecret.generate()))
    require_guard(host_guard, host_work_id)
    # The normal runner checks the published commitment and definition, owns
    # the once-only lock/secret, qualifies throughput and storage before games,
    # pins inputs, retains failures, publishes its local result and validates it.
    result = run_benchmark(benchmark_dir, run=run, proof=proof)
    summary = result.summary
    if result.failures:
        raise ValueError("rated native result validation failed: " + "; ".join(result.failures))
    if (result.run_dir.resolve() != expected_out or summary.status != "complete"
            or summary.rated is not True or summary.games_total != expected_games):
        raise ValueError("native benchmark did not complete the declared rated schedule")
    return {"schema": "spellbench-native-rated-result/v1", "benchmark": benchmark.id,
            "benchmark_sha256": benchmark_sha256, "run": run, "scheduled_games": expected_games,
            "completed_games": summary.games_total, "rated_games": summary.games_rated,
            "halted_games": summary.games_halted, "truncated_games": summary.games_truncated,
            "forfeit_games": summary.games_forfeit, "manifest_sha256": sha(expected_out / store.MANIFEST_NAME),
            "ledger_sha256": sha(expected_out / store.LEDGER_NAME),
            "scope": "complete validated local benchmark; replay and live publication remain separate"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--benchmark-sha256", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--proof", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--host-guard", type=Path, required=True)
    parser.add_argument("--host-work-id", required=True)
    args = parser.parse_args()
    print(json.dumps(play(args.benchmark, benchmark_sha256=args.benchmark_sha256,
                          run=args.run, proof=args.proof, out=args.out,
                          host_guard=args.host_guard, host_work_id=args.host_work_id)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
