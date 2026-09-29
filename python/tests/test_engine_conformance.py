"""Opt-in conformance run against a real v2 engine.

Set SPELLBENCH_ENGINE_BIN to the engine executable; SPELLBENCH_ENGINE_ARGS (space-separated) is appended
to its command, SPELLBENCH_ENGINE_FORMAT (default pauper-bo1) names the format, and SPELLBENCH_ENGINE_DECKS
(comma-separated, default Burn) lists the catalog decks. The games play two of each deck, seat-swapped.
"""

from __future__ import annotations

import os

import pytest

from spellbench.conformance import check_engine

ENGINE_BIN = os.environ.get("SPELLBENCH_ENGINE_BIN")
ENGINE_ARGS = os.environ.get("SPELLBENCH_ENGINE_ARGS", "").split()
FORMAT = os.environ.get("SPELLBENCH_ENGINE_FORMAT") or "pauper-bo1"
DECKS = [deck for deck in os.environ.get("SPELLBENCH_ENGINE_DECKS", "Burn").split(",") if deck]

pytestmark = pytest.mark.skipif(not ENGINE_BIN, reason="SPELLBENCH_ENGINE_BIN is not set")


def test_the_engine_is_conformant() -> None:
    report = check_engine([ENGINE_BIN, *ENGINE_ARGS], format=FORMAT, decks=DECKS)
    assert report.passed, report.render()
