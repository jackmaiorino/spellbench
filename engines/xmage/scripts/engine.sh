#!/usr/bin/env bash
# Starts one XMage engine process (protocol v2 environment role) on stdin/stdout, as a Spellbench host or
# `spellbench conformance engine -- scripts/engine.sh ...` launches it.
#
#   scripts/engine.sh --build DIR --db DIR [--work DIR] [--xmx SIZE]
#
# --build  output of scripts/build.sh
# --db     a card database built once with `DeterminismCheck --scan-only` (the directory named db)
# --work   where per-process working directories go (default: the system temp directory)
#
# Each process works in a fresh directory with its own copy of the card database (design D3: two JVMs on one
# database crash), removed when the engine exits.
set -euo pipefail

BUILD=""
DB=""
WORK="${TMPDIR:-/tmp}"
XMX=2g
while [ $# -gt 0 ]; do
  case "$1" in
    --build) BUILD="$2"; shift 2 ;;
    --db) DB="$2"; shift 2 ;;
    --work) WORK="$2"; shift 2 ;;
    --xmx) XMX="$2"; shift 2 ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
[ -n "$BUILD" ] && [ -n "$DB" ] || { echo "need --build and --db" >&2; exit 2; }
native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }

mkdir -p "$WORK"
DIR=$(mktemp -d "$WORK/xmage-engine-XXXXXX")
trap 'rm -rf "$DIR"' EXIT
cp -R "$DB" "$DIR/db"
cd "$DIR"
java -Xmx"$XMX" -cp "$(native "$BUILD/lib")/*" mage.player.spellbench.server.EngineServer
