#!/usr/bin/env bash
# Rebuilds the shipped register (xmage/resources/spellbench/kit/xmage/register.json) from the pinned XMage sources,
# the pool catalog (the X5 catalog on branch xmage-x0-x1 until it merges) and the slice's fixture cards.
#
#   kit/register/build-register.sh XMAGE_SRC [CATALOG_JSON]
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
XMAGE="$1"
CATALOG="${2:-}"
if [ -z "$CATALOG" ]; then
  CATALOG=$(mktemp)
  git -C "$HERE" show origin/xmage-x0-x1:engines/xmage/overlay/src/main/resources/mage/player/spellbench/catalog.json > "$CATALOG"
fi
python "$HERE/scan.py" --xmage "$XMAGE" --catalog "$CATALOG" --out "$HERE/../xmage/resources/spellbench/kit/xmage/register.json" \
  --extra "Arc Lightning" "Burnished Hart" "Burst Lightning" "Cathar Commando" "Charming Prince" "Cultivate" "Forest" \
  "Grizzly Bears" "Helpful Hunter" "Inspiring Paladin" "Island" "Llanowar Elves" "Mountain" "Plains" "Refute" \
  "Rockface Village" "Screaming Nemesis" "Serra Angel" "Shock" "Stab" "Strix Lookout" "Swamp" "Thriving Bluff" "Youthful Valkyrie" "Kaito, Bane of Nightmares"
