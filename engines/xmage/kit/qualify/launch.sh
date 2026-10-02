#!/usr/bin/env bash
# A1 change 8 on one machine: plan (once, shared by every machine), qualify, then the guarded soak, R-1 and the
# summary, at below-normal priority.
#
#   qualify/launch.sh STEP     STEP = plan | qualify | run | replay | summarize
#
# Environment (all required; no defaults that could point at another lane's files):
#   KIT      kit build (kit/build.sh output)       ENGINE  engine build (with BUILD-MANIFEST.json and lib/)
#   DB       card database template                P2      the repository whose python/ is P's host (main)
#   P2_COMMIT  overrides P2's git revision (a copied python/ tree)
#   ENGINE_MANIFEST_SHA256  the reviewed engine's manifest hash: the engine starts through P's verified entry
#   OUT      this machine's run directory (on a volume with the 60 GiB reserve free)
#   MACHINE  main-pc | haleyspc | runpod           PLAN    the shared plan.json
#   CAP      qualify: the top rung's workers       PLACEMENT  qualify: 'main-pc=...: why; haleyspc=...: why; runpod=...: why'
#   FRACTION, PART  run: this machine's share of the order (one machine: 1.0, A)
#   ENTRIES  plan: entries, default "h1 h2" (kit-mcts waits for its own qualification)
#   CLOCK    plan: kit (default; the profile fdn-mirror-v0 freezes for every entry and builtin)
#   ROWS     replay and summarize: row files (space separated); KITLOGS, ISOLATION likewise for summarize
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
STEP=${1:?step}
: "${KIT:?}" "${ENGINE:?}" "${DB:?}" "${P2:?}" "${OUT:?}" "${PLAN:?}"
if [ -r /proc/$$/winpid ]; then
  powershell -NoProfile -Command "(Get-Process -Id $(cat /proc/$$/winpid)).PriorityClass = 'BelowNormal'" >/dev/null 2>&1 || true
fi
native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
export PYTHONPATH=$(native "$P2/python")
P2_COMMIT=${P2_COMMIT:-$(git -C "$P2" rev-parse HEAD)}
BASH_EXE=$(command -v cygpath >/dev/null 2>&1 && echo "C:/Program Files/Git/bin/bash.exe" || echo bash)
if [ -n "${ENGINE_MANIFEST_SHA256:-}" ]; then
  ENGINE_ARGV=(python "$(native "$P2/python/tools/xmage_verified_entry.py")" --java "$(native "$(command -v java)")"
               --build "$(native "$ENGINE")" --db "$(native "$DB")" --work "$(native "$OUT/engines")"
               --manifest "$(native "$ENGINE/BUILD-MANIFEST.json")" --manifest-sha256 "$ENGINE_MANIFEST_SHA256")
else
  ENGINE_ARGV=("$BASH_EXE" "$(native "$HERE/../../scripts/engine.sh")" --build "$(native "$ENGINE")" --db "$(native "$DB")"
               --work "$(native "$OUT/engines")" --xmx 1536m)
fi
COMMON=(--plan "$(native "$PLAN")" --kit "$(native "$KIT")" --engine-build "$(native "$ENGINE")" --db "$(native "$DB")"
        --p2-commit "$P2_COMMIT" --machine "${MACHINE:?}" --out "$(native "$OUT")")
mkdir -p "$OUT/engines"
case "$STEP" in
  plan)
    args=(); for e in ${ENTRIES:-h1 h2}; do args+=(--entry "$e"); done
    python "$HERE/kitrun.py" plan "${args[@]}" --kit "$(native "$KIT")" --clock "${CLOCK:-kit}" --out "$(native "$PLAN")" ;;
  qualify)
    python "$HERE/kitrun.py" qualify "${COMMON[@]}" --cap "${CAP:?}" --placement "${PLACEMENT:?}" -- "${ENGINE_ARGV[@]}" ;;
  run)
    python "$HERE/kitrun.py" run "${COMMON[@]}" --qualification "$(native "$OUT/QUALIFICATION.json")" \
      --fraction "${FRACTION:-1.0}" --part "${PART:-A}" -- "${ENGINE_ARGV[@]}" ;;
  replay)
    rows=(); for r in ${ROWS:?}; do rows+=(--rows "$(native "$r")"); done
    python "$HERE/kitrun.py" replay "${COMMON[@]}" --qualification "$(native "$OUT/QUALIFICATION.json")" \
      "${rows[@]}" -- "${ENGINE_ARGV[@]}" ;;
  summarize)
    rows=(); for r in ${ROWS:?}; do rows+=(--rows "$(native "$r")"); done
    for k in ${KITLOGS:?}; do rows+=(--kitlogs "$(native "$k")"); done
    for i in ${ISOLATION:?}; do rows+=(--isolation "$(native "$i")"); done
    python "$HERE/kitrun.py" summarize --plan "$(native "$PLAN")" "${rows[@]}" --out "$(native "$OUT/SOAK-SUMMARY.json")" ;;
  *) echo "unknown step $STEP" >&2; exit 2 ;;
esac
