"""The Manabrew adapter: gameView from the human seat's observation, prompts from pending decisions, answers back."""

from __future__ import annotations

import json
import unittest

from spellbench.human.manabrew import prompts, view

ME, OPP = "p0", "p1"


def card(oid, name, seat, zone, *, types=("creature",), power=2, toughness=2, tapped=False, **permanent):
    entry = {"object_id": oid, "card_name": name, "full_name": name, "owner_seat": seat, "controller_seat": seat,
             "zone": zone, "token": False, "copy": False, "face_down": False,
             "characteristics": {"colors": ["red"], "keywords": [], "mana_value": 1, "power": power,
                                 "toughness": toughness, "subtypes": [], "supertypes": [], "types": list(types)}}
    if zone == "battlefield":
        entry["permanent"] = {"tapped": tapped, "attacking": False, "blocking": False, "blocked_attackers": [],
                              "counters": {}, "damage": 0, "summoning_sick": False, "attached_to": None, **permanent}
    return entry


def observation():
    return {"turn": 3, "active_seat": ME, "priority_seat": ME, "phase_step": "precombat_main", "stack": [],
            "players": [
                {"seat": ME, "life": 20, "hand": [card("h1", "Lightning Bolt", ME, "hand", types=("instant",))],
                 "hand_count": 1, "library_count": 50, "battlefield": [card("b1", "Krark-Clan Shaman", ME,
                                                                             "battlefield", power=1, toughness=1)],
                 "graveyard": [], "exile": [], "mana_pool": {"R": 1}, "lands_played_this_turn": 0},
                {"seat": OPP, "life": 17, "hand": None, "hand_count": 4, "library_count": 48,
                 "battlefield": [card("o1", "Writhing Chrysalis", OPP, "battlefield", counters={"p1p1": 1})],
                 "graveyard": [], "exile": [], "mana_pool": {}, "lands_played_this_turn": 1}]}


SEATS = view.Seats(ME, "player-1", "player-0", {"player-1": "human", "player-0": "Basilisk 2"})


class GameViewTest(unittest.TestCase):
    def test_view_shows_the_seat_and_hides_the_opponent_hand(self):
        gv = view.game_view(observation(), SEATS, "g1")
        json.dumps(gv)
        zones = {(z["zone"], z["ownerId"]): z for z in gv["zones"]}
        self.assertEqual(zones[("hand", "player-1")]["cards"][0]["identity"]["name"], "Lightning Bolt")
        opp_hand = zones[("hand", "player-0")]
        self.assertEqual(opp_hand["count"], 4)
        self.assertTrue(all(c == {"visibility": "hidden", "id": c["id"]} for c in opp_hand["cards"]))
        self.assertEqual(zones[("library", "player-0")]["cards"], [])
        chrysalis = zones[("battlefield", "player-0")]["cards"][0]
        self.assertEqual(chrysalis["counters"], {"P1P1": 1})
        self.assertIn("Eldrazi", chrysalis["text"])
        self.assertEqual(gv["step"], "main1")
        self.assertEqual(gv["activePlayerId"], "player-1")
        self.assertEqual({p["id"]: p["life"] for p in gv["players"]}, {"player-1": 20, "player-0": 17})


class PromptTest(unittest.TestCase):
    def pending(self, candidates, *, kind="priority", screen="generic", prompt="Your priority"):
        return {"seq": 7, "prompt": prompt, "context": {"kind": kind}, "group": {}, "screen": screen,
                "candidates": [{"id": i, "kind": s["kind"], "text": t, "semantic": s} for i, (s, t) in
                               enumerate(candidates)]}

    def test_priority_is_choose_action(self):
        bolt = {"object_id": "h1", "card_name": "Lightning Bolt", "zone": "hand"}
        pending = self.pending([({"kind": "pass"}, "Pass"), ({"kind": "cast_spell", "source": bolt}, "Cast Lightning Bolt")])
        data, answer = prompts.build(pending, observation(), SEATS)
        self.assertEqual(data["type"], "chooseAction")
        self.assertEqual(data["actions"], [{"id": "1", "type": "cast", "cardId": "h1", "mode": {"type": "normal"},
                                            "label": "Cast Lightning Bolt"}])
        self.assertEqual(answer({"type": "act", "actionId": "1"}), ("answer", 1))
        self.assertEqual(answer({"type": "pass", "exhaustStack": False}), ("answer", 0))
        with self.assertRaises(ValueError):
            answer({"type": "act", "actionId": "9"})

    def test_targets(self):
        shaman = {"object": {"object_id": "o1", "card_name": "Writhing Chrysalis", "zone": "battlefield"}}
        pending = self.pending([({"kind": "choose_target", "target": shaman}, "Target Writhing Chrysalis"),
                                ({"kind": "choose_target", "target": {"player": OPP}}, "Target opponent")],
                               kind="choice", prompt="Choose a target")
        data, answer = prompts.build(pending, observation(), SEATS)
        self.assertEqual(data["type"], "chooseBoardTargets")
        self.assertEqual(data["candidates"], [{"kind": "card", "id": "o1"}, {"kind": "player", "id": "player-0"}])
        self.assertEqual(answer({"chosen": [{"kind": "player", "id": "player-0"}]}), ("answer", 1))

    def test_options_say_what_they_do(self):
        pending = self.pending([({"kind": "choose_option", "option_index": 0}, "Leave Swamp on top of your library"),
                                ({"kind": "choose_option", "option_index": 1}, "Put Swamp into your graveyard")],
                               kind="choice", prompt="Explore (Map Token) revealed Swamp")
        data, answer = prompts.build(pending, observation(), SEATS)
        self.assertEqual(data["type"], "chooseFromSelection")
        self.assertEqual([o["label"] for o in data["options"]],
                         ["Leave Swamp on top of your library", "Put Swamp into your graveyard"])
        self.assertEqual(data["presentation"]["title"], "Explore (Map Token) revealed Swamp")
        self.assertEqual(answer({"chosenIndices": [1]}), ("answer", 1))

    def test_attack_becomes_a_plan(self):
        attacker = {"object_id": "b1", "card_name": "Krark-Clan Shaman"}
        pending = self.pending([({"kind": "declare_attack", "attacker": attacker, "defender": None}, "no attack"),
                                ({"kind": "declare_attack", "attacker": attacker, "defender": {"player": OPP}}, "attack")],
                               kind="choice", screen="attack")
        data, answer = prompts.build(pending, observation(), SEATS)
        self.assertEqual(data["type"], "chooseAttackers")
        self.assertEqual(data["attackers"][0]["attackerId"], "b1")
        self.assertEqual(answer({"assignments": [{"attackerId": "b1", "targetId": "player-0"}]}),
                         ("plan", {"kind": "attack", "attackers": ["b1"]}))


if __name__ == "__main__":
    unittest.main()
