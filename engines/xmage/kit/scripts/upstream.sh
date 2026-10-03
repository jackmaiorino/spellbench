#!/usr/bin/env bash
# The published kit diffs and the E7 reference build.
#
#   kit/scripts/upstream.sh --xmage-repo DIR --kit-build DIR --engine-build DIR
#
# 1. Extracts the upstream MAD and MCTS sources at the XMage pin and writes kit/diffs/kit-mad.diff and
#    kit/diffs/kit-mcts.diff: the vendored copies (kit/xmage/src/mage/player/ai) against upstream, line endings
#    normalized.
# 2. Builds the E7 reference: upstream ComputerPlayer6/7, SimulatedPlayer2 and SimulationNode2 renamed into package
#    mage.player.ai.upstream, with the same X-P4 candidate (KitPayPlayer) as the kit and nothing else changed, plus
#    the probe in kit/xmage/e7/ -> KIT_BUILD/lib/kit-upstream.jar (never on an entry's classpath).
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
XMAGE=""; KITB=""; ENGINE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --xmage-repo) XMAGE="$2"; shift 2 ;;
    --kit-build) KITB="$2"; shift 2 ;;
    --engine-build) ENGINE="$2"; shift 2 ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
. "$HERE/../pins.env"
native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
SEP=":"; command -v cygpath >/dev/null 2>&1 && SEP=";"
T=$KITB/upstream
rm -rf "$T"; mkdir -p "$T/src" "$T/classes"
git -C "$XMAGE" -c core.autocrlf=false archive --format=tar "$XMAGE_COMMIT" -- \
  Mage.Server.Plugins/Mage.Player.AI.MAD/src Mage.Server.Plugins/Mage.Player.AIMCTS/src | tar -x -C "$T/src"

# 1. diffs
mkdir -p "$HERE/diffs"
for pair in "mad:Mage.Player.AI.MAD" "mcts:Mage.Player.AIMCTS"; do
  name=${pair%%:*}; mod=${pair#*:}
  out="$HERE/diffs/kit-$name.diff"
  : > "$out"
  for f in $(cd "$T/src/Mage.Server.Plugins/$mod/src" && find . -name '*.java' | LC_ALL=C sort); do
    kit="$HERE/xmage/src/$f"
    [ -f "$kit" ] || continue
    # the vendored copy's first line is the MIT attribution header; compare the rest
    tail -n +2 "$kit" | tr -d '\r' > "$T/kit.java"
    tr -d '\r' < "$T/src/Mage.Server.Plugins/$mod/src/$f" > "$T/up.java"
    diff -u --label "upstream/$mod/src/${f#./}" --label "kit/xmage/src/${f#./}" "$T/up.java" "$T/kit.java" >> "$out" || true
  done
  echo "$out: $(grep -c '^[-+][^-+]' "$out" || true) changed lines"
done

# 2. the E7 reference
U=$T/e7src/mage/player/ai/upstream
mkdir -p "$U"
for f in ComputerPlayer6 ComputerPlayer7 SimulatedPlayer2 SimulationNode2; do
  sed -e 's/^package mage\.player\.ai;/package mage.player.ai.upstream;\nimport mage.player.ai.*;/' \
      -e 's/extends ComputerPlayer {/extends KitPayPlayer {/' \
      -e 's/COMPUTER_MAX_THREADS_FOR_SIMULATIONS/5 \/* ComputerPlayer.COMPUTER_MAX_THREADS_FOR_SIMULATIONS, package-private *\//g' \
      "$T/src/Mage.Server.Plugins/Mage.Player.AI.MAD/src/mage/player/ai/$f.java" > "$U/$f.java"
done
cp "$HERE/xmage/e7/"*.java "$U/"
CP="$(native "$KITB/lib/kit-xmage.jar")${SEP}$(native "$KITB/lib/kit-core.jar")${SEP}$(native "$ENGINE/lib")/*"
find "$T/e7src" -name '*.java' > "$T/e7-sources.txt"
if command -v cygpath >/dev/null 2>&1; then
  while read -r p; do cygpath -m "$p"; done < "$T/e7-sources.txt" > "$T/e7.win" && mv "$T/e7.win" "$T/e7-sources.txt"
fi
javac --release 8 -encoding UTF-8 -nowarn -Xlint:-options -cp "$CP" -d "$(native "$T/classes")" @"$(native "$T/e7-sources.txt")"
JAR=jar
if ! command -v jar >/dev/null 2>&1; then
  for d in "${JAVA_HOME:-}" "/c/Program Files/Java/"*; do
    if [ -n "$d" ] && [ -x "$d/bin/jar" -o -x "$d/bin/jar.exe" ]; then JAR="$d/bin/jar"; fi
  done
fi
"$JAR" --create --file "$(native "$KITB/lib/kit-upstream.jar")" -C "$(native "$T/classes")" .
echo "built $KITB/lib/kit-upstream.jar"
