"""The play log over the recorded human games (needs the operator engine records on this machine; skipped without).

Each case replays a recorded game through the narrator exactly as the session does and checks the lines that answer
"what happened and why" for a scenario the owner could not follow, plus the hidden-information check: no line may name
a card the human seat had not seen by then.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from spellbench.human import replay

ROOT = Path(os.environ.get("SPELLBENCH_HUMAN_RECORDS", "E:/artifacts/chains-20261107-human-interim/engine-records/cold"))
GAME_1 = "game-0-g-e04f733c60027f02"  # the first recorded human game (Wildfire against Basilisk 2, seat p0)
GAME_1_RECORDS = sorted(ROOT.glob(f"{GAME_1}-*/engine.jsonl.gz"))

pytestmark = pytest.mark.skipif(not GAME_1_RECORDS, reason="the recorded human game is not on this machine")


@pytest.fixture(scope="module")
def game() -> dict:
    rows = replay.read_record(GAME_1_RECORDS[0])
    return {"rows": rows, "result": replay.replay(rows, "p0")}


def lines(game: dict) -> list[str]:
    return [("  " if line.get("depth") else "") + line["text"] for line in game["result"]["log"]]


def test_krark_clan_shaman_activation_is_explained(game: dict) -> None:
    log = [line.strip() for line in lines(game)]
    assert ("You activate Krark-Clan Shaman (sacrificing Nihil Spellbomb): 1 damage to each creature without flying"
            in log)
    assert any(line.startswith("Krark-Clan Shaman (yours) deals damage: ") and "Writhing Chrysalis (opp)" in line
               for line in log)
    assert "Eldrazi Spawn Token (opp) dies (lethal damage from Krark-Clan Shaman)" in log
    assert "Krark-Clan Shaman (opp) dies (lethal damage from Krark-Clan Shaman)" in log
    assert "Opp sacrifices Eldrazi Spawn Token for {C}" in log
    assert "Writhing Chrysalis (opp) triggers: put a +1/+1 counter on it" in log
    assert "Writhing Chrysalis (opp) gets a +1/+1 counter (now 3/4)" in log
    assert "Writhing Chrysalis (opp) gets a +1/+1 counter (now 4/5)" in log


def test_cleansing_wildfire_names_its_target_and_the_land_it_fetched(game: dict) -> None:
    log = [line.strip() for line in lines(game)]
    at = log.index("You cast Cleansing Wildfire (targeting Drossforge Bridge (yours))")
    assert "Mountain is put onto the battlefield from your library by Cleansing Wildfire" in log[at:at + 4]
    at = log.index("Opp casts Cleansing Wildfire (targeting Drossforge Bridge (opp))")
    assert "Swamp is put onto the battlefield from opp library by Cleansing Wildfire" in log[at:at + 4]


def test_map_token_explore_names_the_revealed_card_and_what_followed(game: dict) -> None:
    log = [line.strip() for line in lines(game)]
    assert "Explore: You reveal Refurbished Familiar from the top of your library" in log   # a nonland: a counter
    assert "Refurbished Familiar (yours) gets a +1/+1 counter (now 3/2)" in log
    assert "Explore: You reveal Drossforge Bridge from the top of your library" in log      # a land: to hand
    assert "You put Drossforge Bridge from library into hand" in log
    assert "Explore: Opp reveals Refurbished Familiar from the top of their library" in log


def test_the_replay_check_stays_where_it_is(game: dict) -> None:
    result = game["result"]
    assert result["changes"] == 801
    assert len(result["unexplained"]) <= 4
    assert not result["leaks"]


def test_no_line_names_a_card_the_seat_has_not_seen(game: dict) -> None:
    result = game["result"]
    assert replay.leak_check(game["rows"], "p0", result["log"]) == []
    # the guard has something to guard: the game holds cards that never became public to the human seat
    public: set[str] = set()
    for sd in replay.decisions(game["rows"]):
        if sd.get("acting_seat") == "p0":
            replay._add_public(sd, public)
    hidden = sorted(replay.all_card_names(game["rows"]) - public)
    assert hidden
    # negative control: a line naming one of them is reported
    fake = [{"text": f"Opp reveals {hidden[0]}"}]
    assert replay.leak_check(game["rows"], "p0", fake) == [fake[0]["text"]]


def test_human_recording_settings_truncate_at_the_cap_and_pass_the_arena_validator(tmp_path):
    """A human session's record must never end the session at the per-game cap (a bot that mills itself with Balustrade
    Spy writes 100 MiB or more in one turn): its config says on_cap truncate and the arena's validator accepts it."""
    from spellbench.arena import engine_records
    from spellbench.human import session

    path, digest = session.recording_settings(tmp_path / "out", tmp_path / "cold")
    data = engine_records.settings({engine_records.CONFIG_ENV: str(path), engine_records.HASH_ENV: digest})
    assert data["on_cap"] == "truncate" and data["per_game_cap_bytes"] == 128 * 2**20
