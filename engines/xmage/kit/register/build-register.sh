#!/usr/bin/env bash
# Rebuilds the shipped register (xmage/resources/spellbench/kit/xmage/register.json) from the pinned XMage sources,
# the XMage engine's deck catalog, the pauper-kernel decks and the slice's fixture cards. The reviewed
# source_extensions rows of the current register are kept unchanged.
#
#   kit/register/build-register.sh XMAGE_SRC
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
XMAGE="$1"
REGISTER="$HERE/../xmage/resources/spellbench/kit/xmage/register.json"
PYTHON=python3
"$PYTHON" -c 'import sys' >/dev/null 2>&1 || PYTHON=python
"$PYTHON" "$HERE/scan.py" --xmage "$XMAGE" \
  --catalog "$HERE/../../overlay/src/main/resources/mage/player/spellbench/catalog.json" \
  --catalog "$HERE/pauper-kernel-decks.json" \
  --keep-extensions "$REGISTER" --out "$REGISTER" \
  --extra "Arc Lightning" "Burnished Hart" "Burst Lightning" "Cathar Commando" "Charming Prince" "Cultivate" "Forest" \
  "Grizzly Bears" "Helpful Hunter" "Inspiring Paladin" "Island" "Llanowar Elves" "Mountain" "Plains" "Refute" \
  "Rockface Village" "Screaming Nemesis" "Serra Angel" "Shock" "Stab" "Strix Lookout" "Swamp" "Thriving Bluff" "Youthful Valkyrie" "Kaito, Bane of Nightmares"
