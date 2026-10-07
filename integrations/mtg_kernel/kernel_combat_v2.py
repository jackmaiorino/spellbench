"""Completion-preserving blocker-major choices for Spellbench v2.

Inputs are the defender's public legal-edge graph and public minimum blocker
counts. Game rules remain with the native engine's final aggregate validator.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Hashable, Mapping

from kernel_observation_v2 import native_key, normalized_zones


class CombatError(ValueError):
    pass


@dataclass(frozen=True)
class BlockPlan:
    blockers: tuple[Hashable, ...]
    edges: Mapping[Hashable, tuple[Hashable, ...]]
    minimums: Mapping[Hashable, int]

    def __post_init__(self):
        if len(set(self.blockers)) != len(self.blockers):
            raise CombatError("duplicate blocker")
        if set(self.edges) != set(self.blockers):
            raise CombatError("blocker graph does not match the public blocker list")
        if any(type(value) is not int or value < 1 for value in self.minimums.values()):
            raise CombatError("invalid minimum blockers")
        if any(len(set(values)) != len(values) or any(value not in self.minimums for value in values)
               for values in self.edges.values()):
            raise CombatError("invalid public blocker edges")

    def completion(self, prefix: tuple[Hashable | None, ...]) -> tuple[Hashable | None, ...] | None:
        """A deterministic valid completion, or None. No outcomes or hidden state."""
        if len(prefix) > len(self.blockers):
            raise CombatError("prefix exceeds blocker count")
        attackers = tuple(self.minimums)
        index = {attacker: slot for slot, attacker in enumerate(attackers)}
        counts = [0] * len(attackers)
        for blocker, choice in zip(self.blockers, prefix):
            if choice is not None:
                if choice not in self.edges[blocker]:
                    raise CombatError("prefix contains an illegal attacker edge")
                counts[index[choice]] += 1
        # Only attackers already chosen must satisfy their minimum. This is a
        # bipartite matching against deficit slots, with one use per blocker.
        deficits = tuple(max(0, self.minimums[attacker] - counts[slot]) if counts[slot] else 0
                         for slot, attacker in enumerate(attackers))
        remaining = self.blockers[len(prefix):]

        @lru_cache(maxsize=None)
        def match(position: int, need: tuple[int, ...]):
            if not any(need):
                return (None,) * (len(remaining) - position)
            if sum(need) > len(remaining) - position:
                return None
            if position == len(remaining):
                return None
            blocker = remaining[position]
            # Stable edge order is the engine's public declaration order.
            for attacker in self.edges[blocker]:
                slot = index[attacker]
                if need[slot]:
                    updated = list(need)
                    updated[slot] -= 1
                    tail = match(position + 1, tuple(updated))
                    if tail is not None:
                        return (attacker,) + tail
            tail = match(position + 1, need)
            return None if tail is None else (None,) + tail

        tail = match(0, deficits)
        return None if tail is None else prefix + tail

    def choices(self, prefix: tuple[Hashable | None, ...]) -> tuple[Hashable | None, ...]:
        if len(prefix) >= len(self.blockers):
            raise CombatError("declaration is already complete")
        blocker = self.blockers[len(prefix)]
        choices = (None,) + self.edges[blocker]
        result = tuple(choice for choice in choices if self.completion(prefix + (choice,)) is not None)
        if not result:
            raise CombatError("declaration has no legal completion")
        return result


def public_minimum(value) -> int:
    """The blockers an attacker needs once blocked. The native engine reads a
    public 0 as 1 (engine.rs minimum_blockers_required takes max(1)); a
    bestowed Nyxborn Hydra attacks with 0."""
    if type(value) is not int or value < 0:
        raise CombatError("invalid minimum blockers")
    return max(1, value)


def native_block_plan(raw: dict, support: dict, projection) -> tuple[BlockPlan, dict]:
    """Build only from the defender's actor-visible legal edges and facts.

    The bridge is still at the first scan decision. Buffer the entire v2
    declaration before translating it to the old attacker-major scan.
    """
    raw = normalized_zones(raw)
    surface = raw["projection"]
    reshape = surface["surface_context"]["private_blockers"]
    scan = surface["policy_surface_context"]["private_combat_selection"]
    if support.get("at_block_root") is not True or not isinstance(support.get("block_declaration_instance"), str):
        raise CombatError("block plan lacks the private declaration root marker")
    if not reshape or not scan or scan["candidate_index"] != 0 or scan["selected"] or reshape["accumulated"]:
        raise CombatError("block plan requires the untouched declaration root")
    attacker = reshape["current_attacker"]
    if attacker is None or native_key(attacker) != native_key(scan["attacker"]):
        raise CombatError("native blocker contexts disagree")
    pairs = [(attacker, [scan["current_candidate"], *scan["remaining_after_current"]]), *reshape["remaining"]]
    edges = {}
    refs = {}
    minimums = {}
    public = {native_key(card["stable"]): card for zone in surface["battlefield"] for card in zone}
    for attacker, blockers in pairs:
        attack_key = native_key(attacker)
        facts = public.get(attack_key)
        if facts is None:
            raise CombatError("native blocker graph contains an unobserved attacker")
        minimums[attack_key] = public_minimum(facts["characteristics"]["effective_keywords"]["minimum_blockers"])
        ref = projection.stable_ref(attacker)
        if ref is None:
            raise CombatError("attacker has no current public reference")
        refs[attack_key] = ref
        for blocker in blockers:
            key = native_key(blocker)
            ref = projection.stable_ref(blocker)
            if ref is None or key not in public:
                raise CombatError("blocker has no current public reference")
            refs[key] = ref
            edges.setdefault(key, []).append(attack_key)
    # Public battlefield order, never arena-number ordering or library order.
    order = tuple(native_key(card["stable"]) for zone in surface["battlefield"] for card in zone
                  if native_key(card["stable"]) in edges)
    return BlockPlan(order, {key: tuple(value) for key, value in edges.items()}, minimums), refs


class BlockDeclaration:
    def __init__(self, plan: BlockPlan, refs: dict):
        self.plan = plan
        self.refs = refs
        self.prefix = ()

    def semantics(self) -> list[dict]:
        blocker = self.plan.blockers[len(self.prefix)]
        return [{"kind": "declare_block", "blocker": self.refs[blocker],
                 "attacker": None if choice is None else self.refs[choice]}
                for choice in self.plan.choices(self.prefix)]

    def choose(self, candidate_id: int) -> bool:
        choices = self.plan.choices(self.prefix)
        if type(candidate_id) is not int or not 0 <= candidate_id < len(choices):
            raise CombatError("block candidate is out of range")
        self.prefix += (choices[candidate_id],)
        return len(self.prefix) == len(self.plan.blockers)

    def assignment(self) -> dict:
        if len(self.prefix) != len(self.plan.blockers):
            raise CombatError("block declaration is unfinished")
        if self.plan.completion(self.prefix) != self.prefix:
            raise CombatError("block declaration has no valid completion")
        return dict(zip(self.plan.blockers, self.prefix))


@dataclass(frozen=True)
class NativeBlockBinding:
    game_id: str
    instance: str
    assignment: Mapping[str, str | None]
    edges: Mapping[str, tuple[str, ...]]


def native_block_pick(view: dict, binding: NativeBlockBinding) -> int:
    """Bind a completed plan to one exact, normalized legacy scan pick."""
    support = view["extensions"].get("x_kernel_v2_support", {})
    if view.get("game_id") != binding.game_id or support.get("block_declaration_instance") != binding.instance:
        raise CombatError("completed plan belongs to another game or block declaration")
    allowed = set(view["extensions"]["x_kernel_flat_v4"]["row_candidate_ids"])
    result = []
    for candidate in view["candidates"]:
        semantic = candidate["semantic"]
        if semantic["kind"] != "choose_blocker_inclusion":
            raise CombatError("completed plan crossed the native blocker boundary")
        # Legacy references are private bindings, never emitted by this module.
        blocker = semantic["blocker"]["object_id"]
        attacker = semantic["attacker"]["object_id"]
        if blocker not in binding.assignment or attacker not in binding.edges.get(blocker, ()):
            raise CombatError("native scan is absent from the captured declaration graph")
        wanted = binding.assignment[blocker] == attacker
        if semantic["include"] == wanted and candidate["candidate_id"] in allowed:
            result.append(candidate["candidate_id"])
    if len(result) != 1:
        raise CombatError("completed v2 declaration does not bind to one native training row")
    return result[0]


def legacy_block_assignment(root: dict, plan: BlockPlan, assignment: dict) -> NativeBlockBinding:
    """Internal v1 binding only. These values never enter the neutral wire."""
    def legacy(key):
        return f"obj-{key[0]:06}-z{key[1]:04}"
    support = root["extensions"].get("x_kernel_v2_support", {})
    if support.get("at_block_root") is not True or not isinstance(support.get("block_declaration_instance"), str):
        raise CombatError("native binding requires the captured declaration root")
    if set(assignment) != set(plan.blockers):
        raise CombatError("assignment does not cover the captured blocker graph")
    prefix = tuple(assignment[blocker] for blocker in plan.blockers)
    if plan.completion(prefix) != prefix:
        raise CombatError("assignment is not a valid completion")
    return NativeBlockBinding(root["game_id"], support["block_declaration_instance"],
        {legacy(blocker): None if attacker is None else legacy(attacker) for blocker, attacker in assignment.items()},
        {legacy(blocker): tuple(legacy(attacker) for attacker in edges) for blocker, edges in plan.edges.items()})
