#!/usr/bin/env bash
# A1 change 8 on one machine: plan (once, shared by every machine), qualify, then the guarded soak, R-1 and the
# summary. Prepared 2026-10-01; run only after the coordinator's "qualification go" names the machine.
#
#   qualify/launch.sh STEP     STEP = plan | qualify | run | replay | summarize
#
# Environment (all required; no defaults that could point at another lane's files):
#   KIT      kit build (kit/build.sh output)       ENGINE  engine build (engines/xmage/scripts/build.sh output)
#   DB       card database template                P2      P's checkout (protocol-v2 at the pinned commit)
#   OUT      this machine's run directory (on a volume with the 60 GiB reserve free)
#   MACHINE  main-pc | haleyspc | runpod           PLAN    the shared plan.json
#   CAP      qualify: the top rung's workers       PLACEMENT  qualify: 'main-pc=...: why; haleyspc=...: why; runpod=...: why'
#   FRACTION, PART  run: this machine's share of the order (one machine: 1.0, A)
#   ENTRIES  plan: entries, default "h1 h2" (kit-mcts waits for its own qualification)
#   CLOCK    plan: fdn-mirror-v0 (default; the benchmark's profile) or kit
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
STEP=${1:?step}
: "${KIT:?}" "${ENGINE:?}" "${DB:?}" "${P2:?}" "${OUT:?}" "${PLAN:?}"
if [ -r /proc/$$/winpid ]; then
  powershell -NoProfile -Command "(Get-Process -Id $(cat /proc/$$/winpid)).PriorityClass = 'BelowNormal'" >/dev/null 2>&1 || true
fi
native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
export PYTHONPATH=$(native "$P2/python")
P2_COMMIT=$(git -C "$P2" rev-parse HEAD)
BASH_EXE=$(command -v cygpath >/dev/null 2>&1 && echo "C:/Program Files/Git/bin/bash.exe" || echo bash)
ENGINE_ARGV=("$BASH_EXE" "$(native "$HERE/../../scripts/engine.sh")" --build "$(native "$ENGINE")" --db "$(native "$DB")"
             --work "$(native "$OUT/engines")" --xmx 1536m)
COMMON=(--plan "$(native "$PLAN")" --kit "$(native "$KIT")" --engine-build "$(native "$ENGINE")" --db "$(native "$DB")"
        --p2-commit "$P2_COMMIT" --out "$(native "$OUT")")
mkdir -p "$OUT/engines"
case "$STEP" in
  plan)
    args=(); for e in ${ENTRIES:-h1 h2}; do args+=(--entry "$e"); done
    python "$HERE/kitrun.py" plan "${args[@]}" --kit "$(native "$KIT")" --clock "${CLOCK:-fdn-mirror-v0}" --out "$(native "$PLAN")" ;;
  qualify)
    python "$HERE/kitrun.py" qualify "${COMMON[@]}" --cap "${CAP:?}" --placement "${PLACEMENT:?}" -- "${ENGINE_ARGV[@]}" ;;
  run)
    python "$HERE/kitrun.py" run "${COMMON[@]}" --qualification "$(native "$OUT/QUALIFICATION.json")" \
      --machine "${MACHINE:?}" --fraction "${FRACTION:-1.0}" --part "${PART:-A}" -- "${ENGINE_ARGV[@]}" ;;
  replay)
    python "$HERE/kitrun.py" replay "${COMMON[@]}" --qualification "$(native "$OUT/QUALIFICATION.json")" \
      --rows "$(native "$OUT/rows-${MACHINE:?}.jsonl")" -- "${ENGINE_ARGV[@]}" ;;
  summarize)
    python "$HERE/kitrun.py" summarize --plan "$(native "$PLAN")" --rows "$(native "$OUT/rows-${MACHINE:?}.jsonl")" \
      --kitlogs "$(native "$OUT/kitlogs-$MACHINE")" --isolation "$(native "$OUT/ISOLATION-$MACHINE.json")" \
      --out "$(native "$OUT/SOAK-SUMMARY.json")" ;;
  *) echo "unknown step $STEP" >&2; exit 2 ;;
esac
