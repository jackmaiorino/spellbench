#!/usr/bin/env bash
# Issue #23's open scope on main's pinned engine (build of 004913a, manifest 3b54f3f6..., lib 094733a7): the
# paired-world leak tests (counterspell, cantrip, randomized, comparator self-tests) and the X4b arrangement
# goldens, regenerated and replayed. Correctness checks, below-normal priority; writes only under --scratch.
#
#   run-23-checks.sh --repo SB_REPO --build BUILD --db DB --scratch DIR [--workers N] [--section leak|goldens|all]
#
# --repo     a work tree of main (its python/ is P's stack; its engines/xmage holds leak.py and goldens.py)
# --build    the pinned engine build; its BUILD-MANIFEST.json must hash to the pin below, or nothing runs
# --db       a card database built with DeterminismCheck --scan-only from that build
# --workers  leak-test worker processes (each holds two engines, one per world); default 8
# Outputs: DIR/leak/ (summaries, pairs, self-tests, audit streams), DIR/goldens/ (regenerated goldens and
# index.json), DIR/goldens-check.txt, DIR/23-checks.log. Copying them into the repository is a separate step.
set -uo pipefail
REPO="" BUILD="" DB="" SCRATCH="" WORKERS=8 SECTION=all
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="$2"; shift 2 ;;
    --build) BUILD="$2"; shift 2 ;;
    --db) DB="$2"; shift 2 ;;
    --scratch) SCRATCH="$2"; shift 2 ;;
    --workers) WORKERS="$2"; shift 2 ;;
    --section) SECTION="$2"; shift 2 ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
[ -n "$REPO" ] && [ -n "$BUILD" ] && [ -n "$DB" ] && [ -n "$SCRATCH" ] || { echo "need --repo --build --db --scratch" >&2; exit 2; }
if [ -r /proc/$$/winpid ]; then
  powershell -NoProfile -Command "(Get-Process -Id $(cat /proc/$$/winpid)).PriorityClass = 'BelowNormal'" \
    >/dev/null 2>&1 || true
else
  renice -n 10 $$ >/dev/null 2>&1 || true
fi
native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
mkdir -p "$SCRATCH/work"
LOG="$SCRATCH/23-checks.log"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $*" | tee -a "$LOG"; }
MANIFEST_SHA256=3b54f3f66cbb135b55dcc19cac5d310447ca78017d1309db05a4d530030c9d93
got=$(sha256sum "$BUILD/BUILD-MANIFEST.json" | cut -c1-64)
[ "$got" = "$MANIFEST_SHA256" ] || { log "build manifest $got is not the pinned $MANIFEST_SHA256"; exit 1; }
X="$REPO/engines/xmage"
SEP=";"; case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) ;; *) SEP=":" ;; esac
export PYTHONPATH="$(native "$REPO/python")$SEP$(native "$X/tests/x4")$SEP$(native "$X/tests/x4s2")"
PY=$(native "$(command -v python)")
# main's entry pins the database files too; these checks take the hashes of the database given
DBF=()
for f in cards.h2.mv.db cards.h2.trace.db; do DBF+=(--db-file "$(native "$DB/$f")" "$(sha256sum "$DB/$f" | cut -c1-64)"); done
ENGINE=("$PY" "$(native "$REPO/python/tools/xmage_verified_entry.py")" --java "$(native "$(command -v java)")"
        --build "$(native "$BUILD")" --db "$(native "$DB")" "${DBF[@]}" --work "$(native "$SCRATCH/work")"
        --manifest "$(native "$BUILD/BUILD-MANIFEST.json")" --manifest-sha256 "$MANIFEST_SHA256")
log "engine: $(grep -E '"(spellbench_source_revision|lib_digest)"' "$BUILD/BUILD-MANIFEST.json" | tr -d ' \n')"
FAIL=0

if [ "$SECTION" = all ] || [ "$SECTION" = leak ]; then
  OUT="$SCRATCH/leak"; rm -rf "$OUT"; mkdir -p "$OUT"
  for spec in "counterspell 50" "cantrip 50" "random 200"; do
    set -- $spec
    log "leak: $1, $2 pairs, $WORKERS workers"
    (cd "$X/tests/x5" && python leak.py --position "$1" --pairs "$2" --workers "$WORKERS" --out "$(native "$OUT")" \
      -- "${ENGINE[@]}") > "$OUT/$1.log" 2>&1 || FAIL=1
    grep -h '"verdict"' "$OUT/$1-summary.json" 2>/dev/null | tee -a "$LOG"
  done
  (cd "$X/tests/x5" && python leak.py --selftest "$(native "$OUT/counterspell-first-pair-streams.json")" p0 \
    > "$(native "$OUT/selftest-counterspell.json")") || FAIL=1
  OBS=$(python -c "import json,sys; r=json.loads(open(sys.argv[1]).readline()); print(next(iter(r['observers'])))" \
    "$OUT/random-pairs.jsonl")
  (cd "$X/tests/x5" && python leak.py --selftest "$(native "$OUT/random-first-pair-streams.json")" "$OBS" \
    > "$(native "$OUT/selftest-random.json")") || FAIL=1
  log "self-tests: $(grep -h '"verdict"' "$OUT"/selftest-*.json | tr -d ' \n')"
  rm -rf "$SCRATCH/work"/*
fi

if [ "$SECTION" = all ] || [ "$SECTION" = goldens ]; then
  G="$SCRATCH/goldens"; rm -rf "$G"
  log "goldens: generate (the five X4b arrangement goldens on this build)"
  python "$(native "$X/tests/x4s2/goldens.py")" generate --out "$(native "$G")" -- "${ENGINE[@]}" \
    > "$SCRATCH/goldens-generate.txt" 2> "$SCRATCH/goldens-generate.log" || FAIL=1
  cat "$SCRATCH/goldens-generate.txt" | tee -a "$LOG"
  log "goldens: replay (P's engine-transcript replay and a whole-game host replay, fresh processes)"
  python "$(native "$X/tests/x4s2/goldens.py")" check --dir "$(native "$G")" -- "${ENGINE[@]}" \
    > "$SCRATCH/goldens-check.txt" 2> "$SCRATCH/goldens-check.log" || FAIL=1
  cat "$SCRATCH/goldens-check.txt" | tee -a "$LOG"
  rm -rf "$SCRATCH/work"/*
fi
log "done, failures: $FAIL"
exit $FAIL
