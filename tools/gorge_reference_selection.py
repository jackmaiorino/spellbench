"""Restrict the frozen reference matrix to natively qualified gorge modes.

The original selection runs first, so seeds, seats, decks and replay order stay
bound to the full schedule. A restriction only drops games whose native seats
name a held mode; it never adds, reorders or renumbers a game.
"""
from collections import Counter

from spellbench.arena.allocation import ThroughputError

ALL_POLICIES = ['bot', 'bot-auto-pay', 'lethal-pressure', 'lethal-pressure-auto-pay', 'ar8', 'blocks',
                'explore', 'legacy', 'search', 'search-mana', 'search-redeal', 'search-mana-redeal']


def declared_matrix_policies(value):
    """Parse an ordered explicit selection; None or 'all' keeps every mode."""
    if value in (None, 'all'):
        return list(ALL_POLICIES)
    policies = value if isinstance(value, list) else value.split(',')
    if not policies or policies != [name for name in ALL_POLICIES if name in policies]:
        raise ThroughputError('Reference policy selection is not an ordered subset of the gorge modes')
    return policies


def restrict_matrix(chosen, expected, policies):
    names = {'gorge-' + name for name in declared_matrix_policies(policies)}
    kept = [context for context in chosen
            if all(spec.name in names for _, spec in context.seat_specs if spec.name.startswith('gorge-'))]
    cells = {cell: count for cell, count in expected.items() if cell[0] in names}
    observed = Counter((spec.name, context.decks[0].catalog_id) for context in kept
                       for _, spec in context.seat_specs if spec.name.startswith('gorge-'))
    if observed != Counter(cells) or len({name for name, _ in cells}) != len(names):
        raise ThroughputError('Restricted reference matrix omits a qualified policy/deck cell')
    return kept, cells


def matrix_counts(chosen, expected):
    """Games, cells and native participant receipts the matrix must close."""
    return len(chosen), len(expected), sum(expected.values())
