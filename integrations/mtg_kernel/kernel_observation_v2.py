"""Neutral observations from the kernel's actor-visible V5 projection.

The legacy payload and all native identities stay inside the environment.
This module never reads omniscient state or forwards x_kernel_v5. Stack
incarnations come from an opt-in private bridge sideband, not their positions.
"""
from __future__ import annotations

from collections import Counter

import hashlib
import hmac
from copy import deepcopy
from typing import Any

from spellbench.observation import validate_observation

COLORS = ("white", "blue", "black", "red", "green")
SEATS = ("p0", "p1")
PHASES = {"main1": "precombat_main", "main2": "postcombat_main",
          "begin_combat": "beginning_of_combat", "end_combat": "end_of_combat", "end": "end_step"}
COUNTERS = {"plus1_plus1": "p1p1", "minus1_minus1": "m1m1",
            "minus0_minus1": "m0m1", "stun": "stun", "lore": "lore"}
KEYWORDS = ("flying", "reach", "haste", "vigilance", "trample", "first_strike", "double_strike",
            "deathtouch", "menace", "defender", "lifelink", "hexproof", "indestructible",
            "protection_from_monocolored")
# Fixed classifications from the private bridge. Arbitrary support values are
# never diagnostic text: they may contain facts outside the visible projection.
PRIVATE_PROJECTION_FAILURES = (
    "invalid detached resolving item", "invalid pending trigger announcement",
    "invalid pending activation announcement", "foreign mana ability row",
    "unbound mana ability row",
)


class ProjectionError(ValueError):
    """A fact cannot be represented without guessing or exposing private data."""


def native_key(stable: dict) -> tuple:
    return stable["arena_id"], stable["zone_change_count"], stable["zone"]


def legacy_id(stable: dict) -> str:
    return f"obj-{stable['arena_id']:06}-z{stable['zone_change_count']:04}"


def normalized_zones(value: Any) -> Any:
    if isinstance(value, list):
        return [normalized_zones(item) for item in value]
    if isinstance(value, dict):
        return {key: item.lower() if key == "zone" and isinstance(item, str) else normalized_zones(item)
                for key, item in value.items()}
    return value


class ViewerIds:
    def __init__(self, secret: bytes, viewer: str):
        self.secret = secret
        self.viewer = viewer
        self.serial = 0
        self.current: dict[tuple, str] = {}

    def retain(self, keys: set[tuple]) -> None:
        self.current = {key: value for key, value in self.current.items() if key in keys}

    def get(self, key: tuple) -> str:
        if key not in self.current:
            # Only the observer's local allocation counter enters the ID. Native
            # arena numbers, hidden allocations and global steps do not.
            payload = f"spellbench-kernel-v2-id\0{self.viewer}\0{self.serial}".encode()
            self.current[key] = hmac.new(self.secret, payload, hashlib.sha256).hexdigest()[:32]
            self.serial += 1
        return self.current[key]


