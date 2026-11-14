"""Write ``cards.json``: rules text for the cards of the Pauper pool, for the Manabrew client's card view.

Source: the XMage card data file in our mage repository (``Utils/mtg-cards-data.txt``: name|set|number|rarity|cost|
type line|power|toughness|text, with "$" between abilities). Tokens are not in that file; their text is below.
Run: ``python -m spellbench.human.manabrew.build_cards <mtg-cards-data.txt> <name> [<name> ...]``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOKENS = {
    "Eldrazi Spawn Token": {"type_line": "Token Creature - Eldrazi Spawn", "power": "0", "toughness": "1",
                            "text": "Sacrifice this creature: Add {C}."},
    "Map Token": {"type_line": "Token Artifact - Map",
                  "text": "{1}, {T}, Sacrifice this artifact: Target creature you control explores. Activate only "
                          "as a sorcery."},
    "Blood Token": {"type_line": "Token Artifact - Blood",
                    "text": "{1}, {T}, Discard a card, Sacrifice this artifact: Draw a card."},
    "Treasure Token": {"type_line": "Token Artifact - Treasure",
                       "text": "{T}, Sacrifice this artifact: Add one mana of any color."},
    "Clue Token": {"type_line": "Token Artifact - Clue", "text": "{2}, Sacrifice this artifact: Draw a card."},
    "Food Token": {"type_line": "Token Artifact - Food",
                   "text": "{2}, {T}, Sacrifice this artifact: You gain 3 life."},
    "Goblin Token": {"type_line": "Token Creature - Goblin", "power": "1", "toughness": "1", "text": ""},
    "Elf Warrior Token": {"type_line": "Token Creature - Elf Warrior", "power": "1", "toughness": "1", "text": ""},
    "Samurai Token": {"type_line": "Token Artifact Creature - Samurai", "power": "2", "toughness": "2",
                      "text": "Vigilance"},
    "Bird Token": {"type_line": "Token Creature - Bird", "power": "1", "toughness": "1", "text": "Flying"},
    "Spirit Token": {"type_line": "Token Creature - Spirit", "power": "1", "toughness": "1", "text": "Flying"},
}


def build(data_file: Path, names: list[str]) -> dict:
    wanted = set()
    for name in names:
        wanted.update(part.strip() for part in name.split("//"))
    found: dict[str, dict] = {}
    for line in data_file.read_text(encoding="utf-8").splitlines():
        parts = line.split("|")
        if len(parts) < 9 or parts[0] not in wanted or parts[0] in found:
            continue
        found[parts[0]] = {"mana_cost": parts[4], "type_line": parts[5], "power": parts[6] or None,
                           "toughness": parts[7] or None, "text": parts[8].replace("$", "\n")}
    out = {name: found[name] for name in sorted(found)}
    for name, token in TOKENS.items():
        out[name] = {"mana_cost": "", "power": None, "toughness": None, **token}
    missing = sorted(wanted - set(found))
    if missing:
        print(f"no text for: {missing}", file=sys.stderr)
    return out


if __name__ == "__main__":
    table = build(Path(sys.argv[1]), sys.argv[2:])
    target = Path(__file__).with_name("cards.json")
    target.write_text(json.dumps(table, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(table)} cards -> {target}")
