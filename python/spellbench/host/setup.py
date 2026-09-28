"""``GameSetup``: one scheduled game's bindings, computed once and shared by both roles (spec 9.2, 10.2).

Data only. Tasks 23 and 25 build one of these per scheduled game and read its fields to
construct the engine's ``reset`` and each agent's ``game_start``; ``host.game`` re-exports it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..agent_messages import OwnDeck
from ..messages import Limits, Resources, Rules, TimeControl, WireDeck


@dataclass(frozen=True)
class GameSetup:
    """One game's bindings: the engine's decks and the agents' decks, rules, clocks and seeds.

    ``game_secret_hex`` is declared ``field(repr=False)`` (R3-28): the dataclass repr never
    prints it, so logging or erroring on a ``GameSetup`` cannot leak the secret.
    """

    game_index: int
    game_id: str
    game_secret_hex: str = field(repr=False)
    format: str
    wire_decks: tuple[WireDeck, WireDeck]
    own_decks: tuple[OwnDeck, OwnDeck]
    rules: Rules
    time_control: TimeControl
    limits: Limits
    resources: Resources
    agent_seeds: tuple[int, int]
