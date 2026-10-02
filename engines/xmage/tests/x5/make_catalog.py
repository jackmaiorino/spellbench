"""X5: writes the engine catalog (overlay/src/main/resources/mage/player/spellbench/catalog.json) from both pools.

- Standard 2022-25 (format standard-2022-25-bo1): the 16 decks of MageZero's pool, read from its fork's .dck files
  (MIT; see ../../NOTICE). The two decks X2 put in the catalog (Standard16-RG, Standard16-UB) stay first, unchanged.
- FDN (format fdn-limited-bo1): the 16 decks staged for fdn-mirror-v0 (17lands FDN Premier Draft data, CC BY 4.0,
  via DraftZero; see ../../NOTICE), copied as staged.

Names are Oracle names in NFC: the .dck names (XMage's), except that a multi-face card the .dck names by its front
face (a transforming double-faced card or an adventure) takes its full name "A // B" (spec 4.4; FULL_NAMES, read
from the card classes at the XMage pin, each checked with validate_deck). Sideboards are ignored. A deck the engine cannot play is left out with its reason
(--exclude ID=REASON, after validate_deck.py).

    python make_catalog.py --magezero D:/community/mage-magezero --fdn .../fdn-mirror-v0-catalog.json [--exclude ID=REASON]
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATALOG = HERE.parents[1] / "overlay/src/main/resources/mage/player/spellbench/catalog.json"
STANDARD = ["Standard16-RG", "Standard16-UB"] + sorted(
    ["Standard-MonoB", "Standard-MonoG", "Standard-MonoR", "Standard-MonoU", "Standard-MonoW"]
    + [f"Standard16-{c}" for c in ("GB", "RB", "BW", "UG", "GW", "UR", "RW", "UW", "5C")])
STANDARD_FORMAT = "standard-2022-25-bo1"
# Multi-face cards of the Standard pool named by their front face in the .dck files (back face from the XMage card
# class at the pin: TransformingDoubleFacedCard or AdventureCard).
FULL_NAMES = {
    "Braided Net": "Braided Net // Braided Quipu",
    "Brutal Cathar": "Brutal Cathar // Moonrage Brute",
    "Cecil, Dark Knight": "Cecil, Dark Knight // Cecil, Redeemed Paladin",
    "Clay-Fired Bricks": "Clay-Fired Bricks // Cosmium Kiln",
    "Etali, Primal Conqueror": "Etali, Primal Conqueror // Etali, Primal Sickness",
    "Fable of the Mirror-Breaker": "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki",
    "Graveyard Trespasser": "Graveyard Trespasser // Graveyard Glutton",
    "Imodane's Recruiter": "Imodane's Recruiter // Train Troops",
    "Mosswood Dreadknight": "Mosswood Dreadknight // Dread Whispers",
    "Ojer Axonil, Deepest Might": "Ojer Axonil, Deepest Might // Temple of Power",
    "Polukranos Reborn": "Polukranos Reborn // Polukranos, Engine of Ruin",
    "Questing Druid": "Questing Druid // Seek the Beast",
    "Spring-Loaded Sawblades": "Spring-Loaded Sawblades // Bladewheel Chariot",
    "Thousand Moons Smithy": "Thousand Moons Smithy // Barracks of the Thousand",
    "Virtue of Loyalty": "Virtue of Loyalty // Ardenvale Fealty",
}
FDN_FORMAT = "fdn-limited-bo1"


def read_dck(path: Path) -> list[dict]:
    """Main-deck rows of an XMage .dck file ("N [SET:NUM] Name"), merged by name, in code point order."""
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("SB", "NAME", "LAYOUT")):
            continue
        count, rest = line.split(" ", 1)
        if rest.startswith("["):
            rest = rest.split("]", 1)[1].strip()
        name = unicodedata.normalize("NFC", FULL_NAMES.get(rest, rest))
        counts[name] = counts.get(name, 0) + int(count)
    return [{"name": n, "count": c} for n, c in sorted(counts.items())]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--magezero", required=True, help="MageZero's XMage fork (Mage.Tests/decks)")
    parser.add_argument("--fdn", required=True, help="the staged fdn-mirror-v0 catalog")
    parser.add_argument("--exclude", action="append", default=[], help="ID=REASON, a deck left out")
    args = parser.parse_args()
    excluded = dict(item.split("=", 1) for item in args.exclude)
    old = {d["catalog_id"]: d for d in json.loads(CATALOG.read_text(encoding="utf-8"))}
    decks = []
    for deck_id in STANDARD:
        rows = read_dck(Path(args.magezero) / "Mage.Tests/decks" / f"{deck_id}.dck")
        if deck_id in old and sorted((FULL_NAMES.get(r["name"], r["name"]), r["count"])
                                     for r in old[deck_id]["decklist"]) != [(r["name"], r["count"]) for r in rows]:
            print(f"{deck_id}: differs from the catalog entry X2 wrote", file=sys.stderr)
            return 1
        decks.append({"catalog_id": deck_id, "name": deck_id, "formats": [STANDARD_FORMAT], "decklist": rows})
    for deck in json.loads(Path(args.fdn).read_text(encoding="utf-8")):
        if deck["formats"] != [FDN_FORMAT]:
            print(f"{deck['catalog_id']}: unexpected formats {deck['formats']}", file=sys.stderr)
            return 1
        rows = [{"name": unicodedata.normalize("NFC", r["name"]), "count": r["count"]} for r in deck["decklist"]]
        decks.append({"catalog_id": deck["catalog_id"], "name": deck["name"], "formats": deck["formats"],
                      "decklist": rows})
    for deck in decks:
        total = sum(r["count"] for r in deck["decklist"])
        minimum = 40 if deck["formats"] == [FDN_FORMAT] else 60
        if total < minimum:
            print(f"{deck['catalog_id']}: {total} cards, below {minimum}", file=sys.stderr)
            return 1
    kept = [d for d in decks if d["catalog_id"] not in excluded]
    CATALOG.write_text(json.dumps(kept, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"catalog: {len(kept)} decks ({sum(STANDARD_FORMAT in d['formats'] for d in kept)} standard, "
          f"{sum(FDN_FORMAT in d['formats'] for d in kept)} fdn); excluded: {excluded or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
