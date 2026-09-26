from __future__ import annotations

import collections
from pathlib import Path
from typing import Any, Deque

import pytest

from spellbench import wire
from spellbench.errors import TransportError
from spellbench.models import (
    Candidate,
    Decision,
    EngineIdentity,
    Group,
    Provenance,
    SeatSummary,
    StateSummary,
)

GOLDENS_DIR = Path(__file__).resolve().parents[2] / "goldens" / "protocol_v1"

TEST_ENGINE = EngineIdentity(
    name="test-engine",
    version="0.1.0",
    source_revision=None,
    rules_snapshot_id="rules-test",
    card_pool_identity="pool-test",
)
TEST_PROVENANCE = TEST_ENGINE.provenance()

OBJ = {
    "object_id": "obj-000001",
    "card_name": "Lightning Bolt",
    "owner_seat": "p0",
    "controller_seat": "p0",
    "zone": "hand",
}
OBJ2 = {
    "object_id": "obj-000002",
    "card_name": "Grizzly Bears",
    "owner_seat": "p1",
    "controller_seat": "p1",
    "zone": "battlefield",
}
HIDDEN_OBJ = {
    "object_id": "obj-000003",
    "card_name": None,
    "owner_seat": "p1",
    "controller_seat": "p1",
    "zone": "hand",
}

VALID_SEMANTICS: dict[str, dict[str, Any]] = {
    "pass": {"kind": "pass"},
    "play_land": {"kind": "play_land", "source": OBJ},
    "cast_spell": {"kind": "cast_spell", "source": OBJ},
    "activate_mana_ability": {
        "kind": "activate_mana_ability",
        "source": OBJ2,
        "mana_choice": "R",
        "cost_target": None,
    },
    "activate_ability": {"kind": "activate_ability", "source": OBJ2, "ability_index": 0},
    "plot_spell": {"kind": "plot_spell", "source": OBJ},
    "choose_target": {"kind": "choose_target", "source": OBJ, "remaining": 0, "target": {"player": "p1"}},
    "choose_cost_target": {
        "kind": "choose_cost_target",
        "source": OBJ,
        "cost_kind": "sacrifice",
        "remaining": 1,
        "candidate": OBJ2,
    },
    "choose_cast_mode": {"kind": "choose_cast_mode", "source": OBJ, "mode": "alternative"},
    "choose_kicker": {"kind": "choose_kicker", "source": OBJ, "pay": True},
    "choose_spell_mode": {"kind": "choose_spell_mode", "source": OBJ, "mode_index": 1, "mode_count": 2},
    "choose_option": {"kind": "choose_option", "source": OBJ, "option_index": 0, "option_count": 3},
    "choose_effect_target": {
        "kind": "choose_effect_target",
        "source": OBJ,
        "target": {"object": OBJ2},
        "selected_count": 0,
        "min_targets": 1,
        "max_targets": 2,
    },
    "finish_effect_selection": {"kind": "finish_effect_selection", "source": OBJ, "selected_count": 1},
    "choose_color": {"kind": "choose_color", "source": OBJ, "color": "red"},
    "choose_number": {"kind": "choose_number", "source": OBJ, "value": 2, "minimum": 0, "maximum": 5},
    "choose_boolean": {"kind": "choose_boolean", "source": OBJ, "value": False},
    "finish_target_selection": {"kind": "finish_target_selection", "source": OBJ, "selected_count": 1},
    "choose_optional_cost_use": {"kind": "choose_optional_cost_use", "use_cost": True},
    "choose_optional_cost_which": {"kind": "choose_optional_cost_which", "choice": "sacrifice_land"},
    "choose_spell_copy_payment": {"kind": "choose_spell_copy_payment", "source": OBJ, "pay": False},
    "choose_spell_copy_retarget": {"kind": "choose_spell_copy_retarget", "source": OBJ, "change_target": True},
    "choose_madness_cast": {"kind": "choose_madness_cast", "card": OBJ, "cast_it": True},
    "discard": {"kind": "discard", "cards": [OBJ]},
    "choose_attacker_inclusion": {"kind": "choose_attacker_inclusion", "attacker": OBJ2, "include": True},
    "choose_blocker_inclusion": {
        "kind": "choose_blocker_inclusion",
        "attacker": OBJ2,
        "blocker": OBJ,
        "include": False,
    },
    "order_triggers": {"kind": "order_triggers", "pending_sources": [OBJ, OBJ2], "order": [1, 0]},
}


def make_decision(
    request_id: str,
    *,
    step: int = 0,
    acting_seat: str = "p0",
    group: Group | None = None,
    game_id: str = "g-0001",
    semantics: list[dict[str, Any]] | None = None,
    provenance: Provenance = TEST_PROVENANCE,
    extensions: dict[str, Any] | None = None,
) -> Decision:
    if semantics is None:
        semantics = [{"kind": "pass"}]
    candidates = tuple(
        Candidate(candidate_id=index, semantic=semantic, display_text=None)
        for index, semantic in enumerate(semantics)
    )
    return Decision(
        request_id=request_id,
        game_id=game_id,
        step=step,
        acting_seat=acting_seat,
        group=group if group is not None else Group(group_id=step, substep_index=0, substep_count=1),
        state_summary=StateSummary(
            turn=1,
            phase_step="precombat_main",
            active_seat="p0",
            priority_seat=acting_seat,
            seats=(
                SeatSummary(
                    seat="p0", life=20, hand_count=7, library_count=53, graveyard_count=0, battlefield_count=0
                ),
                SeatSummary(
                    seat="p1", life=20, hand_count=7, library_count=53, graveyard_count=0, battlefield_count=0
                ),
            ),
            stack_count=0,
        ),
        candidates=candidates,
        candidates_sha256=wire.candidates_sha256([candidate.to_json() for candidate in candidates]),
        provenance=provenance,
        extensions={} if extensions is None else extensions,
    )


def payload(message: dict[str, Any]) -> bytes:
    """Canonical line payload (no newline), as ScriptedPeer responses carry."""
    return wire.canonical_json_dumps(message)


class ScriptedPeer:
    """In-process fake peer: queued response payloads (or exceptions)."""

    def __init__(self, responses: list[bytes | BaseException] | None = None) -> None:
        self.responses: Deque[bytes | BaseException] = collections.deque(responses or [])
        self.sent: list[bytes] = []
        self.closed = False

    def write_line(self, data: bytes) -> None:
        if self.closed:
            raise TransportError("peer is closed")
        self.sent.append(data)

    def read_line(self) -> bytes:
        if not self.responses:
            raise TransportError("script exhausted")
        item = self.responses.popleft()
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self) -> None:
        self.closed = True


def load_transcript(name: str) -> list[tuple[bytes, str, dict[str, Any]]]:
    """Returns (raw_line_without_newline, dir, message) per transcript row."""
    path = GOLDENS_DIR / name
    rows = []
    for raw in path.read_bytes().splitlines():
        entry = wire.strict_json_loads(raw)
        rows.append((raw, entry["dir"], entry["message"]))
    return rows


def transcript_requests(name: str, direction: str) -> list[dict[str, Any]]:
    return [message for _, dir_, message in load_transcript(name) if dir_ == direction]


def transcript_response_payloads(name: str, direction: str) -> list[bytes]:
    return [payload(message) for _, dir_, message in load_transcript(name) if dir_ == direction]


@pytest.fixture()
def scripted_peer() -> ScriptedPeer:
    return ScriptedPeer()
