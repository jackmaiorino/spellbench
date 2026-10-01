#!/usr/bin/env bash
# Task X4 stage 1 evidence: P's conformance runner, the first-vs-uniform soak through P's host with the live
# validator, a rerun of the same schedule for cross-process determinism, a single-game replay (same process and a
# second process), the caps check, and coverage soaks (uniform against itself, heuristic against uniform, the X3
# face-down decks).
#
#   tests/x4/run-evidence.sh --build DIR --db DIR --p2 DIR --work DIR [--games N] [--shards K]
#
# --build   output of scripts/build.sh (patched)
# --db      card database template (each engine process copies it)
# --p2      checkout of the spellbench protocol-v2 branch (P's host, validator and builtins)
# --work    scratch directory (wiped); results land in WORK/out
set -euo pipefail

HERE=$(cd "$(dirname "$0")/../.." && pwd)
BUILD=""; DB=""; P2=""; WORK=""; GAMES=200; SHARDS=12
while [ $# -gt 0 ]; do
  case "$1" in
    --build) BUILD="$2"; shift 2 ;;
    --db) DB="$2"; shift 2 ;;
    --p2) P2="$2"; shift 2 ;;
    --work) WORK="$2"; shift 2 ;;
    --games) GAMES="$2"; shift 2 ;;
    --shards) SHARDS="$2"; shift 2 ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
[ -n "$BUILD" ] && [ -n "$DB" ] && [ -n "$P2" ] && [ -n "$WORK" ] || { echo "need --build, --db, --p2 and --work" >&2; exit 2; }
native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
PYTHON=python3
"$PYTHON" -c 'import sys' >/dev/null 2>&1 || PYTHON=python
BASH_EXE=$(native "$(command -v bash)")
[ -x "/c/Program Files/Git/bin/bash.exe" ] && BASH_EXE="C:/Program Files/Git/bin/bash.exe"
rm -rf "$WORK"
mkdir -p "$WORK/out" "$WORK/engines"
WORK=$(cd "$WORK" && pwd)
OUT="$WORK/out"
export PYTHONPATH="$(native "$P2/python")"
ENGINE=("$BASH_EXE" "$(native "$HERE/scripts/engine.sh")" --build "$(native "$BUILD")" --db "$(native "$DB")"
        --work "$(native "$WORK/engines")" --xmx 1536m)
SOAK="$(native "$HERE/tests/x4/soak.py")"
stats() { export SPELLBENCH_XMAGE_STATS="$(native "$OUT/stats-$1.jsonl")"; }

echo "== conformance (20 checks plus 20 games)"
( cd "$P2" && time "$PYTHON" -c "import sys; from spellbench.arena.cli import main; sys.exit(main(sys.argv[1:]))" \
    conformance engine --format standard-2022-25-bo1 --deck Standard16-RG --deck Standard16-UB --games 20 \
    -- "${ENGINE[@]}" ) > "$OUT/conformance.txt" 2>&1 || true
cat "$OUT/conformance.txt"

echo "== soak: $GAMES games, first against uniform, $SHARDS processes"
stats soak
SECRET=$("$PYTHON" -c "import secrets; print(secrets.token_hex(32))")
"$PYTHON" "$SOAK" --games "$GAMES" --shards "$SHARDS" --run-secret "$SECRET" --out "$(native "$OUT/soak.jsonl")" \
    -- "${ENGINE[@]}" > "$OUT/soak-summary.json" 2> "$OUT/soak.log"
cat "$OUT/soak-summary.json"

echo "== rerun of the same schedule in fresh processes, another shard split"
stats rerun
"$PYTHON" "$SOAK" --games "$GAMES" --shards $((SHARDS - 4)) --run-secret "$SECRET" --out "$(native "$OUT/rerun.jsonl")" \
    -- "${ENGINE[@]}" > "$OUT/rerun-summary.json" 2> "$OUT/rerun.log"
"$PYTHON" - "$OUT/soak.jsonl" "$OUT/rerun.jsonl" > "$OUT/determinism.json" <<'EOF'
import json, sys
a = {json.loads(l)["game_index"]: json.loads(l)["game_digest"] for l in open(sys.argv[1])}
b = {json.loads(l)["game_index"]: json.loads(l)["game_digest"] for l in open(sys.argv[2])}
differ = sorted(i for i in a if a[i] != b.get(i))
print(json.dumps({"games": len(a), "equal_digests": len(a) - len(differ), "differ": differ}, indent=1))
EOF
cat "$OUT/determinism.json"

echo "== replay of game 0: twice in one process, twice in a second process"
stats replay
"$PYTHON" "$SOAK" --replay 0 --run-secret "$SECRET" --out "$(native "$OUT/replay.jsonl")" -- "${ENGINE[@]}" \
    > "$OUT/replay.json" 2> "$OUT/replay.log" || true
cat "$OUT/replay.json"

echo "== caps (max_decisions, max_steps)"
"$PYTHON" "$(native "$HERE/tests/x4/caps.py")" -- "${ENGINE[@]}" > "$OUT/caps.json" 2> "$OUT/caps.log" || true
tail -1 "$OUT/caps.json"

echo "== coverage soaks"
stats uniform
"$PYTHON" "$SOAK" --games 100 --shards "$SHARDS" --bots uniform --out "$(native "$OUT/uniform.jsonl")" \
    -- "${ENGINE[@]}" > "$OUT/uniform-summary.json" 2> "$OUT/uniform.log" || true
stats heuristic
"$PYTHON" "$SOAK" --games 100 --shards "$SHARDS" --bots heuristic,uniform --out "$(native "$OUT/heuristic.jsonl")" \
    -- "${ENGINE[@]}" > "$OUT/heuristic-summary.json" 2> "$OUT/heuristic.log" || true
stats facedown
D="$HERE/tests/x3/decks"
"$PYTHON" "$SOAK" --games 60 --shards "$SHARDS" --bots uniform --decklist "$(native "$D/BGRoots.dck")" \
    --decklist "$(native "$D/Standard-MonoG.dck")" --decklist "$(native "$D/X3-FaceDown-UG.dck")" \
    --out "$(native "$OUT/facedown.jsonl")" -- "${ENGINE[@]}" > "$OUT/facedown-summary.json" 2> "$OUT/facedown.log" || true
for s in uniform heuristic facedown; do echo "-- $s"; cat "$OUT/$s-summary.json"; done
echo "== done: $OUT"
