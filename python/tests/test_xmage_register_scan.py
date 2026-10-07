"""Constructor types distinguish land choices from spell effect filters."""
import importlib.util
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "constructor, effect, expected",
    [
        ('super(ownerId, setInfo, new CardType[]{CardType.ENCHANTMENT}, "{2}{U}");',
         'filter.add(Predicates.not(CardType.LAND.getPredicate()));', 'supported'),
        ('super(ownerId, setInfo, new CardType[]{CardType.LAND}, "");', '', 'approximate'),
        ('super(ownerId, setInfo, new CardType[]{CardType.ARTIFACT, CardType.LAND}, "");', '', 'approximate'),
        ('super(ownerId, setInfo, dynamicTypes(), "");', 'CardType.LAND;', 'approximate'),
    ],
)
def test_nonstack_land_choice_uses_constructor_types(tmp_path, constructor, effect, expected):
    scanner = Path(__file__).resolve().parents[2] / "engines/xmage/kit/register/scan.py"
    spec = importlib.util.spec_from_file_location("xmage_register_scan", scanner)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / "mage/cards/s/ScanCard.java"
    path.parent.mkdir(parents=True)
    path.write_text(
        'package mage.cards.s; class ScanCard { ScanCard() {' + constructor
        + 'new AsEntersBattlefieldAbility(new ChooseColorEffect(Outcome.Detriment));'
        + effect + '}}', encoding="utf-8"
    )
    entry = module.scan_card("Scan Card", "mage.cards.s.ScanCard", str(tmp_path), {}, {})
    assert entry["status"] == expected
    assert ("non_stack_choices" in entry) == (expected == "approximate")


def _load_scanner():
    scanner = Path(__file__).resolve().parents[2] / "engines/xmage/kit/register/scan.py"
    spec = importlib.util.spec_from_file_location("xmage_register_scan_main", scanner)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_xmage(root: Path) -> None:
    (root / "Mage/src/main/java/mage").mkdir(parents=True)
    sets = root / "Mage.Sets/src/mage/sets"
    sets.mkdir(parents=True)
    (sets / "Fake.java").write_text(
        'cards.add(new SetCardInfo("Alpha", 1, Rarity.COMMON, mage.cards.a.Alpha.class));\n'
        'cards.add(new SetCardInfo("Beta", 2, Rarity.COMMON, mage.cards.b.Beta.class));\n', encoding="utf-8")
    for letter, name in (("a", "Alpha"), ("b", "Beta")):
        path = root / f"Mage.Sets/src/mage/cards/{letter}/{name}.java"
        path.parent.mkdir(parents=True)
        path.write_text(f'package mage.cards.{letter}; class {name} {{ {name}() {{'
                        'super(ownerId, setInfo, new CardType[]{CardType.INSTANT}, "{R}"); }}', encoding="utf-8")


def test_several_catalogs_and_kept_extensions(tmp_path, monkeypatch):
    import json
    import sys
    module = _load_scanner()
    _fake_xmage(tmp_path / "xmage")
    first = tmp_path / "first.json"
    first.write_text(json.dumps([{"catalog_id": "A", "decklist": [{"name": "Alpha", "count": 4}]}]), encoding="utf-8")
    second = tmp_path / "second.json"
    second.write_text(json.dumps([{"catalog_id": "B", "decklist": [{"name": "Beta", "count": 4},
                                                                  {"name": "Gamma", "count": 1}]}]), encoding="utf-8")
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"cards": {"Kept": {"class": "mage.cards.k.Kept", "status": "supported"}},
                               "source_extensions": {"Kept": {"scope": "reviewed"}}}), encoding="utf-8")
    out = tmp_path / "register.json"
    monkeypatch.setattr(sys, "argv", ["scan.py", "--xmage", str(tmp_path / "xmage"), "--catalog", str(first),
                                      "--catalog", str(second), "--keep-extensions", str(old), "--out", str(out)])
    module.main()
    register = json.loads(out.read_text(encoding="utf-8"))
    assert set(register["admission"]) == {"A", "B"}
    assert register["admission"]["A"]["admitted"]
    assert register["admission"]["B"]["unsupported_cards"] == ["Gamma"]
    assert register["cards"]["Kept"] == {"class": "mage.cards.k.Kept", "status": "supported"}
    assert register["source_extensions"] == {"Kept": {"scope": "reviewed"}}


def test_duplicate_deck_ids_are_refused(tmp_path, monkeypatch):
    import json
    import sys
    module = _load_scanner()
    _fake_xmage(tmp_path / "xmage")
    catalog = tmp_path / "c.json"
    catalog.write_text(json.dumps([{"catalog_id": "A", "decklist": [{"name": "Alpha", "count": 4}]}]), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["scan.py", "--xmage", str(tmp_path / "xmage"), "--catalog", str(catalog),
                                      "--catalog", str(catalog), "--out", str(tmp_path / "r.json")])
    with pytest.raises(SystemExit):
        module.main()


def test_pauper_kernel_decks_are_the_benchmark_pool():
    import json
    root = Path(__file__).resolve().parents[2]
    decks = json.loads((root / "engines/xmage/kit/register/pauper-kernel-decks.json").read_text(encoding="utf-8"))
    pool = json.loads((root / "benchmarks/pauper-kernel-v2/benchmark.json").read_text(encoding="utf-8"))["deck_pool"]
    assert [d["catalog_id"] for d in decks] == pool
    assert all(sum(r["count"] for r in d["decklist"]) == 60 for d in decks)
    register = json.loads((root / "engines/xmage/kit/xmage/resources/spellbench/kit/xmage/register.json")
                          .read_text(encoding="utf-8"))
    assert all(register["admission"][deck]["admitted"] for deck in pool)
