#!/usr/bin/env bash
# Review change 5: reproduces the nine H1 decisions of the slice's final game set whose MAD choice had no offered
# candidate, then diagnoses each with the current kit's mapping diagnostics (Slice case UNMAPPED).
#
# The slice code (commit b9bd4f5) replays its games exactly (E5); this script exports that commit's kit, changes one
# line so its decision dumps carry the decision as sent to the runner (with the seat's own history), rebuilds it,
# replays the two games, keeps the nine dumped decisions and runs UNMAPPED on them with the current kit.
#
#   kit/scripts/diagnose-unmapped.sh --repo REPO --engine-build ENGINE --db DB --p2 P2 --kit KIT --work DIR -- ENGINE_ARGV...
#
# KIT is the current kit build (kit/build.sh output). Games: heuristic set index 6 (g-4ce9380fdae33a52, steps 155,
# 161) and uniform set index 3 (g-19525074c1c62f1a, steps 212 214 216 238 315 460 462, round trip on), with the run
# secrets recorded in evidence/games/*/summary.json.
set -euo pipefail
REPO=""; ENGINE=""; DB=""; P2=""; KIT=""; WORK=""
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="$2"; shift 2 ;;
    --engine-build) ENGINE="$2"; shift 2 ;;
    --db) DB="$2"; shift 2 ;;
    --p2) P2="$2"; shift 2 ;;
    --kit) KIT="$2"; shift 2 ;;
    --work) WORK="$2"; shift 2 ;;
    --) shift; break ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
OLD="$WORK/kit-b9bd4f5"
mkdir -p "$OLD" "$WORK/dumps" "$WORK/nine"
git -C "$REPO" archive b9bd4f5 engines/xmage/kit | tar -x -C "$OLD"
F="$OLD/engines/xmage/kit/core/src/spellbench/kit/core/Front.java"
grep -q '"decision", d)));' "$F"
sed -i 's/"decision", d)));/"decision", req.get("decision"))));/' "$F"
bash "$OLD/engines/xmage/kit/build.sh" --engine-build "$ENGINE" --out "$WORK/kit-old-build" > "$WORK/kit-old-build.log"
H=6af65adb4d66eb48dcfcc975070e22fef9bef7e71dfe0ca0abfe8e6bbfde482e
U=0403caec570a8951a2377689e314d92e475954e86d5662d1b9f0b8826e3a67e7
AGENT=(bash "$OLD/engines/xmage/kit/scripts/agent.sh" --kit "$WORK/kit-old-build" --engine-build "$ENGINE" --db "$DB"
       --work "$WORK/agents" --entry h1 --dump "$WORK/dumps")
cmd() { python -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@"; }
PYTHONPATH="$P2/python" python "$OLD/engines/xmage/kit/tests/play.py" --games 8 --index 6 --run-secret "$H" \
  --out "$WORK/replay-heuristic.jsonl" --kit-name kit-mad-k1-s6 --kit-cmd "$(cmd "${AGENT[@]}")" --opponent heuristic -- "$@"
PYTHONPATH="$P2/python" python "$OLD/engines/xmage/kit/tests/play.py" --games 4 --index 3 --run-secret "$U" \
  --out "$WORK/replay-uniform.jsonl" --kit-name kit-mad-k1-s6 --kit-cmd "$(cmd "${AGENT[@]}" --roundtrip 1)" --opponent uniform -- "$@"
for s in 155 161; do cp "$WORK/dumps/decision-g-4ce9380fdae33a52-$s.json" "$WORK/nine/"; done
for s in 212 214 216 238 315 460 462; do cp "$WORK/dumps/decision-g-19525074c1c62f1a-$s.json" "$WORK/nine/"; done
SEP=":"; command -v cygpath >/dev/null 2>&1 && SEP=";"
mkdir -p "$WORK/slice" && cp -R "$DB" "$WORK/slice/db" && cd "$WORK/slice"
java -cp "$KIT/lib/kit-xmage.jar${SEP}$KIT/lib/kit-core.jar${SEP}$ENGINE/lib/*" -Dkit.unmapped.dir="$WORK/nine" \
  spellbench.kit.xmage.Slice "$WORK/unmapped.jsonl" UNMAPPED
