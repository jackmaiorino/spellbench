"""The unrated coverage probes preserve the frozen rated schedule and its clocks."""
from collections import Counter
import importlib.util
from pathlib import Path

from spellbench.arena.config import TournamentConfig
from spellbench.arena.schedule import schedule
from spellbench.bench.definition import load_benchmark
from spellbench.run_secret import RunSecret
from spellbench.bench.run import QualificationPlay
import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('failed', [False, True])
def test_reference_measurement_preserves_required_finalizer_and_audit_directory(monkeypatch, tmp_path, failed):
    monkeypatch.setenv('GORGE_CLOUD_STAGE', str(tmp_path/'unstarted'))
    monkeypatch.setenv('GORGE_AGENT_AUDIT_DIR', str(tmp_path/'unused'))
    spec = importlib.util.spec_from_file_location('gorge_reference_cleanup',
        REPO/'engines/gorge/scripts/reference_matrix.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    def play(workers, positions):
        calls.append((workers, positions, module.os.environ['GORGE_AGENT_AUDIT_DIR']))
        if failed:
            raise RuntimeError('fixture game failure')
        return 1.0, ()
    measured = module.audited_qualification(QualificationPlay(play, lambda: calls.append('finished')),
        {'trial': 0, 'directory': None}, tmp_path)
    try:
        if failed:
            with pytest.raises(RuntimeError, match='fixture game failure'):
                measured(2, (0, 1))
        else:
            assert measured(2, (0, 1)) == (1.0, ())
    finally:
        measured.finish()
    assert calls[-1] == 'finished'
    assert Path(calls[0][2]) == tmp_path/'guard-native-audits/trial-1-workers-2'
    assert not (tmp_path/'PRIVATE-GUARD-SECRET.json').exists()


def test_reference_probes_preserve_original_seeds_seats_and_replay(monkeypatch, tmp_path):
    monkeypatch.setenv('GORGE_CLOUD_STAGE', str(tmp_path/'unstarted'))
    spec = importlib.util.spec_from_file_location('gorge_reference_matrix',
                                                REPO/'engines/gorge/scripts/reference_matrix.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    benchmark = load_benchmark(REPO/'benchmarks/pauper-gorge')
    cfg = TournamentConfig.from_json(benchmark.tournament_config(str(tmp_path/'diagnostics')))
    original_config = cfg.to_json()
    contexts = schedule(cfg, RunSecret.from_hex('23'*32))
    chosen, expected = module.select_matrix(contexts)

    original = [c for c in contexts if c.pair_index < 5
                and 'uniform' in {s.name for _, s in c.seat_specs}
                and any(s.name.startswith('gorge-') for _, s in c.seat_specs)]
    original.sort(key=lambda c: (not any('search' in s.name for _, s in c.seat_specs), c.game_index))
    assert len(contexts) == 3640
    assert len(original) == 120 and chosen[:120] == original
    assert all(c is contexts[c.game_index] for c in chosen)
    assert len(chosen) == len({c.game_index for c in chosen}) == 140
    # Appending probes leaves the preselected search/Burn replay untouched.
    original_replay = next(c for c in original if c.decks[0].catalog_id == 'Burn'
                           and any('search' in s.name for _, s in c.seat_specs))
    actual_replay = next(c for c in chosen if c.decks[0].catalog_id == 'Burn'
                         and any('search' in s.name for _, s in c.seat_specs))
    assert actual_replay is original_replay

    probes = chosen[120:]
    probe_cells = Counter()
    partners = {}
    for context in probes:
        names = {s.name for _, s in context.seat_specs}
        assert names in ({'gorge-search', 'gorge-bot'}, {'gorge-search-mana', 'gorge-bot'})
        search = next(s.name for _, s in context.seat_specs if s.name != 'gorge-bot')
        probe_cells[(search, context.decks[0].catalog_id)] += 1
        partners.setdefault((context.matchup_index, context.pair_index), []).append(context)
    assert len(probe_cells) == 10 and set(probe_cells.values()) == {2}
    assert len(partners) == 10
    for pair in partners.values():
        first, second = sorted(pair, key=lambda c: c.pair_slot)
        assert (first.pair_slot, second.pair_slot) == (0, 1)
        assert first.seat_specs[0][1] == second.seat_specs[1][1]
        assert first.seat_specs[1][1] == second.seat_specs[0][1]
        assert first.decks == second.decks
    assert len(expected) == 60
    for (policy, deck), games in expected.items():
        assert deck in {'Wildfire', 'Rally', 'Spy', 'Burn', 'CawGates'}
        assert games == (6 if policy == 'gorge-bot' else
                         4 if policy in {'gorge-search', 'gorge-search-mana'} else 2)
    assert sum(expected.values()) == 160  # Both native participants have receipts.
    assert cfg.to_json() == original_config
