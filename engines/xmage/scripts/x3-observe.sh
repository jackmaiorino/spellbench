#!/usr/bin/env bash
# Task X3 evidence: seeded random games in-process, both seats' observations at every prompt, checked with the
# reference validator (P's Python stack) and the X3 invariants (tests/x3/check_observations.py).
#
#   scripts/x3-observe.sh --build DIR --db DIR --p2 DIR --work DIR [--catalog-games N] [--facedown-games N]
#                         [--shards K]
#
# --build           output of scripts/build.sh (patched)
# --db              a card database template (DeterminismCheck --scan-only); each process gets its own copy
# --p2              a checkout of the spellbench protocol-v2 branch (its python/ is the reference stack)
# --work            scratch directory (wiped)
# --catalog-games   games over the two catalog decks, both seatings and both starting seats (default 240)
# --facedown-games  games over tests/x3/decks (disguise, manifest dread, cloak, foretell; default 120)
# --shards          engine processes in parallel (default 6)
#
# Game g uses game_secret(g) of the Section 16 run secret. A fresh process replays the first 8 games and must
# give the same per-game digests (observations are deterministic).
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
BUILD=""
DB=""
P2=""
WORK=""
CATALOG=240
FACEDOWN=120
SHARDS=6
while [ $# -gt 0 ]; do
  case "$1" in
    --build) BUILD="$2"; shift 2 ;;
    --db) DB="$2"; shift 2 ;;
    --p2) P2="$2"; shift 2 ;;
    --work) WORK="$2"; shift 2 ;;
    --catalog-games) CATALOG="$2"; shift 2 ;;
    --facedown-games) FACEDOWN="$2"; shift 2 ;;
    --shards) SHARDS="$2"; shift 2 ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
[ -n "$BUILD" ] && [ -n "$DB" ] && [ -n "$P2" ] && [ -n "$WORK" ] || { echo "need --build, --db, --p2 and --work" >&2; exit 2; }
native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
PYTHON=python3
"$PYTHON" -c 'import sys' >/dev/null 2>&1 || PYTHON=python
MAIN=mage.player.spellbench.x3.ObservationSoak
CP="$(native "$BUILD/lib")/*"
DECKS=$(native "$HERE/tests/x3/decks")
CATALOG_PAIRS=Standard16-RG:Standard16-UB,Standard16-UB:Standard16-RG
FACEDOWN_PAIRS=BGRoots:Standard-MonoG,Standard-MonoG:BGRoots,X3-FaceDown-UG:BGRoots,BGRoots:X3-FaceDown-UG
rm -rf "$WORK"
mkdir -p "$WORK/out"
WORK=$(cd "$WORK" && pwd)
OUT=$(native "$WORK/out")

# soak <name> <first> <count> <pairs>: one engine process in its own directory with its own card database
soak() {
  local dir="$WORK/$1"
  mkdir -p "$dir"
  cp -R "$DB" "$dir/db"
  (cd "$dir" && java -Xmx1536m -cp "$CP" "$MAIN" --out-dir "${5:-$OUT}" --deck-dir "$DECKS" --first "$2" \
      --count "$3" --pairs "$4" > summary.jsonl 2> engine.log)
  rm -rf "$dir/db"
}

echo "== self-test (Section 6.10 tables)"
java -cp "$CP" "$MAIN" --selftest

echo "== soak: $CATALOG catalog games and $FACEDOWN face-down games in $SHARDS processes"
t0=$(date +%s)
TOTAL=$((CATALOG + FACEDOWN))
PER=$(( (TOTAL + SHARDS - 1) / SHARDS ))
for s in $(seq 0 $((SHARDS - 1))); do
  (
    lo=$((s * PER)); hi=$(( (s + 1) * PER )); [ $hi -gt $TOTAL ] && hi=$TOTAL
    # a shard may straddle the catalog and face-down ranges: one process per range
    if [ $lo -lt $CATALOG ]; then
      chi=$(( hi < CATALOG ? hi : CATALOG ))
      [ $chi -gt $lo ] && soak "shard$s-c" $lo $((chi - lo)) "$CATALOG_PAIRS"
    fi
    if [ $hi -gt $CATALOG ]; then
      flo=$(( lo > CATALOG ? lo : CATALOG ))
      [ $hi -gt $flo ] && soak "shard$s-f" $flo $((hi - flo)) "$FACEDOWN_PAIRS"
    fi
  ) &
done
wait
echo "soak wall time: $(( $(date +%s) - t0 )) s"
cat "$WORK"/shard*/summary.jsonl > "$WORK/summary.jsonl"

echo "== determinism: a fresh process replays games 0 to 7"
mkdir -p "$WORK/rerun-out"
soak rerun 0 8 "$CATALOG_PAIRS" "$(native "$WORK/rerun-out")"
"$PYTHON" - "$WORK/summary.jsonl" "$WORK/rerun/summary.jsonl" <<'EOF'
import json, sys
first = {r["game"]: r["digest"] for r in map(json.loads, open(sys.argv[1]))}
again = [json.loads(l) for l in open(sys.argv[2])]
same = sum(first.get(r["game"]) == r["digest"] for r in again)
print(f"rerun digests equal: {same} of {len(again)}")
sys.exit(0 if same == len(again) == 8 else 1)
EOF
rm -rf "$WORK/rerun-out"

echo "== games"
"$PYTHON" - "$WORK/summary.jsonl" <<'EOF'
import collections, json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
by = collections.Counter((r["decks"], r["terminal"]) for r in rows)
for (decks, terminal), n in sorted(by.items()):
    print(f"{decks:36s} {terminal:12s} {n}")
print(f"games {len(rows)}, prompts {sum(r['decisions'] for r in rows)}, face-down sightings "
      f"{sum(r['face_down_sightings'] for r in rows)}, looks {sum(r['looks'] for r in rows)}")
EOF

echo "== check (reference validator V1, V2, V4 to V9, and invariants I1 to I6)"
status=0
PYTHONPATH="$(native "$P2/python")" "$PYTHON" "$HERE/tests/x3/check_observations.py" "$WORK/out"     --json "$WORK/check.json" > "$WORK/check.txt" || status=$?
cat "$WORK/check.txt"
echo "X3 verdict: $([ $status = 0 ] && echo PASS || echo FAIL)"
exit $status
