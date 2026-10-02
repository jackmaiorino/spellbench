#!/usr/bin/env bash
# X5m: the first rated fdn-mirror-v0 run, through P's guarded benchmark launcher (spellbench bench, default branch).
#
#   run_rated.sh prepare  [--rehearse]           private: build, checks, optional unrated rehearsal; ends at STOP
#   run_rated.sh commit   --approved TEXT        PUBLIC: push the run's commitment (spellbench bench commit)
#   run_rated.sh play     --run NAME --proof URL private until published: play the committed run (guard, pins)
#   run_rated.sh publish  --run NAME --approved TEXT  PUBLIC: push runs/NAME (results, revealed secret; site deploys)
#
# Nothing public happens without --approved, whose text (who confirmed, when) goes into the log. The third-party
# timestamp between commit and play is a manual public step (README). Environment, all required:
#   SB_REPO        a clean work tree of jackmaiorino/spellbench at origin's default branch tip, holding
#                  benchmarks/fdn-mirror-v0 (bench commit refuses anything else)
#   SB_SCRATCH     engine build, card database and engine work directories (an SSD, never E: for scratch)
#   XMAGE_REPO     a clone of XMage holding the pinned commit; M2: a Maven repository
#   SPELLBENCH_PIN_ROOT, SPELLBENCH_ARTIFACT_REGISTER, SPELLBENCH_SECRETS_DIR   P's rated-run values (bench commit
#                  checks them before publishing anything); the secrets directory must lie outside every git tree
#   PLACEMENT      the COMPUTE-POLICY placement note: 'main-pc=...; haleyspc=...; runpod=...'
set -euo pipefail
STAGE="${1:-}"; shift || true
APPROVED=""; RUN=""; PROOF=""; REHEARSE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --approved) APPROVED="$2"; shift 2 ;;
    --run) RUN="$2"; shift 2 ;;
    --proof) PROOF="$2"; shift 2 ;;
    --rehearse) REHEARSE=1; shift ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
: "${SB_REPO:?}" "${SB_SCRATCH:?}"
BENCH="$SB_REPO/benchmarks/fdn-mirror-v0"
LOG="$SB_SCRATCH/x5m-run.log"
mkdir -p "$SB_SCRATCH/work"
if [ -r /proc/$$/winpid ]; then
  powershell -NoProfile -Command "(Get-Process -Id $(cat /proc/$$/winpid)).PriorityClass = 'BelowNormal'" \
    >/dev/null 2>&1 || true
else
  renice -n 10 $$ >/dev/null 2>&1 || true
fi
native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] $*" | tee -a "$LOG"; }
export PYTHONPATH="$(native "$SB_REPO/python")"
SPELLBENCH=(python -m spellbench.arena.cli)
# the definition's placeholders (benchmarks/local.json may hold them instead; the environment wins)
export XMAGE_BASH="${XMAGE_BASH:-$(native "$(command -v bash)")}"
export XMAGE_ENGINE_SH="$(native "$SB_REPO/engines/xmage/scripts/engine.sh")"
export XMAGE_BUILD="$(native "$SB_SCRATCH/build")" XMAGE_DB="$(native "$SB_SCRATCH/db")"
export XMAGE_WORK="$(native "$SB_SCRATCH/work")"

clean_default_tip() {
  git -C "$SB_REPO" fetch -q origin
  local branch tip head
  branch=$(git -C "$SB_REPO" symbolic-ref --short refs/remotes/origin/HEAD | sed 's#^origin/##')
  tip=$(git -C "$SB_REPO" rev-parse "origin/$branch"); head=$(git -C "$SB_REPO" rev-parse HEAD)
  [ "$tip" = "$head" ] || { log "HEAD $head is not origin/$branch $tip"; exit 1; }
  [ -z "$(git -C "$SB_REPO" status --porcelain --untracked-files=no)" ] || { log "tracked files changed"; exit 1; }
}

case "$STAGE" in
prepare)
  log "prepare (private): checks, build, decks, guard dry run"
  clean_default_tip
  python -c "