class KernelProjection:
    def __init__(self, catalog: dict, game_secret: bytes, *, first_seat: str = "p0", keywords: bool = False):
        if catalog.get("schema") != "spellbench-kernel-public-catalog/v1":
            raise ProjectionError("unsupported public catalog schema")
        if first_seat not in SEATS:
            raise ProjectionError("invalid starting seat")
        self.catalog = catalog
        self.keywords = keywords
        self.seat_map = {"p0": first_seat, "p1": SEATS[1 - SEATS.index(first_seat)]}
        self.ids = {seat: ViewerIds(game_secret, seat) for seat in SEATS}
        self.refs: dict[str, dict] = {}
        self.stable_refs: dict[tuple, dict] = {}
        self.stack_refs = {}
        self.metadata_by_id = {(card["card_db_id"], card["face"]): (name, card)
                               for name, card in catalog["cards"].items()}

    def seat(self, native: str) -> str:
        try:
            return self.seat_map[native]
        except KeyError as exc:
            raise ProjectionError("invalid native seat") from exc

    def spell_characteristics(self, metadata, x_value, cast_method):
        if x_value is not None and (type(x_value) is not int or x_value < 0):
            raise ProjectionError("invalid public chosen X")
        if cast_method == "omen":
            forms = metadata.get("spell_forms")
            form = forms.get("omen") if type(forms) is dict else None
            if type(form) is not dict or type(form.get("x_count")) is not int or not 0 <= form["x_count"] <= 255:
                raise ProjectionError("Omen spell metadata absent or invalid in compiled catalog")
            characteristics = form.get("characteristics")
            keys = {"supertypes", "types", "subtypes", "colors", "mana_value", "power", "toughness", "keywords"}
            if (type(characteristics) is not dict or set(characteristics) != keys
                    or any(type(characteristics[key]) is not list
                           or any(type(value) is not str for value in characteristics[key])
                           for key in ("supertypes", "types", "subtypes", "colors", "keywords"))
                    or not set(characteristics["types"]) & {"instant", "sorcery"}
                    or any(kind not in {"land", "creature", "instant", "sorcery", "artifact", "enchantment", "planeswalker"}
                           for kind in characteristics["types"])
                    or any(color not in COLORS for color in characteristics["colors"])
                    or type(characteristics["mana_value"]) is not int or characteristics["mana_value"] < 0
                    or any(characteristics[key] is not None and type(characteristics[key]) is not int
                           for key in ("power", "toughness"))):
                raise ProjectionError("Omen spell characteristics absent or invalid in compiled catalog")
            metadata = form
        result = deepcopy(metadata["characteristics"])
        result["colors"] = sorted(result["colors"], key=COLORS.index)
        result["mana_value"] += metadata["x_count"] * (x_value or 0)
        if cast_method == "bestow":
            result["types"], result["subtypes"] = ["enchantment"], ["aura"]
            result["power"] = result["toughness"] = None
        if not self.keywords:
            result["keywords"] = None
        elif not isinstance(result["keywords"], list):
            raise ProjectionError("printed spell keywords absent from compiled catalog")
        return result

    def metadata(self, name: str) -> dict:
        try:
            return self.catalog["cards"][name]
        except KeyError as exc:
            raise ProjectionError("visible card absent from compiled catalog") from exc

    def ref(self, stable: dict, name: str, *, key: tuple | None = None) -> dict:
        zone = stable["zone"]
        owner = self.seat(stable["owner"])
        controller = self.seat(stable["controller"]) if zone in ("battlefield", "stack") else owner
        ref = {"object_id": self.ids[self.viewer].get(key or ("card", *native_key(stable))),
               "card_name": name, "owner_seat": owner, "controller_seat": controller, "zone": zone}
        self.stable_refs[native_key(stable)] = ref
        self.refs[legacy_id(stable)] = ref
        return ref

    def stable_ref(self, stable: dict | None) -> dict | None:
        return None if stable is None else deepcopy(self.stable_refs.get(native_key(stable)))

    def effect_ref(self, effect, support):
        instance = support.get("resolving_stack_instance")
        if instance is not None:
            if instance not in self.stack_refs:
                raise ProjectionError("resolving effect lost its public stack instance")
            return deepcopy(self.stack_refs[instance])
        return self.stable_ref(effect["source"])

    def target(self, target: dict) -> dict | None:
        if target["target_kind"] == "player":
            return {"player": self.seat(target["player"])}
        if target["target_kind"] == "object":
            ref = self.stable_ref(target["object"])
            return None if ref is None else {"object": ref}
        raise ProjectionError("unsupported native target kind")

    def legacy_ref(self, ref: dict | None, *, nullable: bool = False) -> dict | None:
        if ref is None:
            if nullable:
                return None
            raise ProjectionError("missing required native reference")
        result = self.refs.get(ref["object_id"])
        if result is None or result["zone"] != ref["zone"]:
            if nullable:
                return None
            raise ProjectionError("candidate refers to an unobserved object")
        if result["card_name"] != ref["card_name"]:
            raise ProjectionError("native reference name disagrees with actor observation")
        return deepcopy(result)

    def characteristics(self, card: dict, *, effective: bool) -> dict:
        result = deepcopy(self.metadata(card["card_name"])["characteristics"])
        result["colors"] = sorted(result["colors"], key=COLORS.index)
        if not self.keywords:
            result["keywords"] = None
        elif not isinstance(result["keywords"], list):
            raise ProjectionError("printed keywords absent from compiled catalog")
        if effective:
            facts = card["characteristics"]
            result["types"] = [kind for kind, enabled in facts["type_flags"].items() if enabled]
            result["colors"] = [color for bit, color in enumerate(COLORS)
                                if facts["effective_color_mask"] & (1 << bit)]
            try:
                result["subtypes"] = sorted({self.catalog["subtypes"][str(value)]
                                            for value in facts["effective_subtype_ids"]})
            except KeyError as exc:
                raise ProjectionError("effective subtype absent from compiled catalog") from exc
            creature = "creature" in result["types"]
            result["power"] = facts["effective_power"] if creature else None
            result["toughness"] = facts["effective_toughness"] if creature else None
            if self.keywords:
                flags = facts["effective_keywords"]
                extras = self.keyword_extras.get(legacy_id(card["stable"]))
                if not isinstance(extras, dict) or set(extras) != {"flash", "islandwalk", "cant_be_blocked"} or any(type(value) is not bool for value in extras.values()):
                    raise ProjectionError("effective public keyword extras are absent")
                result["keywords"] = [name for name in KEYWORDS if flags[name]]
                result["keywords"].extend(name for name, present in extras.items() if present)
                result["keywords"].extend(color + "walk" for bit, color in enumerate(("plains", "island", "swamp", "mountain", "forest"))
                                          if flags["landwalk_mask"] & (1 << bit))
                if flags["ward_generic"]:
                    result["keywords"].append("ward")
                result["keywords"] = sorted(set(result["keywords"]))
        return result

    def record(self, card: dict) -> dict:
        stable = card["stable"]
        name = card["card_name"]
        ref = self.stable_ref(stable)
        if ref is None:
            raise ProjectionError("record was not registered")
        battlefield = stable["zone"] == "battlefield"
        permanent = None
        if battlefield:
            key = native_key(stable)
            attacked = key in self.attackers
            blocked = self.blocks.get(key, [])
            counters = {COUNTERS[name]: value for name, value in card["counters"].items() if value > 0}
            if any(value < 0 for value in card["counters"].values()):
                raise ProjectionError("negative public counter")
            attached = self.attached.get(key)
            permanent = {
                "tapped": card["tapped"], "summoning_sick": card["summoning_sick"],
                "damage": card["damage"], "counters": counters,
                "attached_to": None if attached is None else {"object": attached},
                "attacking": attacked,
                "attack_target": {"player": SEATS[1 - SEATS.index(ref["controller_seat"])]} if attacked else None,
                "blocking": bool(blocked), "blocked_attackers": blocked,
                "phased_out": False, "statuses": [], "class_level": None,
                "chosen": [] if card.get("chosen_color") is None else
                    [{"kind": "color", "value": dict(zip("WUBRG", COLORS))[card["chosen_color"]]}],
            }
        return {**ref, "full_name": self.metadata(name)["full_name"], "face_down": False,
                "token": card.get("is_token", False), "copy": False,
                "characteristics": self.characteristics(card, effective=battlefield),
                "permanent": permanent, "exiled_by": self.exiled_by.get(native_key(stable))}

    def add_hand_knowledge(self, known: list, knowledge: dict, hand_counts: list) -> None:
        """Name-level facts about the other seat's hand. A card revealed in
        this decision is already listed with its id; it absorbs one fact with
        its name, so no copy is claimed twice."""
        for owner, facts in knowledge["hand"].items():
            seat = self.seat(SEATS[owner])
            names = Counter(fact["name"] for fact in facts)
            if names - knowledge["hand_truth"][owner]:
                raise ProjectionError("knowledge tracker claims a card the hand does not hold")
            for entry in known:
                if entry["owner_seat"] == seat and entry["zone"] == "hand" and names[entry["card_name"]]:
                    names[entry["card_name"]] -= 1
            for fact in facts:
                if names[fact["name"]]:
                    names[fact["name"]] -= 1
                    known.append({"owner_seat": seat, "zone": "hand", "card_name": fact["name"], "object_id": None,
                                  "position_from_top": None, "position_from_bottom": None, "how": fact["how"]})
            if sum(entry["owner_seat"] == seat and entry["zone"] == "hand" for entry in known) > hand_counts[owner]:
                raise ProjectionError("known hand facts exceed the hand count")

    def project(self, raw: dict, support: dict, knowledge: dict | None = None) -> dict:
        """The viewer's observation. With `knowledge` (the history tracker's
        view, profile known_cards:true) `known` carries every Section 6.7 fact,
        checked against the kernel's own library knowledge and the true hands."""
        failure = support.get("projection_error")
        if failure:
            message = "native private projection validation failed"
            if type(failure) is str and failure in PRIVATE_PROJECTION_FAILURES:
                message += ": " + failure
            raise ProjectionError(message)
        if f"{raw['card_db_hash']:016x}" != self.catalog["card_db_hash"]:
            raise ProjectionError("actor observation uses a different card database")
        raw = normalized_zones(raw)
        self.viewer = self.seat(raw["acting_player"])
        self.keyword_extras = support.get("public_keyword_extras", {})
        projection = raw["projection"]
        self.refs = {}
        self.stable_refs = {}
        public = [card for zones in (projection["battlefield"], projection["graveyards"])
                  for zone in zones for card in zone] + projection["exile"]
        cards = public + raw["own_hand"]
        stack = list(projection["stack"])
        instances = support.get("stack_instances")
        if not isinstance(instances, list) or len(instances) != len(stack) or len(set(instances)) != len(instances):
            raise ProjectionError("missing or inconsistent private stack instances")
        instances = list(instances)
        for field in ("detached_resolution", "announcing_trigger", "announcing_activation"):
            extra = support.get(field)
            if extra is None:
                continue
            if not isinstance(extra, dict) or set(extra) != {"instance", "item"} or not isinstance(extra["instance"], str):
                raise ProjectionError("malformed private stack announcement")
            if extra["instance"] in instances:
                raise ProjectionError("private resolving item duplicates a live stack instance")
            stack.append(normalized_zones(extra["item"]))
            instances.append(extra["instance"])
        keys = {("card", *native_key(card["stable"])) for card in cards}
        def stack_key(item, instance):
            # An original spell keeps its zone incarnation during announcement
            # and stack placement. Copies and abilities are distinct items.
            return (("card", *native_key(item["source"])) if item["stack_item_kind"] == "spell" and not item["is_copy"]
                    else ("stack", instance))
        keys.update(stack_key(item, instance) for item, instance in zip(stack, instances))
        announcing = []
        stack_sources = {native_key(item["source"]) for item in stack if item["stack_item_kind"] == "spell"}
        engine_context = projection["engine_context"]
        for field in ("pending_cast",):
            pending = engine_context.get(field)
            if pending and pending["source"]["zone"] == "stack" and native_key(pending["source"]) not in stack_sources:
                stable = pending["source"]
                if self.seat(stable["owner"]) != self.viewer:
                    raise ProjectionError("unplaced announcement is not the actor's own spell")
                name, metadata = self.metadata_by_id[(stable["card_db_id"], 0)]
                if metadata["x_count"] and "announcement_x_value" not in support:
                    raise ProjectionError("unplaced X announcement needs a public chosen-X sideband")
                announcing.append((stable, name, pending))
                stack_sources.add(native_key(stable))
                keys.add(("card", *native_key(stable)))
        # Library identities are issued only for the current look, never merely
        # because positional knowledge survived an earlier look.
        effect = projection["engine_context"]["pending_effect"]
        choice = None if effect is None else effect["choice"]
        offered_objects = {}
        if choice and choice["choice_kind"] == "targets":
            offered_objects = {native_key(target["object"]): target["object"]
                               for target in choice["legal_targets"] + choice["selected_targets"]
                               if target["target_kind"] == "object" and
                               (target["object"]["zone"] == "library" or
                                target["object"]["zone"] == "hand" and
                                self.seat(target["object"]["owner"]) != self.viewer)}
        look_count = support.get("look_card_count")
        if look_count is not None:
            if type(look_count) is not int or look_count < 1 or support.get("look_owner") not in SEATS:
                raise ProjectionError("invalid actor-visible look dimensions")
            entries = raw["known_library_cards"][SEATS.index(support["look_owner"])]
            prefix = [entry for entry in entries if entry["position"] < look_count]
            if len(prefix) != look_count or {entry["position"] for entry in prefix} != set(range(look_count)):
                raise ProjectionError("looked-at prefix is absent from actor-visible knowledge")
            offered_objects.update({native_key(entry["card"]["stable"]): entry["card"]["stable"] for entry in prefix})
        offered = set(offered_objects)
        look = support.get("effect_instance")
        if offered and not isinstance(look, str):
            raise ProjectionError("current look lacks a private effect instance")
        keys.update(("look", look, *key) for key in offered)
        self.ids[self.viewer].retain(keys)
        for card in cards:
            self.ref(card["stable"], card["card_name"])
        for item, instance in zip(stack, instances):
            if item["stack_item_kind"] == "spell":
                stable = item["source"]
                name, _ = self.metadata_by_id[(stable["card_db_id"], item["face_index"])]
                if stable["zone"] != "stack":
                    raise ProjectionError("spell source is not a live stack card")
                self.ref(stable, name, key=stack_key(item, instance))
        for stable, name, _ in announcing:
            self.ref(stable, name)
        known = []
        exposed_known = set()
        if knowledge is not None:
            for owner, entries in enumerate(raw["known_library_cards"]):
                native = {entry["position"]: (entry["card"]["stable"]["arena_id"], entry["card"]["card_name"])
                          for entry in entries}
                tracked = {position: (fact["native"], fact["name"])
                           for position, fact in knowledge["library"][owner].items()}
                if native != tracked or len(native) != len(entries):
                    raise ProjectionError("knowledge tracker disagrees with the kernel's library knowledge")
        for owner, entries in enumerate(raw["known_library_cards"]):
            for entry in entries:
                card = entry["card"]
                stable = card["stable"]
                key = native_key(stable)
                if key not in offered and knowledge is None:
                    continue  # profile known_cards:false, no historical tracker claim
                exposed = self.ref(stable, card["card_name"], key=("look", look, *key)) if key in offered else None
                if exposed is not None:
                    exposed_known.add(key)
                how = "looked_at" if exposed is not None else knowledge["library"][owner][entry["position"]]["how"]
                known.append({"owner_seat": self.seat(SEATS[owner]), "zone": "library", "card_name": card["card_name"],
                              "object_id": None if exposed is None else exposed["object_id"],
                              "position_from_top": entry["position"], "position_from_bottom": None, "how": how})
        for owner, entries in enumerate(raw["known_hand_cards"]):
            if self.seat(SEATS[owner]) == self.viewer:
                continue  # the viewer's hand is already represented by records
            for card in entries:
                stable = card["stable"]
                key = native_key(stable)
                if key not in offered:
                    continue
                exposed = self.ref(stable, card["card_name"], key=("look", look, *key)) if key in offered else None
                if exposed is not None:
                    exposed_known.add(key)
                known.append({"owner_seat": self.seat(SEATS[owner]), "zone": "hand", "card_name": card["card_name"],
                              "object_id": None if exposed is None else exposed["object_id"],
                              "position_from_top": None, "position_from_bottom": None, "how": "revealed"})
        # Current search/reveal targets are licensed actor-visible facts even
        # when the legacy knowledge store has no positional record. A search
        # conveys names and availability, never original library order.
        current = []
        for key, stable in offered_objects.items():
            if key not in exposed_known:
                try:
                    name, _ = self.metadata_by_id[(stable["card_db_id"], 0)]
                except KeyError as exc:
                    raise ProjectionError("offered card absent from compiled catalog") from exc
                current.append((name, key, stable))
        for name, key, stable in sorted(current):
            exposed = self.ref(stable, name, key=("look", look, *key))
            if stable["zone"] == "library" and support.get("choice", {}).get("purpose") != "search":
                raise ProjectionError("looked-at library card lacks an actor-visible position")
            known.append({"owner_seat": self.seat(stable["owner"]), "zone": stable["zone"], "card_name": name,
                          "object_id": exposed["object_id"], "position_from_top": None,
                          "position_from_bottom": None, "how": "searching" if stable["zone"] == "library" else "revealed"})
        if knowledge is not None:
            self.add_hand_knowledge(known, knowledge, projection["hand_counts"])
        known.sort(key=lambda entry: tuple((0, "") if entry[key] is None else (1, entry[key]) for key in
                   ("owner_seat", "zone", "card_name", "position_from_top", "position_from_bottom", "how", "object_id")))
        self.attached, self.exiled_by = {}, {}
        for relation in projection["object_relations"]:
            field = "attached_to" if relation["relation_kind"] == "attached_to" else "exiled_by"
            target = self.stable_ref(relation[field])
            if target is not None:
                (self.attached if field == "attached_to" else self.exiled_by)[native_key(relation["object"])] = target
        combat = projection["combat"]
        self.attackers = {native_key(attacker) for attacker in combat["ordered_attackers"]}
        self.blocks = {}
        for attacker, blockers in combat["attacker_to_ordered_blockers"]:
            target = self.stable_ref(attacker)
            if target is not None:
                for blocker in blockers:
                    self.blocks.setdefault(native_key(blocker), []).append(target)
        players = {}
        for native_index, native in enumerate(SEATS):
            seat = self.seat(native)
            players[seat] = {
                "seat": seat, "life": projection["life_totals"][native_index], "poison": None, "counters": None,
                "mana_pool": dict(zip(("W", "U", "B", "R", "G", "C"), projection["mana_pools"][native_index])),
                "lands_played_this_turn": projection["player_status"][native_index]["lands_played_this_turn"],
                "mulligans_taken": 0,
                "designations": [name for name in ("initiative", "monarch") if projection.get(name) == native],
                "progress": None,
                "hand_count": projection["hand_counts"][native_index], "library_count": projection["library_counts"][native_index],
                "hand": [self.record(card) for card in raw["own_hand"]] if seat == self.viewer else None,
                "battlefield": [self.record(card) for card in projection["battlefield"][native_index]],
                "graveyard": [self.record(card) for card in projection["graveyards"][native_index]],
                "exile": [self.record(card) for card in projection["exile"] if card["stable"]["owner"] == native],
                "command": [],
            }
        output_stack = []
        self.stack_refs = {}
        for item, instance in zip(stack, instances):
            stable = item["source"]
            spell = item["stack_item_kind"] == "spell"
            source = self.stable_ref(stable)
            # The card name of an ability is frozen public identity even after
            # its source leaves. The source reference itself must then be null.
            name, metadata = self.metadata_by_id[(stable["card_db_id"], item["face_index"])]
            revealed_source = any(native_key(card["stable"]) == native_key(stable)
                for cards in raw["known_hand_cards"] for card in cards)
            if not spell and source is None and (stable["zone"] == "library" or
                    stable["zone"] == "hand" and self.seat(stable["owner"]) != self.viewer and not revealed_source):
                name = None
            if spell:
                ref = source
                if ref is None:
                    raise ProjectionError("missing visible spell instance")
                x_value = item["x_value"]
                cast_method = item.get("cast_method")
                pending = engine_context.get("pending_cast")
                if pending and pending.get("source") and native_key(pending["source"]) == native_key(stable):
                    x_value = support.get("announcement_x_value", x_value)
                    cast_method = support.get("announcement_cast_method", cast_method)
                characteristics = self.spell_characteristics(metadata, x_value, cast_method)
                source = None
            else:
                ref = {"object_id": self.ids[self.viewer].get(("stack", instance)), "card_name": name,
                       "owner_seat": self.seat(item["controller"]), "controller_seat": self.seat(item["controller"]), "zone": "stack"}
                characteristics = None
            kind = item["stack_item_kind"]
            self.stack_refs[instance] = deepcopy(ref)
            output_stack.append({**ref, "stack_kind": "triggered_ability" if kind == "madness_offer" else kind,
                                 "source": source, "face_down": False, "copy": item["is_copy"],
                                 "characteristics": characteristics,
                                 "targets": [self.target(target) for target in item["targets"]],
                                 "divided": None, "modes": [item["mode_chosen"]],
                                 "x_value": x_value if spell else item["x_value"], "text": None})
        for stable, name, pending in announcing:
            metadata = self.metadata(name)
            x_value = support.get("announcement_x_value")
            characteristics = self.spell_characteristics(metadata, x_value, support.get("announcement_cast_method"))
            output_stack.append({**self.stable_ref(stable), "stack_kind": "spell", "source": None,
                "face_down": False, "copy": False, "characteristics": characteristics,
                "targets": [self.target(target) for target in pending.get("chosen_targets", [])],
                "divided": None, "modes": [pending["mode_chosen"]] if "mode_chosen" in pending else None,
                "x_value": x_value, "text": None})
        output_stack.reverse()  # native bottom-first; protocol top-first
        result = {
            "viewer": self.viewer, "turn": projection["turn"],
            "phase_step": PHASES.get(projection["phase"], projection["phase"]),
            "active_seat": self.seat(projection["active_player"]), "priority_seat": self.seat(projection["priority_player"]),
            "passed_seats": [self.seat(SEATS[index]) for index, passed in enumerate(projection["engine_context"]["priority_passes"]) if passed],
            "day_night": None, "players": [players[seat] for seat in SEATS], "stack": output_stack,
            "pending_triggers": None, "known": known,
        }
        validate_observation(result)
        return result
