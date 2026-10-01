#!/usr/bin/env bash
# X5 final run on one machine, through P's guard: build, validate_deck over the catalog, P's scaling comparison
# (qualification.plan_allocation), then the whole 10,112-game schedule with the worker count the guard chose, then
# the summary. Below-normal priority for this script and every process it starts.
#
#   tests/x5/run-final.sh --machine NAME --scratch DIR --xmage-repo PATH --m2 PATH --p2 DIR --cap N --placement TEXT
#
# --scratch  holds build/, db/, work/, qualify/, run/ (engine scratch and outputs; nothing goes into the repo)
# --p2       P's stack at protocol-v2 4b588a1 (its python/ directory is put on PYTHONPATH)
set -euo pipefail

MACHINE="" SCRATCH="" XMAGE_REPO="" M2="" P2="" CAP="" PLACEMENT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --machine) MACHINE="$2"; shift 2 ;;
    --scratch) SCRATCH="$2"; shift 2 ;;
    --xmage-repo) XMAGE_REPO="$2"; shift 2 ;;
    --m2) M2="$2"; shift 2 ;;
    --p2) P2="$2"; shift 2 ;;
    --cap) CAP="$2"; shift 2 ;;
    --placement) PLACEMENT="$2"; shift 2 ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
if [ -r /proc/$$/winpid ]; then
  powershell -NoProfile -Command "(Get-Process -Id $(cat /proc/$$/winpid)).PriorityClass = 'BelowNormal'" \
    >/dev/null 2>&1 || true
else
  renice -n 10 $$ >/dev/null 2>&1 || true
fi
HERE=$(cd "$(dirname "$0")/../.." && pwd)
native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
export PYTHONPATH="$(native "$P2/python")"
mkdir -p "$SCRATCH/work"
stamp() { date '+%Y-%m-%d %H:%M:%S %Z'; }

echo "[$(stamp)] build"
bash "$HERE/scripts/build.sh" --out "$SCRATCH/build" --xmage-repo "$XMAGE_REPO" --m2 "$M2" > "$SCRATCH/build.log" 2>&1
DIGEST=$(grep -o '"lib_digest": "[0-9a-f]*"' "$SCRATCH/build/BUILD-MANIFEST.json" | cut -d'"' -f4)
echo "[$(stamp)] lib_digest $DIGEST"
if [ ! -d "$SCRATCH/db" ]; then
  mkdir -p "$SCRATCH/dbscan"
  (cd "$SCRATCH/dbscan" && java -Xmx2g -cp "$(native "$SCRATCH/build/lib")/*" \
     mage.player.spellbench.x1.DeterminismCheck --scan-only > scan.log 2>&1)
  mv "$SCRATCH/dbscan/db" "$SCRATCH/db"
fi
ENGINE=(bash "$(native "$HERE/scripts/engine.sh")" --build "$(native "$SCRATCH/build")" --db "$(native "$SCRATCH/db")"
        --work "$(native "$SCRATCH/work")")

echo "[$(stamp)] validate_deck over the catalog"
python "$HERE/tests/x5/validate_decks.py" --expect-catalog -- "${ENGINE[@]}" > "$SCRATCH/validate-decks.json"

echo "[$(stamp)] qualification (P's plan_allocation)"
python "$HERE/tests/x5/x5run.py" qualify --plan "$HERE/tests/x5/plan.json" --machine "$MACHINE" --cap "$CAP" \
  --placement "$PLACEMENT" --build-digest "sha256:$DIGEST" --p2-commit 4b588a1 --out "$(native "$SCRATCH/qualify")" \
  -- "${ENGINE[@]}"
WORKERS=$(python -c "import json,sys; print(json.load(open(sys.argv[1]))['workers'])" "$SCRATCH/qualify/allocation.json")

echo "[$(stamp)] run: $WORKERS workers"
python "$HERE/tests/x5/x5run.py" run --plan "$HERE/tests/x5/plan.json" --machine "$MACHINE" --workers "$WORKERS" \
  --fraction 1.0 --part A --out "$(native "$SCRATCH/run")" -- "${ENGINE[@]}"

echo "[$(stamp)] summary"
python "$HERE/tests/x5/x5run.py" summarize --plan "$HERE/tests/x5/plan.json" "$SCRATCH/run/rows-$MACHINE.jsonl" \
  --stats "$SCRATCH/run/stats-$MACHINE" --out "$SCRATCH/run/summary.json"
rm -rf "$SCRATCH/work"/xmage-engine-*
echo "[$(stamp)] done"
