"""The pregame scenario (Task 21 fix round 1): a scenario poses the mulligan and starting-player decisions itself.

Spec 7.6 lets an engine skip these decisions only under ``mulligan: "none"`` and
``starting_player: "host_assigned"``. The fake engine's built-in games refuse any other value
(``unsupported_rule``); a scenario deck poses them itself, so it plays under ``--london --toss``.
"""

from __future__ import annotations

from fake_v2_world import Posed, Scenario


def _script(world):
    world.turn, world.phase_step = 0, "pregame"           # a pregame decision: turn 0, both seats null
    world.active_seat = world.priority_seat = None
    for seat in ("p0", "p1"):
        yield Posed(seat, [{"kind": "mulligan", "hand_size": 7, "mulligans_taken": 0, "keep": True},
                           {"kind": "mulligan", "hand_size": 7, "mulligans_taken": 0, "keep": False}])
    yield Posed("p0", [{"kind": "choose_starting_player", "player": seat} for seat in ("p0", "p1")])


SCENARIO = Scenario(
    name="pregame",
    decklist=[{"name": "Mountain", "count": 20}],
    engine_args=("--london", "--toss"),
    script=_script,
)
