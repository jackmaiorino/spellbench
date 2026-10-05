#!/usr/bin/env bash
# Builds the XMage agent kit (design A0 revision 3, Section 2): kit-core (no XMage imports) and kit-xmage (the
# runner, the world builder, the vendored MAD and MCTS copies with the kit diff, and the shared library into the
# engine overlay), compiled at Java 8 source level against the engine's exact jars.
#
#   kit/build.sh --engine-build DIR --out DIR
#
# --engine-build  output of engines/xmage/scripts/build.sh (lib/ and BUILD-MANIFEST.json)
# --out           a directory outside the repository; lib/ gets kit-core.jar and kit-xmage.jar, plus KIT-MANIFEST.json
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ENGINE=""
OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --engine-build) ENGINE="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
[ -n "$ENGINE" ] && [ -n "$OUT" ] || { echo "need --engine-build and --out" >&2; exit 2; }
native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
SEP=":"; command -v cygpath >/dev/null 2>&1 && SEP=";"
sha256() { sha256sum | cut -c1-64; }

mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
rm -rf "$OUT/classes-core" "$OUT/classes-xmage" "$OUT/lib"
mkdir -p "$OUT/classes-core" "$OUT/classes-xmage" "$OUT/lib"

find "$HERE/core/src" -name '*.java' | LC_ALL=C sort > "$OUT/core-sources.txt"
find "$HERE/xmage/src" -name '*.java' | LC_ALL=C sort > "$OUT/xmage-sources.txt"
if command -v cygpath >/dev/null 2>&1; then
  for f in core xmage; do
    while read -r p; do cygpath -m "$p"; done < "$OUT/$f-sources.txt" > "$OUT/$f-sources.win" && mv "$OUT/$f-sources.win" "$OUT/$f-sources.txt"
  done
fi

JAVAC_OPTS=(--release 8 -encoding UTF-8 -nowarn -Xlint:-options)
javac "${JAVAC_OPTS[@]}" -d "$(native "$OUT/classes-core")" @"$(native "$OUT/core-sources.txt")"
javac "${JAVAC_OPTS[@]}" -cp "$(native "$OUT/classes-core")${SEP}$(native "$ENGINE/lib")/*" \
  -d "$(native "$OUT/classes-xmage")" @"$(native "$OUT/xmage-sources.txt")"

# resources (the mechanics register) go into the kit-xmage jar
if [ -d "$HERE/xmage/resources" ]; then
  cp -R "$HERE/xmage/resources/." "$OUT/classes-xmage/"
fi

# The Windows PATH can contain JDK 23 java/javac and a JDK 8 jar. Resolve
# the archiver from the running pinned JDK rather than accepting that mix.
[ "$(javac -version 2>&1 | sed -n '/^javac /p')" = "javac 23.0.1" ] || { echo "JDK 23.0.1 required" >&2; exit 2; }
KIT_JDK_DIR=$(java -XshowSettings:properties -version 2>&1 | sed -n 's/^ *java.home = //p' | tr -d '\r')
if command -v cygpath >/dev/null 2>&1; then KIT_JDK_DIR=$(cygpath -u "$KIT_JDK_DIR"); fi
JAR="$KIT_JDK_DIR/bin/jar"
if [ -x "$KIT_JDK_DIR/bin/jar.exe" ]; then JAR="$KIT_JDK_DIR/bin/jar.exe"; fi
[ -x "$JAR" ] || { echo "pinned JDK archiver unavailable" >&2; exit 2; }
STAMP=2026-09-18T22:54:08Z
"$JAR" --create --date="$STAMP" --file "$(native "$OUT/lib/kit-core.jar")" -C "$(native "$OUT/classes-core")" .
"$JAR" --create --date="$STAMP" --file "$(native "$OUT/lib/kit-xmage.jar")" -C "$(native "$OUT/classes-xmage")" .

ENGINE_DIGEST=$(grep -o '"lib_digest": "[0-9a-f]*"' "$ENGINE/BUILD-MANIFEST.json" | cut -d'"' -f4)
RULES_ID=$(grep -o '"rules_snapshot_id": "[^"]*"' "$ENGINE/BUILD-MANIFEST.json" | cut -d'"' -f4)
SRC_DIGEST=$(cd "$HERE" && find core/src xmage/src xmage/resources -type f | LC_ALL=C sort | while read -r f; do printf '%s  %s\n' "$(sha256 < "$f")" "$f"; done | sha256)
{
  echo "{"
  echo "  \"kit_version\": \"0.3.0\","
  echo "  \"engine_lib_digest\": \"$ENGINE_DIGEST\","
  echo "  \"engine_rules_snapshot_id\": \"$RULES_ID\","
  echo "  \"kit_source_digest\": \"$SRC_DIGEST\","
  echo "  \"jdk\": \"$(java -version 2>&1 | awk '/^(openjdk|java) version /{print; exit}' | sed 's/"/\\"/g')\","
  echo "  \"jars\": {"
  echo "    \"kit-core.jar\": \"$(sha256 < "$OUT/lib/kit-core.jar")\","
  echo "    \"kit-xmage.jar\": \"$(sha256 < "$OUT/lib/kit-xmage.jar")\""
  echo "  }"
  echo "}"
} > "$OUT/KIT-MANIFEST.json"
cat "$OUT/KIT-MANIFEST.json"
