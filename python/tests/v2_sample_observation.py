"""The spec 6.1 example observation as data, and the all-on and all-off flag sets of spec 6.9."""

from __future__ import annotations

from spellbench.observation import OBSERVATION_FLAGS

# Spec 6.1, verbatim (JSON null, true and false written as None, True and False).
SAMPLE_OBSERVATION = {
    "viewer": "p0",
    "turn": 5,
    "phase_step": "precombat_main",
    "active_seat": "p0",
    "priority_seat": "p0",
    "passed_seats": [],
    "day_night": None,
    "players": [
        {
            "seat": "p0", "life": 14, "poison": None, "counters": None,
            "mana_pool": {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0},
            "lands_played_this_turn": 0, "mulligans_taken": 0, "designations": [], "progress": None,
            "hand_count": 2, "library_count": 46,
            "hand": [
                {"object_id": "o-1a7f3c9e5b2d4801", "card_name": "Lightning Bolt", "owner_seat": "p0", "controller_seat": "p0", "zone": "hand",
                 "full_name": None, "face_down": False, "token": False, "copy": False,
                 "characteristics": {"supertypes": [], "types": ["instant"], "subtypes": [], "colors": ["red"],
                                     "mana_value": 1, "power": None, "toughness": None, "keywords": []},
                 "permanent": None, "exiled_by": None},
                {"object_id": "o-2b8e4dafc6031912", "card_name": "Mountain", "owner_seat": "p0", "controller_seat": "p0", "zone": "hand",
                 "full_name": None, "face_down": False, "token": False, "copy": False,
                 "characteristics": {"supertypes": ["basic"], "types": ["land"], "subtypes": ["mountain"], "colors": [],
                                     "mana_value": 0, "power": None, "toughness": None, "keywords": []},
                 "permanent": None, "exiled_by": None},
            ],
            "battlefield": [
                {"object_id": "o-4da06fc1e8253b34", "card_name": "Monastery Swiftspear", "owner_seat": "p0", "controller_seat": "p0", "zone": "battlefield",
                 "full_name": None, "face_down": False, "token": False, "copy": False,
                 "characteristics": {"supertypes": [], "types": ["creature"], "subtypes": ["human", "monk"], "colors": ["red"],
                                     "mana_value": 1, "power": 2, "toughness": 3, "keywords": ["haste", "prowess"]},
                 "permanent": {"tapped": False, "summoning_sick": False, "damage": 0, "counters": {"p1p1": 1},
                               "attached_to": None, "attacking": False, "attack_target": None,
                               "blocking": False, "blocked_attackers": [], "phased_out": False,
                               "statuses": [], "class_level": None, "chosen": []},
                 "exiled_by": None},
            ],
            "graveyard": [],
            "exile": [],
            "command": [],
        },
        {
            "seat": "p1", "life": 11, "poison": None, "counters": None,
            "mana_pool": {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0},
            "lands_played_this_turn": 0, "mulligans_taken": 1, "designations": [], "progress": None,
            "hand_count": 3, "library_count": 47,
            "hand": None,
            "battlefield": [
                {"object_id": "o-6fc281e30a475d56", "card_name": "Spellstutter Sprite", "owner_seat": "p1", "controller_seat": "p1", "zone": "battlefield",
                 "full_name": None, "face_down": False, "token": False, "copy": False,
                 "characteristics": {"supertypes": [], "types": ["creature"], "subtypes": ["faerie", "wizard"], "colors": ["blue"],
                                     "mana_value": 2, "power": 1, "toughness": 1, "keywords": ["flash", "flying"]},
                 "permanent": {"tapped": True, "summoning_sick": False, "damage": 0, "counters": {},
                               "attached_to": None, "attacking": False, "attack_target": None,
                               "blocking": False, "blocked_attackers": [], "phased_out": False,
                               "statuses": [], "class_level": None, "chosen": []},
                 "exiled_by": None},
            ],
            "graveyard": [],
            "exile": [],
            "command": [],
        },
    ],
    "stack": [],
    "pending_triggers": [],
    "known": [
        {"owner_seat": "p0", "zone": "library", "card_name": "Mountain", "object_id": None,
         "position_from_top": 0, "position_from_bottom": None, "how": "looked_at"},
        {"owner_seat": "p1", "zone": "hand", "card_name": "Counterspell", "object_id": None,
         "position_from_top": None, "position_from_bottom": None, "how": "revealed"},
    ],
}

ALL_FLAGS_ON = dict.fromkeys(OBSERVATION_FLAGS, True)
ALL_FLAGS_OFF = dict.fromkeys(OBSERVATION_FLAGS, False)
