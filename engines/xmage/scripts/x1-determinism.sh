#!/usr/bin/env bash
# Task X1 evidence: reruns of one scripted two-seat game must give byte-identical transcript digests in one JVM
# and across fresh processes with the patch series, and must not without it (the negative control).
#
#   scripts/x1-determinism.sh --build DIR --stock-build DIR --work DIR
#
# --build        output of scripts/build.sh (patched)
# --stock-build  output of scripts/build.sh --stock
# --work         scratch directory (wiped); each engine process gets its own working directory and card database
#
# Game secrets are the Section 16 test vectors: S = game_secret(0), S2 = game_secret(1).
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
BUILD=""
STOCK=""
WORK=""
while [ $# -gt 0 ]; do
  case "$1" in
    --build) BUILD="$2"; shift 2 ;;
    --stock-build) STOCK="$2"; shift 2 ;;
    --work) WORK="$2"; shift 2 ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
[ -n "$BUILD" ] && [ -n "$STOCK" ] && [ -n "$WORK" ] || { echo "need --build, --stock-build and --work" >&2; exit 2; }
native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
PYTHON=python3
"$PYTHON" -c 'import sys' >/dev/null 2>&1 || PYTHON=python

S=7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e
S2=952ea875cce08bf7706f87a89ae6a4e318a1bc4b46d6b506f8bb8505c518238e
# soak: game_secret(2..5) of the same run secret
SOAK="61d80bc8e83cfbadfcebe7d7333a58adca5855e91a958b50bfb2d0fac8de6736 c887c54935e811a529c7646e4be95be54e3f8ec3acda935d26122ca533657de5 cca9db8b8f0f6f6a9ba99e520702c052eb50fcdf43bb200643787b73d47561b1 17d93aca04922227c07d61db5c203acdc90a889c751f4b8d95d991e2980b5e52"
DECK0=$(native "$HERE/tests/x1/decks/Standard16-RG.dck")
DECK1=$(native "$HERE/tests/x1/decks/Standard16-UB.dck")
MAIN=mage.player.spellbench.x1.DeterminismCheck
rm -rf "$WORK"
mkdir -p "$WORK"
WORK=$(cd "$WORK" && pwd)
RESULTS="$WORK/results.jsonl"
: > "$RESULTS"

# run <build dir> <run name> <game spec>...: one engine process in its own directory with its own card database
run() {
  local build="$1" name="$2"; shift 2
  local dir="$WORK/$name"
  mkdir -p "$dir"
  cp -R "$WORK/db-$(basename "$build")" "$dir/db"
  local args=()
  for g in "$@"; do args+=(--game "$g"); done
  (cd "$dir" && java -Xmx2g -cp "$(native "$build/lib")/*" "$MAIN" --deck0 "$DECK0" --deck1 "$DECK1" \
      --out-dir transcripts "${args[@]}" > summary.jsonl 2> engine.log)
  sed "s/^{/{\"run\":\"$name\",/" "$dir/summary.jsonl" >> "$RESULTS"
}

dbtemplate() {
  local build="$1" dir="$WORK/db-$(basename "$1")-scan"
  mkdir -p "$dir"
  (cd "$dir" && java -Xmx2g -cp "$(native "$build/lib")/*" "$MAIN" --scan-only > scan.log 2>&1)
  mv "$dir/db" "$WORK/db-$(basename "$build")"
}

echo "== self-test (Section 16 vectors)"
java -cp "$(native "$BUILD/lib")/*" "$MAIN" --selftest

echo "== card database templates"
dbtemplate "$BUILD" &
dbtemplate "$STOCK" &
wait

A="$WORK/answers"
mkdir -p "$A"
echo "== patched: record S, then reruns (one JVM: S, S2, S; two fresh processes: S)"
run "$BUILD" patched-record "record:$S:$(native "$A/patched-S.txt")"
run "$BUILD" patched-jvm "replay:$S:$(native "$A/patched-S.txt")" "record:$S2:$(native "$A/patched-S2.txt")" \
    "replay:$S:$(native "$A/patched-S.txt")" &
run "$BUILD" patched-fresh1 "replay:$S:$(native "$A/patched-S.txt")" &
run "$BUILD" patched-fresh2 "replay:$S:$(native "$A/patched-S.txt")" &
wait

echo "== patched soak: four more games recorded in one JVM, replayed in reverse order in another"
REC=()
REP=()
for x in $SOAK; do REC+=("record:$x:$(native "$A/patched-$x.txt")"); REP=("replay:$x:$(native "$A/patched-$x.txt")" "${REP[@]}"); done
run "$BUILD" soak-record "${REC[@]}"
run "$BUILD" soak-replay "${REP[@]}"

echo "== stock (negative control): record S with CABT's seeding, then the same reruns"
run "$STOCK" stock-record "record:$S:$(native "$A/stock-S.txt")"
run "$STOCK" stock-jvm "replay:$S:$(native "$A/stock-S.txt")" "record:$S2:$(native "$A/stock-S2.txt")" \
    "replay:$S:$(native "$A/stock-S.txt")" &
run "$STOCK" stock-fresh1 "replay:$S:$(native "$A/stock-S.txt")" &
run "$STOCK" stock-fresh2 "replay:$S:$(native "$A/stock-S.txt")" &
wait

"$PYTHON" - "$(native "$RESULTS")" <<'EOF'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
print("%-15s %4s %-6s %-8s %5s %-18s %-14s %-14s" % ("run", "game", "mode", "secret", "dec", "terminal", "digest", "content"))
for r in rows:
    print("%-15s %4d %-6s %-8s %5d %-18s %-14s %-14s" % (r["run"], r["game"], r["mode"], r["secret"], r["decisions"],
          r["terminal"], r["digest"][7:19], r["content_digest"][7:19]))
def pick(build):
    return [r for r in rows if r["run"].startswith(build) and r["secret"] == "7648831b"]
verdict = True
for build, expect in (("patched", True), ("stock", False)):
    s = pick(build)
    same = len({r["digest"] for r in s}) == 1
    same_content = len({r["content_digest"] for r in s}) == 1
    print("%s: %d runs of S; digests %s; content digests %s" % (build, len(s), "IDENTICAL" if same else "DIFFER",
          "IDENTICAL" if same_content else "DIFFER"))
    verdict &= (same == expect)
soak = {}
for r in rows:
    if r["run"].startswith("soak"):
        soak.setdefault(r["secret"], []).append(r)
for sec, rs in sorted(soak.items()):
    same = len(rs) == 2 and len({r["digest"] for r in rs}) == 1
    print("soak %s: %s" % (sec, "IDENTICAL" if same else "DIFFER"))
    verdict &= same
print("X1 verdict:", "PASS" if verdict else "FAIL")
sys.exit(0 if verdict else 1)
EOF
