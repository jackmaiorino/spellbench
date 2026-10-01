#!/usr/bin/env bash
# Builds the Spellbench XMage engine (task X0): XMage at the pin, CABT vendored at its pin, the X patch series,
# and the Spellbench overlay. Runs in Git Bash on Windows and in bash on Linux.
#
#   scripts/build.sh --out DIR [--xmage-repo PATH] [--m2 PATH] [--stock]
#
# --out         a directory outside this repository; it is wiped and rebuilt
# --xmage-repo  a clone of XMage that contains (or can fetch) the pinned commit (default ../xmage-src next to --out)
# --m2          Maven local repository (default ~/.m2/repository)
# --stock       skip the patch series and the stream router: the negative control for task X1
#
# Output: DIR/lib (jars and classpath.txt) and DIR/BUILD-MANIFEST.json (pins, identity strings, jar hashes).
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
. "$HERE/pins.env"
OUT=""
XMAGE_REPO=""
M2="${HOME}/.m2/repository"
STOCK=0
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --xmage-repo) XMAGE_REPO="$2"; shift 2 ;;
    --m2) M2="$2"; shift 2 ;;
    --stock) STOCK=1; shift ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
[ -n "$OUT" ] || { echo "--out is required" >&2; exit 2; }
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
case "$OUT/" in "$HERE"/*) echo "--out must be outside the repository" >&2; exit 2 ;; esac
[ -n "$XMAGE_REPO" ] || XMAGE_REPO="$(dirname "$OUT")/xmage-src"

# native paths for Maven and Java on Windows
native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
sha256() { sha256sum | cut -c1-64; }
PYTHON=python3
"$PYTHON" -c 'import sys' >/dev/null 2>&1 || PYTHON=python

# 1. XMage sources at the pin (LF line endings on every OS)
if [ ! -d "$XMAGE_REPO/.git" ] && [ ! -f "$XMAGE_REPO/HEAD" ]; then
  git init -q "$XMAGE_REPO"
  git -C "$XMAGE_REPO" remote add origin "$XMAGE_UPSTREAM"
fi
if ! git -C "$XMAGE_REPO" cat-file -e "$XMAGE_COMMIT^{commit}" 2>/dev/null; then
  git -C "$XMAGE_REPO" fetch --depth 1 origin "$XMAGE_COMMIT"
fi
rm -rf "$OUT/src" "$OUT/lib"
mkdir -p "$OUT/src" "$OUT/lib"
SRC="$OUT/src"
PATHS=$(git -C "$XMAGE_REPO" ls-tree -r --name-only "$XMAGE_COMMIT" | grep 'pom\.xml$' | grep -v '^Mage\.Sets/\|^Mage/\|^Mage\.Common/' || true)
git -C "$XMAGE_REPO" -c core.autocrlf=false archive --format=tar "$XMAGE_COMMIT" -- \
  $PATHS Mage Mage.Common Mage.Sets Mage.Server.Plugins/Mage.Player.AI | tar -x -C "$SRC"

# 2. CABT, vendored at CABT_COMMIT, overlaid as its own build does
cp -R "$HERE/vendor/cabt/Mage.Server.Plugins/Mage.Player.AI/." "$SRC/Mage.Server.Plugins/Mage.Player.AI/"
"$PYTHON" "$HERE/vendor/cabt/services/engine/prepare_reference.py" "$(native "$SRC")"

# 3. build-only patches (both builds), then the X patch series (skipped for the stock negative control)
ls "$HERE"/patches/build-only/*.patch >/dev/null || { echo "missing patches/build-only" >&2; exit 1; }
for p in $(ls "$HERE"/patches/build-only/*.patch | LC_ALL=C sort); do
  (cd "$SRC" && GIT_CEILING_DIRECTORIES="$OUT" git apply --whitespace=nowarn "$p")
done
PATCHES=$(ls "$HERE"/patches/xmage/*.patch | LC_ALL=C sort)
if [ "$STOCK" = 0 ]; then
  for p in $PATCHES; do
    (cd "$SRC" && GIT_CEILING_DIRECTORIES="$OUT" git apply --whitespace=nowarn "$p")
  done
fi

# 4. identity strings (Section 9.1; README "Engine identity strings")
if [ "$STOCK" = 0 ]; then
  XPAT=$(cat $PATCHES | sha256)
  SETS_XPAT=$(cat $PATCHES | awk '/^diff --git /{keep = ($3 ~ /^a\/Mage\.Sets\//)} keep' | sha256)
else
  XPAT=none
  SETS_XPAT=none
fi
SETS_TREE=$(git -C "$XMAGE_REPO" rev-parse "$XMAGE_COMMIT:Mage.Sets")
RULES_ID="xmage-$XMAGE_COMMIT-xpat-$XPAT"
POOL_ID="xmage-sets-$SETS_TREE-xpat-$SETS_XPAT"

# 5. the Spellbench overlay; the stream router, the v2 server and its decision mapper only with the patch series
#    they rely on
MOD="$SRC/Mage.Server.Plugins/Mage.Player.AI"
OVL="$MOD/src/main/java/mage/player/spellbench"
RES="$MOD/src/main/resources/mage/player/spellbench"
mkdir -p "$OVL" "$RES"
cp -R "$HERE/overlay/src/main/java/mage/player/spellbench/." "$OVL/"
cp -R "$HERE/overlay/src/main/resources/mage/player/spellbench/." "$RES/"
[ "$STOCK" = 0 ] || rm -rf "$OVL/rng" "$OVL/server" "$OVL/decide" "$OVL/x3"
printf 'rules_snapshot_id=%s\ncard_pool_identity=%s\n' "$RULES_ID" "$POOL_ID" > "$RES/engine-identity.properties"

# 6. compile and package (no install: stock and patched builds never share Maven coordinates)
: "${MAVEN_OPTS:=-Xmx6g}"
export MAVEN_OPTS
mvn -B -q -f "$(native "$SRC/pom.xml")" -pl Mage.Server.Plugins/Mage.Player.AI -am \
  -DskipTests -Djacoco.skip=true -Dmaven.repo.local="$(native "$M2")" \
  -Dproject.build.outputTimestamp="$OUTPUT_TIMESTAMP" \
  package dependency:build-classpath -Dmdep.outputFile=target/classpath.txt -Dmdep.pathSeparator='|' -Dmdep.includeScope=runtime

# 7. lib/: the four module jars plus their dependencies, and a lib-relative classpath
CP_FILE="$SRC/Mage.Server.Plugins/Mage.Player.AI/target/classpath.txt"
: > "$OUT/lib/classpath.txt"
for f in "$SRC"/Mage.Server.Plugins/Mage.Player.AI/target/mage-player-ai-*.jar $(tr '|' '\n' < "$CP_FILE"); do
  [ -n "$f" ] || continue
  if command -v cygpath >/dev/null 2>&1; then f=$(cygpath -u "$f"); fi
  case "$f" in *.jar) ;; *) continue ;; esac
  b=$(basename "$f")
  cp "$f" "$OUT/lib/$b"
  echo "$b" >> "$OUT/lib/classpath.txt"
done

# 8. the build manifest
JAVA_V=$(java -version 2>&1 | head -1)
MVN_V=$(mvn -B -v 2>/dev/null | head -1 | tr -d '\r' | sed 's/\x1b\[[0-9;]*m//g')
{
  echo "{"
  echo "  \"xmage_commit\": \"$XMAGE_COMMIT\","
  echo "  \"cabt_commit\": \"$CABT_COMMIT\","
  echo "  \"patch_series\": \"$( [ "$STOCK" = 0 ] && echo applied || echo none )\","
  echo "  \"rules_snapshot_id\": \"$RULES_ID\","
  echo "  \"card_pool_identity\": \"$POOL_ID\","
  echo "  \"jdk\": \"$(printf '%s' "$JAVA_V" | sed 's/"/\\"/g')\","
  echo "  \"maven\": \"$MVN_V\","
  echo "  \"jars\": {"
  (cd "$OUT/lib" && LC_ALL=C ls *.jar | while read -r j; do printf '    "%s": "%s",\n' "$j" "$(sha256 < "$j")"; done) | sed '$ s/,$//'
  echo "  },"
  echo "  \"lib_digest\": \"$(cd "$OUT/lib" && LC_ALL=C ls *.jar | while read -r j; do printf '%s  %s\n' "$(sha256 < "$j")" "$j"; done | sha256)\""
  echo "}"
} > "$OUT/BUILD-MANIFEST.json"
cat "$OUT/BUILD-MANIFEST.json"
