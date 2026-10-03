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