from pathlib import Path; from spellbench.bench import definition
from spellbench.arena.config import TournamentConfig; from spellbench.arena.schedule import schedule
from spellbench.run_secret import RunSecret
b = definition.load_benchmark(Path(r'$(native "$BENCH")'))
c = TournamentConfig.from_json(b.tournament_config('runs/check'))
print('definition ok:', b.id, len(schedule(c, RunSecret.generate())), 'games')" | tee -a "$LOG"
  for v in SPELLBENCH_PIN_ROOT SPELLBENCH_ARTIFACT_REGISTER SPELLBENCH_SECRETS_DIR PLACEMENT; do
    [ -n "${!v:-}" ] || { log "missing $v"; exit 1; }
  done
  [ -f "$SPELLBENCH_ARTIFACT_REGISTER" ] || { log "no artifact register script"; exit 1; }
  if [ ! -f "$SB_SCRATCH/build/BUILD-MANIFEST.json" ]; then
    bash "$SB_REPO/engines/xmage/scripts/build.sh" --out "$SB_SCRATCH/build" --xmage-repo "$XMAGE_REPO" \
      --m2 "${M2:-$HOME/.m2/repository}" > "$SB_SCRATCH/build.log" 2>&1
    rm -rf "$SB_SCRATCH/build/src"
  fi
  log "$(grep -E '"(rules_snapshot_id|card_pool_identity|lib_digest)"' "$SB_SCRATCH/build/BUILD-MANIFEST.json" | tr -d ' \n')"
  if [ ! -d "$SB_SCRATCH/db" ]; then
    mkdir -p "$SB_SCRATCH/dbscan"
    (cd "$SB_SCRATCH/dbscan" && java -Xmx2g -cp "$XMAGE_BUILD/lib/*" mage.player.spellbench.x1.DeterminismCheck \
      --scan-only > scan.log 2>&1)
    mv "$SB_SCRATCH/dbscan/db" "$SB_SCRATCH/db"
  fi
  ENGINE=("$XMAGE_BASH" "$XMAGE_ENGINE_SH" --build "$XMAGE_BUILD" --db "$XMAGE_DB" --work "$XMAGE_WORK")
  python "$SB_REPO/engines/xmage/tests/x5/validate_decks.py" --expect-catalog -- "${ENGINE[@]}" \
    > "$SB_SCRATCH/validate-decks.json" && log "validate_deck: all catalog decks deck_ok, no probe declared"
  if [ "$REHEARSE" = 1 ]; then
    # an unrated run of the same definition in a private copy outside the repository: the guard, the runner and
    # the validator end to end under a throwaway secret; nothing of it is ever published
    R="$SB_SCRATCH/rehearsal/benchmarks"; rm -rf "$R"; mkdir -p "$R"; cp -R "$BENCH" "$R/"
    log "rehearsal: unrated run in $R (private)"
    "${SPELLBENCH[@]}" bench run "$(native "$R/fdn-mirror-v0")" --unrated --placement "$PLACEMENT" | tee -a "$LOG"
  fi
  rm -rf "$SB_SCRATCH/work"/xmage-engine-*
  log "=================================================================================="
  log "STOP. Everything above was private. The next steps are PUBLIC and need Jack's confirmation:"
  log "  1. run_rated.sh commit --approved '<who, when>'   pushes COMMITMENT.json to origin/main"
  log "     (the push also redeploys the site); 2. a third-party timestamp of that commit (README);"
  log "  3. run_rated.sh play --run NAME --proof URL (private until 4); 4. run_rated.sh publish --run NAME"
  log "     --approved '<who, when>' pushes the results and the revealed secret; the site redeploys."
  log "=================================================================================="
  ;;
commit)
  [ -n "$APPROVED" ] || { echo "commit is PUBLIC: pass --approved '<who confirmed, when>'" >&2; exit 2; }
  clean_default_tip
  log "PUBLIC step 1 approved by: $APPROVED"
  "${SPELLBENCH[@]}" bench commit "$(native "$BENCH")" --placement "$PLACEMENT" | tee -a "$LOG"
  log "next (PUBLIC step 2): record a third-party timestamp of the commitment commit (README), then play"
  ;;
play)
  [ -n "$RUN" ] && [ -n "$PROOF" ] || { echo "play needs --run NAME --proof URL" >&2; exit 2; }
  log "play (results stay local until publish): run $RUN, proof $PROOF"
  "${SPELLBENCH[@]}" bench run "$(native "$BENCH")" --run "$RUN" --proof "$PROOF" | tee -a "$LOG"
  rm -rf "$SB_SCRATCH/work"/xmage-engine-*
  "${SPELLBENCH[@]}" validate "$(native "$BENCH/runs/$RUN")" | tee -a "$LOG"
  "${SPELLBENCH[@]}" leaderboard "$(native "$BENCH/runs/$RUN")" | tee -a "$LOG"
  log "STOP. The run directory is local. Publishing it is PUBLIC step 3 (run_rated.sh publish)."
  log "Spec 11.6: every committed run must be published, also an aborted or invalid one."
  ;;
publish)
  [ -n "$APPROVED" ] && [ -n "$RUN" ] || { echo "publish is PUBLIC: pass --run NAME --approved TEXT" >&2; exit 2; }
  "${SPELLBENCH[@]}" validate "$(native "$BENCH/runs/$RUN")"
  python -m spellbench.arena.cli site "$(native "$SB_REPO/benchmarks")" "$(native "$SB_SCRATCH/site-check")"
  log "PUBLIC step 3 approved by: $APPROVED"
  git -C "$SB_REPO" add "benchmarks/fdn-mirror-v0/runs/$RUN"
  git -C "$SB_REPO" commit -q -m "fdn-mirror-v0: run $RUN"
  git -C "$SB_REPO" push -q origin HEAD:main
  log "pushed; the Pages workflow validates every latest run and deploys the site"
  ;;
*)
  sed -n 2,20p "$0"; exit 2 ;;
esac
