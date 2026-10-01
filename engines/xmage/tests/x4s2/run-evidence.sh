#!/usr/bin/env bash
# Task X4 stage 2 evidence (issues #18 X4b, #19 X4c, #20 X4d, #22 X4h), in sections a shared machine can run one at
# a time (each well under 90 minutes):
#
#   tests/x4s2/run-evidence.sh --build DIR --db DIR --p2 DIR --work DIR --section NAME [--shards K]
#
# Sections (results land in WORK/out-NAME, wiped first):
#   audit      X4c: the callback audit (CallbackAudit) and the fixtures (Chandra, Flameshaper; cascade into an
#              adventure card)
#   goldens    X4b: replays the committed goldens (tests/x4s2/goldens) two ways; GOLDENS_GENERATE=1 regenerates
#              them into WORK first
#   combat     X4d: 2,000 uniform games: the combat decks (menace, must attack, must block, lure, can't block
#              alone, extra blocks), the X3 face-down decks, and heuristic against uniform on the combat decks
#   hash       X4h: 100 uniform games three times with one run secret: as is, then with -XX:hashCode=3 and an
#              identity-hash warm-up, then with -XX:hashCode=4 and another warm-up; every game digest compared
#   regress    P's conformance runner (20 games) and the 200-game first-vs-uniform soak, live-validated
set -euo pipefail

HERE=$(cd "$(dirname "$0")/../.." && pwd)
BUILD=""; DB=""; P2=""; WORK=""; SECTION=""; SHARDS=12
while [ $# -gt 0 ]; do
  case "$1" in
    --build) BUILD="$2"; shift 2 ;;
    --db) DB="$2"; shift 2 ;;
    --p2) P2="$2"; shift 2 ;;
    --work) WORK="$2"; shift 2 ;;
    --section) SECTION="$2"; shift 2 ;;
    --shards) SHARDS="$2"; shift 2 ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
[ -n "$BUILD" ] && [ -n "$DB" ] && [ -n "$P2" ] && [ -n "$WORK" ] && [ -n "$SECTION" ] \
  || { echo "need --build, --db, --p2, --work and --section" >&2; exit 2; }
native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
# a shared machine: this script and every process it starts run at below-normal priority
if [ -r /proc/$$/winpid ] && command -v powershell >/dev/null 2>&1; then
  powershell -NoProfile -Command "(Get-Process -Id $(cat /proc/$$/winpid)).PriorityClass = 'BelowNormal'" \
    >/dev/null 2>&1 || true
else
  renice -n 10 $$ >/dev/null 2>&1 || true
fi
PYTHON=python3
"$PYTHON" -c 'import sys' >/dev/null 2>&1 || PYTHON=python
BASH_EXE=$(native "$(command -v bash)")
[ -x "/c/Program Files/Git/bin/bash.exe" ] && BASH_EXE="C:/Program Files/Git/bin/bash.exe"
mkdir -p "$WORK"
WORK=$(cd "$WORK" && pwd)
OUT="$WORK/out-$SECTION"
rm -rf "$OUT" "$WORK/engines"
mkdir -p "$OUT" "$WORK/engines"
export PYTHONPATH="$(native "$P2/python");$(native "$HERE/tests/x4");$(native "$HERE/tests/x4s2")"
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) ;; *) PYTHONPATH=$(printf '%s' "$PYTHONPATH" | tr ';' ':') ;; esac
ENGINE=("$BASH_EXE" "$(native "$HERE/scripts/engine.sh")" --build "$(native "$BUILD")" --db "$(native "$DB")"
        --work "$(native "$WORK/engines")" --xmx 1536m)
SOAK="$(native "$HERE/tests/x4/soak.py")"
AGG="$(native "$HERE/tests/x4/agg.py")"
stats() { mkdir -p "$OUT/stats-$1"; export SPELLBENCH_XMAGE_STATS="$(native "$OUT/stats-$1")"; }
counters() { "$PYTHON" "$AGG" "$(native "$OUT/stats-$1")" --json "$(native "$OUT/counters-$1.json")" > /dev/null; }
D3="$HERE/tests/x3/decks"
D4="$HERE/tests/x4s2/decks"
COMBAT=(--decklist "$(native "$D4/X4d-Menace-R.dck")" --decklist "$(native "$D4/X4d-Lure-G.dck")"
        --decklist "$(native "$D4/X4d-Raptor-RW.dck")")
FACEDOWN=(--decklist "$(native "$D3/BGRoots.dck")" --decklist "$(native "$D3/Standard-MonoG.dck")"
          --decklist "$(native "$D3/X3-FaceDown-UG.dck")")

# compare A B...: the game digests of runs of one schedule, game by game (spec 11.8)
compare() {
  "$PYTHON" - "$@" <<'EOF'
import json, sys
runs = [{json.loads(l)["game_index"]: json.loads(l)["game_digest"] for l in open(p)} for p in sys.argv[1:]]
base = runs[0]
differ = sorted(i for i in base if any(r.get(i) != base[i] for r in runs[1:]))
print(json.dumps({"runs": len(runs), "games": len(base), "equal_digests": len(base) - len(differ),
                  "differ": differ}, indent=1))
EOF
}

