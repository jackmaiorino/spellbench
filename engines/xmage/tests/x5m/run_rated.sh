#!/usr/bin/env bash
# X5m: the first rated fdn-mirror-v0 run, through P's guarded benchmark launcher (spellbench bench, on main).
#
#   run_rated.sh prepare  [--rehearse]                private: engine, checks, optional unrated rehearsal; ends at STOP
#   run_rated.sh commit   --approved TEXT             PUBLIC: push the run's commitment (spellbench bench commit)
#   run_rated.sh play     --run NAME --proof URL      private until published: play the committed run (guard, pins)
#   run_rated.sh publish  --run NAME --approved TEXT  PUBLIC: push runs/NAME (results, revealed secret; site deploys)
#
# Nothing public happens without --approved, whose text (who confirmed, when) goes into the log. The third-party
# timestamp between commit and play is a manual public step (README). Environment:
#   SB_REPO        a clean work tree of jackmaiorino/spellbench at the tip of origin/main, holding
#                  benchmarks/fdn-mirror-v0 (bench commit refuses anything else)
#   SB_SCRATCH     card database and engine work directories (an SSD; never E: for scratch)
#   XMAGE_BUILD    the pinned engine build (CI artifact of 004913a); if absent, built here from that exact commit
#   XMAGE_DB_SOURCE  a directory holding the reviewed card database (copied to SB_SCRATCH/db, checked by hash)
#                  (XMAGE_REPO: an XMage clone holding the pinned commit; M2: a Maven repository)
#   SPELLBENCH_PIN_ROOT, SPELLBENCH_ARTIFACT_REGISTER, SPELLBENCH_SECRETS_DIR   P's rated-run values (bench commit
#                  checks them before publishing anything); the secrets directory must lie outside every git tree
#   PLACEMENT      the COMPUTE-POLICY placement note: 'main-pc=...; computehost=...; runpod=...'
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

# The definition's placeholders (benchmarks/local.json may hold them instead; the environment wins). The engine is
# main's verified entry: every jar is checked against the pinned build manifest before Java starts.
MANIFEST_SHA256=3b54f3f66cbb135b55dcc19cac5d310447ca78017d1309db05a4d530030c9d93   # build of 004913a, lib 094733a7
ENGINE_SOURCE_REV="${ENGINE_SOURCE_REV:-004913a4fd8e2455f8dfcbcd73a15c568a56bcc2}"
export PYTHON="${PYTHON:-$(native "$(command -v python)")}"
export JAVA="${JAVA:-$(native "$(command -v java)")}"
export XMAGE_VERIFIED_ENTRY="$(native "$SB_REPO/python/tools/xmage_verified_entry.py")"
export XMAGE_BUILD="${XMAGE_BUILD:-$(native "$SB_SCRATCH/build")}"
export XMAGE_BUILD_MANIFEST="$(native "$XMAGE_BUILD/BUILD-MANIFEST.json")"
export XMAGE_DB="$(native "$SB_SCRATCH/db")" XMAGE_ENGINE_WORK="$(native "$SB_SCRATCH/work")"
# the reviewed card database (the same files and hashes as standard-mirror-xmage); a fresh scan differs byte-wise
DB_MV_SHA256=fcdba7e7e5a0875d70380d8d99a5e776fe1eead630ef2a4d6c3340f9378919e3
DB_TRACE_SHA256=ba9c75cd574d96b18e2689ede6d4d90fff7b2a15fcefa0d23d5b4fc4b835f458
ENGINE=("$PYTHON" "$XMAGE_VERIFIED_ENTRY" --java "$JAVA" --build "$XMAGE_BUILD" --db "$XMAGE_DB"
        --db-file "$XMAGE_DB/cards.h2.mv.db" "$DB_MV_SHA256" --db-file "$XMAGE_DB/cards.h2.trace.db" "$DB_TRACE_SHA256"
        --work "$XMAGE_ENGINE_WORK" --manifest "$XMAGE_BUILD_MANIFEST" --manifest-sha256 "$MANIFEST_SHA256")

check_manifest() {
  local got
  got=$(sha256sum "$XMAGE_BUILD/BUILD-MANIFEST.json" | cut -c1-64)
  [ "$got" = "$MANIFEST_SHA256" ] || { log "build manifest $got is not the pinned $MANIFEST_SHA256"; exit 1; }
}

check_db() {
  [ "$(sha256sum "$XMAGE_DB/cards.h2.mv.db" | cut -c1-64)" = "$DB_MV_SHA256" ]     && [ "$(sha256sum "$XMAGE_DB/cards.h2.trace.db" | cut -c1-64)" = "$DB_TRACE_SHA256" ]     || { log "the card database in $XMAGE_DB is not the pinned one"; exit 1; }
}

