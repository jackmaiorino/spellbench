"""Re-verify a published tournament directory from its files alone."""

from __future__ import annotations

from pathlib import Path

from . import legacy_v1


def validate_tournament_dir(directory: Path) -> list[str]:
    """Re-verify a published tournament; returns the failures (empty means OK).

    Protocol v1 runs (schema spellbench-tournament/v1) go to the frozen legacy
    verifier; the v2 verifier arrives with the v2 arena.
    """
    return legacy_v1.validate_v1_run(directory)
