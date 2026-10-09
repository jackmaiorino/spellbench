"""Bound authorization work on the trusted host before game_start, without inference."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .login import refresh_credentials
from .provider import ProviderError
from .run_budget import RunBudget, STAGE_EXHAUSTED

GAME_PROFILE_HORIZON_S = 1800
PROFILE_LOCK_TIMEOUT_S = 35
RENEWAL_TIMEOUT_S = 40


def renew_profile(path: Path, budget: RunBudget) -> None:
    # The host child owns no model client. Its output is discarded so account
    # data cannot enter broker logs. A hard process deadline also bounds slow
    # response bodies, which urllib's socket inactivity timeout cannot do.
    command = [sys.executable, "-m", "spellbench.llm.renewal", "--credentials", str(path),
               "--run-budget", str(budget.path), "--model", budget.model]
    if budget.paths.manifest is not None:
        command += ["--run-budget-map", str(budget.paths.manifest),
                    "--run-budget-map-sha256", budget.paths.sha256]
    if budget.admission_scope is not None:
        command += ["--admission-scope", str(budget.admission_scope),
                    "--admission-scope-sha256", budget.admission_scope_sha256]
    child = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        status = child.wait(timeout=RENEWAL_TIMEOUT_S)
        if status in (3, 4) and budget.admission_scope is not None:
            # Revalidate the parent rather than trusting an exit-code claim.
            budget.check(allow_pending=True)
        if status != 0:
            raise ProviderError("profile_renewal_failed")
        budget.check(allow_pending=True)
    except Exception as exc:
        if isinstance(exc, ProviderError) and exc.code in STAGE_EXHAUSTED:
            raise
        # Stop admission before killing the child and releasing its profile
        # lock. Another waiter must not reuse an uncertain rotating token.
        budget.fail("profile_renewal_failed")
        raise ProviderError("profile_renewal_failed") from None
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--run-budget", type=Path, required=True)
    parser.add_argument("--run-budget-map", type=Path)
    parser.add_argument("--run-budget-map-sha256")
    parser.add_argument("--admission-scope", type=Path)
    parser.add_argument("--admission-scope-sha256")
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    budget = RunBudget(args.run_budget, model=args.model, path_map=args.run_budget_map,
                       path_map_sha256=args.run_budget_map_sha256,
                       admission_scope=args.admission_scope, admission_scope_sha256=args.admission_scope_sha256)
    try:
        refresh_credentials(
            args.credentials, minimum_valid_seconds=GAME_PROFILE_HORIZON_S,
            lock_timeout_s=PROFILE_LOCK_TIMEOUT_S,
            before_refresh=lambda: budget.check(allow_pending=True),
            on_failure=lambda: budget.fail("profile_renewal_failed"),
        )
        return 0
    except Exception as exc:
        if isinstance(exc, ProviderError) and exc.code in STAGE_EXHAUSTED:
            return 3 if exc.code == "run_budget_stage_requests_exhausted" else 4
        budget.fail("profile_renewal_failed")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