clean_default_tip() {
  git -C "$SB_REPO" fetch -q origin
  local tip head
  tip=$(git -C "$SB_REPO" rev-parse origin/main); head=$(git -C "$SB_REPO" rev-parse HEAD)
  [ "$tip" = "$head" ] || { log "HEAD $head is not origin/main $tip"; exit 1; }
  [ -z "$(git -C "$SB_REPO" status --porcelain --untracked-files=no)" ] || { log "tracked files changed"; exit 1; }
}

case "$STAGE" in
prepare)
  log "prepare (private): checks, engine, decks, optional rehearsal"
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
  if [ ! -f "$XMAGE_BUILD/BUILD-MANIFEST.json" ]; then
    # a build of the exact source revision: its commit is in the manifest and in hello.source_revision, so a build
    # of any other commit cannot match the pin
    : "${XMAGE_REPO:?an XMage clone is needed to build the engine}"
    git -C "$SB_REPO" worktree add -q --detach "$SB_SCRATCH/engine-wt" "$ENGINE_SOURCE_REV"
    bash "$SB_SCRATCH/engine-wt/engines/xmage/scripts/build.sh" --out "$XMAGE_BUILD" --xmage-repo "$XMAGE_REPO" \
      --m2 "${M2:-$HOME/.m2/repository}" > "$SB_SCRATCH/build.log" 2>&1
    git -C "$SB_REPO" worktree remove --force "$SB_SCRATCH/engine-wt"
    rm -rf "$XMAGE_BUILD/src"
  fi
  check_manifest
  log "$(grep -E '"(rules_snapshot_id|card_pool_identity|lib_digest|spellbench_source_revision)"' \
    "$XMAGE_BUILD/BUILD-MANIFEST.json" | tr -d ' \n')"
  if [ ! -d "$SB_SCRATCH/db" ]; then
    : "${XMAGE_DB_SOURCE:?a directory holding the reviewed card database (cards.h2.mv.db, cards.h2.trace.db)}"
    mkdir -p "$SB_SCRATCH/db" && cp "$XMAGE_DB_SOURCE/cards.h2.mv.db" "$XMAGE_DB_SOURCE/cards.h2.trace.db" "$SB_SCRATCH/db/"
  fi
  check_db
  python "$SB_REPO/engines/xmage/tests/x5/validate_decks.py" --expect-catalog -- "${ENGINE[@]}" \
    > "$SB_SCRATCH/validate-decks.json" && log "validate_deck: all catalog decks deck_ok, no probe declared"
  if [ "$REHEARSE" = 1 ]; then
    # an unrated run of the same definition in a private copy outside the repository: the guard, the runner and
    # the validator end to end under a throwaway secret; nothing of it is ever published
    R="$SB_SCRATCH/rehearsal/benchmarks"; rm -rf "$R"; mkdir -p "$R"; cp -R "$BENCH" "$R/"
    log "rehearsal: unrated run in $R (private)"
    "${SPELLBENCH[@]}" bench run "$(native "$R/fdn-mirror-v0")" --unrated --placement "$PLACEMENT" | tee -a "$LOG"
  fi
  rm -rf "$SB_SCRATCH/work"/*
  log "=================================================================================="
  log "STOP. Everything above was private. The next steps are PUBLIC and need the maintainer's confirmation:"
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
  check_manifest
  check_db
  log "play (results stay local until publish): run $RUN, proof $PROOF"
  "${SPELLBENCH[@]}" bench run "$(native "$BENCH")" --run "$RUN" --proof "$PROOF" | tee -a "$LOG"
  rm -rf "$SB_SCRATCH/work"/*
  "${SPELLBENCH[@]}" validate "$(native "$BENCH/runs/$RUN")" | tee -a "$LOG"
  "${SPELLBENCH[@]}" leaderboard "$(native "$BENCH/runs/$RUN")" | tee -a "$LOG"
  log "STOP. The run directory is local. Publishing it is PUBLIC step 3 (run_rated.sh publish)."
  log "Spec 11.6: every committed run must be published, also an aborted or invalid one."
  ;;
publish)
  [ -n "$APPROVED" ] && [ -n "$RUN" ] || { echo "publish is PUBLIC: pass --run NAME --approved TEXT" >&2; exit 2; }
  "${SPELLBENCH[@]}" validate "$(native "$BENCH/runs/$RUN")"
  "${SPELLBENCH[@]}" site "$(native "$SB_REPO/benchmarks")" "$(native "$SB_SCRATCH/site-check")"
  log "PUBLIC step 3 approved by: $APPROVED"
  git -C "$SB_REPO" add "benchmarks/fdn-mirror-v0/runs/$RUN"
  git -C "$SB_REPO" commit -q -m "fdn-mirror-v0: run $RUN"
  git -C "$SB_REPO" push -q origin HEAD:main
  log "pushed; the Pages workflow validates every latest run and deploys the site"
  ;;
*)
  sed -n 2,20p "$0"; exit 2 ;;
esac
