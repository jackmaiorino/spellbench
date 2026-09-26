"""Opt-in conformance run against a real environment-role engine binary.

Set ``SPELLBENCH_ENGINE_BIN`` to an engine executable (for example
mtg-kernel's ``agent_bridge_v1``) to drive whole games through the reference
:class:`EngineProcess`. Every response passes the reference validators:
strict JSON (including the ``|x| <= 2^53`` integer bound), message schemas,
step and group contiguity, provenance pinning, and terminal counts.
``SPELLBENCH_ENGINE_DECKS`` (comma-separated, default ``Burn``) lists the
catalog decks to sweep, each played as a mirror. Skipped when
``SPELLBENCH_ENGINE_BIN`` is unset.
"""

from __future__ import annotations

import os

import pytest

from spellbench.engine_client import EngineProcess
from spellbench.models import Decision, Terminal

ENGINE_BIN = os.environ.get("SPELLBENCH_ENGINE_BIN")
DECKS = [deck for deck in os.environ.get("SPELLBENCH_ENGINE_DECKS", "Burn").split(",") if deck]
FORMAT = "pauper-bo1"
STEP_BUDGET = 3_000

pytestmark = pytest.mark.skipif(not ENGINE_BIN, reason="SPELLBENCH_ENGINE_BIN is not set")


def _play(pick, *, deck: str, game_seed: int) -> tuple[Terminal, int]:
    """Play one capped game with ``pick(decision) -> candidate_id``."""
    with EngineProcess([ENGINE_BIN], timeout_s=120) as engine:
        hello = engine.hello()
        assert FORMAT in hello.formats
        response = engine.reset(
            game_id=f"conformance-{game_seed}",
            format=FORMAT,
            decks=[{"catalog_id": deck}, {"catalog_id": deck}],
            game_seed=game_seed,
            max_decisions=STEP_BUDGET,
            max_steps=STEP_BUDGET,
        )
        steps = 0
        while isinstance(response, Decision):
            assert response.step == steps
            response = engine.step(pick(response))
            steps += 1
        assert isinstance(response, Terminal)
        return response, steps


@pytest.mark.parametrize("deck", DECKS)
def test_first_candidate_game_is_conformant(deck: str) -> None:
    terminal, steps = _play(lambda decision: 0, deck=deck, game_seed=12345)
    assert terminal.result.step_count == steps


@pytest.mark.parametrize("deck", DECKS)
def test_rotating_candidate_game_is_conformant(deck: str) -> None:
    terminal, steps = _play(
        lambda decision: decision.step % len(decision.candidates), deck=deck, game_seed=987654321
    )
    assert terminal.result.step_count == steps
