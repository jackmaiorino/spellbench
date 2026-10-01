#!/usr/bin/env bash
# Starts one kit agent process (protocol v2 agent role) on stdin/stdout: the front (kit-core) and, as its child, the
# runner (kit-xmage, one JVM with XMage). One process per seat and game (design K1).
#
#   kit/scripts/agent.sh --kit DIR --engine-build DIR --db DIR [--work DIR] [--xmx SIZE] [front options...]
#
# --kit           output of kit/build.sh
# --engine-build  output of engines/xmage/scripts/build.sh (the exact engine jars, K2)
# --db            the card database template (each agent copies it into its own work directory)
# --work          where per-agent work directories go (default: the system temp directory)
# Front options (passed through): --entry h1|h2|h3 --worlds K --skill S --log FILE --log-dir DIR (one log per game) --grace-ms N --overhead-ms N
#   --nodes N --options N --operations N --iterations N --rollout N --hang-at SEAT_STEP (the identity follows the configuration; overrides give a -custom name)
#
# The work directory (database copy, runner stderr) is removed when the front exits.
set -euo pipefail

KIT=""; ENGINE=""; DB=""; WORK="${TMPDIR:-/tmp}"; XMX=1536m
FRONT=()
while [ $# -gt 0 ]; do
  case "$1" in
    --kit) KIT="$2"; shift 2 ;;
    --engine-build) ENGINE="$2"; shift 2 ;;
    --db) DB="$2"; shift 2 ;;
    --work) WORK="$2"; shift 2 ;;
    --xmx) XMX="$2"; shift 2 ;;
    *) FRONT+=("$1" "$2"); shift 2 ;;
  esac
done
[ -n "$KIT" ] && [ -n "$ENGINE" ] && [ -n "$DB" ] || { echo "need --kit, --engine-build and --db" >&2; exit 2; }
native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
SEP=":"; command -v cygpath >/dev/null 2>&1 && SEP=";"

mkdir -p "$WORK"
DIR=$(mktemp -d "$WORK/kit-agent-XXXXXX")
cleanup() { rm -rf "$DIR"; }
trap cleanup EXIT
cp -R "$DB" "$DIR/db"
CP_RUNNER="$(native "$KIT/lib/kit-xmage.jar")${SEP}$(native "$KIT/lib/kit-core.jar")${SEP}$(native "$ENGINE/lib")/*"
java -Xmx128m -cp "$(native "$KIT/lib/kit-core.jar")" spellbench.kit.core.Front \
  --work "$(native "$DIR")" "${FRONT[@]}" \
  -- java -Xmx"$XMX" -XX:+UseSerialGC -cp "$CP_RUNNER" spellbench.kit.xmage.Runner