case "$SECTION" in
audit)
  echo "== X4c callback audit"
  java -cp "$(native "$BUILD/lib")/*" mage.player.spellbench.decide.CallbackAudit > "$OUT/callback-audit.txt" \
    2> "$OUT/callback-audit.log" || true
  tail -3 "$OUT/callback-audit.txt"
  echo "== X4c fixtures"
  stats fixtures
  "$PYTHON" "$(native "$HERE/tests/x4s2/fixtures.py")" --games 12 -- "${ENGINE[@]}" > "$OUT/fixtures.jsonl" \
    2> "$OUT/fixtures.log" || true
  grep '"verdict"' "$OUT/fixtures.jsonl" || true
  counters fixtures
  ;;
goldens)
  DIR="$HERE/tests/x4s2/goldens"
  if [ "${GOLDENS_GENERATE:-0}" = 1 ]; then
    echo "== X4b generate"
    DIR="$WORK/goldens"
    rm -rf "$DIR"
    "$PYTHON" "$(native "$HERE/tests/x4s2/goldens.py")" generate --out "$(native "$DIR")" -- "${ENGINE[@]}" \
      > "$OUT/generate.txt" 2> "$OUT/generate.log" || true
    cat "$OUT/generate.txt"
  fi
  echo "== X4b check"
  "$PYTHON" "$(native "$HERE/tests/x4s2/goldens.py")" check --dir "$(native "$DIR")" -- "${ENGINE[@]}" \
    > "$OUT/goldens-check.txt" 2> "$OUT/goldens-check.log" || true
  cat "$OUT/goldens-check.txt"
  ;;
combat)
  echo "== X4d: 1,000 uniform games on the combat decks"
  stats combat
  "$PYTHON" "$SOAK" --games 1000 --shards "$SHARDS" --bots uniform "${COMBAT[@]}" --out "$(native "$OUT/combat.jsonl")" \
    -- "${ENGINE[@]}" > "$OUT/combat-summary.json" 2> "$OUT/combat.log" || true
  counters combat
  echo "== X4d: 600 uniform games on the X3 face-down decks"
  stats facedown
  "$PYTHON" "$SOAK" --games 600 --shards "$SHARDS" --bots uniform "${FACEDOWN[@]}" \
    --out "$(native "$OUT/facedown.jsonl")" -- "${ENGINE[@]}" > "$OUT/facedown-summary.json" 2> "$OUT/facedown.log" || true
  counters facedown
  echo "== X4d: 400 games heuristic against uniform on the combat decks"
  stats heuristic
  "$PYTHON" "$SOAK" --games 400 --shards "$SHARDS" --bots heuristic,uniform "${COMBAT[@]}" \
    --out "$(native "$OUT/heuristic.jsonl")" -- "${ENGINE[@]}" > "$OUT/heuristic-summary.json" \
    2> "$OUT/heuristic.log" || true
  counters heuristic
  for s in combat facedown heuristic; do echo "-- $s"; cat "$OUT/$s-summary.json"; done
  ;;
hash)
  SECRET=$("$PYTHON" -c "import secrets; print(secrets.token_hex(32))")
  run() {
    local name="$1"; shift
    stats "$name"
    env JAVA_TOOL_OPTIONS="$*" "$PYTHON" "$SOAK" --games 100 --shards "$SHARDS" --bots uniform \
      --deck Standard16-RG --deck Standard16-UB "${COMBAT[@]}" --run-secret "$SECRET" \
      --out "$(native "$OUT/$name.jsonl")" -- "${ENGINE[@]}" > "$OUT/$name-summary.json" 2> "$OUT/$name.log" || true
    counters "$name"
  }
  echo "== X4h: as is"
  run base ""
  echo "== X4h: -XX:hashCode=3, warm-up 7919"
  run seq "-XX:+UnlockExperimentalVMOptions -XX:hashCode=3 -Dspellbench.hashWarmup=7919"
  echo "== X4h: -XX:hashCode=4, warm-up 104729"
  run addr "-XX:+UnlockExperimentalVMOptions -XX:hashCode=4 -Dspellbench.hashWarmup=104729"
  compare "$(native "$OUT/base.jsonl")" "$(native "$OUT/seq.jsonl")" "$(native "$OUT/addr.jsonl")" \
    > "$OUT/hash-determinism.json"
  cat "$OUT/hash-determinism.json"
  ;;
regress)
  echo "== conformance (20 checks plus 20 games)"
  ( cd "$P2" && "$PYTHON" -c "import sys; from spellbench.arena.cli import main; sys.exit(main(sys.argv[1:]))" \
      conformance engine --format standard-2022-25-bo1 --deck Standard16-RG --deck Standard16-UB --games 20 \
      -- "${ENGINE[@]}" ) > "$OUT/conformance.txt" 2>&1 || true
  cat "$OUT/conformance.txt"
  echo "== 200-game soak, first against uniform"
  stats soak
  "$PYTHON" "$SOAK" --games 200 --shards "$SHARDS" --out "$(native "$OUT/soak.jsonl")" -- "${ENGINE[@]}" \
    > "$OUT/soak-summary.json" 2> "$OUT/soak.log" || true
  cat "$OUT/soak-summary.json"
  counters soak
  ;;
*) echo "unknown section $SECTION" >&2; exit 2 ;;
esac
echo "== done: $OUT"
