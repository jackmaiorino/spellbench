"""Bound authorization work on the trusted host before game_start, without inference."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .login import refresh_credentials
from .provider import ProviderError
from .run_budget import RunBudget

GAME_PROFILE_HORIZON_S = 1800
PROFILE_LOCK_TIMEOUT_S = 35
RENEWAL_TIMEOUT_S = 50


def renew_profile(path: Path, budget: RunBudget) -> None:
    # The host child owns no model client. Its output is discarded so account
    # data cannot enter broker logs. A hard process deadline also bounds slow
    # response bodies, which urllib's socket inactivity timeout cannot do.
    child = subprocess.Popen(
        [sys.executable, "-m", "spellbench.llm.renewal", "--credentials", str(path),
         "--run-budget", str(budget.path), "--model", budget.model],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if child.wait(timeout=RENEWAL_TIMEOUT_S) != 0:
            raise ProviderError("profile_renewal_failed")
        budget.check(allow_pending=True)
    except Exception:
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
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    budget = RunBudget(args.run_budget, model=args.model)
    try:
        refresh_credentials(
            args.credentials, minimum_valid_seconds=GAME_PROFILE_HORIZON_S,
            lock_timeout_s=PROFILE_LOCK_TIMEOUT_S,
            before_refresh=lambda: budget.check(allow_pending=True),
            on_failure=lambda: budget.fail("profile_renewal_failed"),
        )
        return 0
    except Exception:
        budget.fail("profile_renewal_failed")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
