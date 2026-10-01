# XMage engine for Spellbench (sub-project X)

Status: spike through tasks X0 (pin and build) and X1 (determinism and secrets). There is no v2 server yet (X2), no observation builder (X3) and no decision mapping (X4), so this engine cannot serve games to a Spellbench host. Design: `E:/spellbench-archive/program-research/x-design-draft.md` (with the 2026-09-30 gate addendum); research: `x-xmage-brief.md` beside it.

## Pins

| What | Pin |
|---|---|
| XMage | `fd40ad5c29a92cef824cf12ba6d0e4daa25db975` (2026-09-18), https://github.com/magefree/mage |
| CABT | `bc1cf38c75ee3b3922b174bf20bc6e180e1f7a26`, https://github.com/NMaass/mtg-rl-tools, vendored unchanged in `vendor/cabt/` |
| Mage.Sets tree at the XMage pin | `3c333c4538a45690b640b4520b6572c40da80cb9` |
| Jar timestamps | `2026-09-18T22:54:08Z` (the XMage commit time) |

`pins.env` holds the pins `scripts/build.sh` reads.

## Engine identity strings (protocol v2 Section 9.1)

| Field | Scheme | Value at these pins |
|---|---|---|
| `rules_snapshot_id` | `xmage-<XMage commit>-xpat-<sha256 of patches/xmage/*.patch concatenated in name order>` | `xmage-fd40ad5c29a92cef824cf12ba6d0e4daa25db975-xpat-8c2578bef233c7d26ca090613cad5b11e198d21a49b0f67edb964bd782aeec6b` |
| `card_pool_identity` | `xmage-sets-<git tree id of Mage.Sets at the pin>-xpat-<sha256 of the patch sections under Mage.Sets/>` | `xmage-sets-3c333c4538a45690b640b4520b6572c40da80cb9-xpat-94cbe27a7907a9c2ac6a4bc22e3b152270493eb3da92e8449331ea0ccef6997c` |

The pool identity hashes the Mage.Sets patch sections because X-P2 and X-P3 edit 23 card classes. A tree id is used instead of "the last commit touching Mage.Sets", which a shallow clone cannot compute. `scripts/build.sh` computes both strings and writes them to `BUILD-MANIFEST.json`. The build-only patch in `patches/build-only/` does not change rules and is not hashed.

## Layout

- `vendor/cabt/`: CABT's `Mage.Player.AI` overlay, its `LICENSE`, and `services/engine/prepare_reference.py`.
- `patches/xmage/`: the core patch series, applied in name order (below).
- `patches/build-only/`: build-only patches, applied to every build. Today this is one patch, which pins the jar manifest's `Build-Time`.
- `overlay/`: the `mage.player.spellbench` package. It holds the Section 11.6 and 5.3 derivations (`Secrets`, `ids.ObjectIds`), the stream router (`rng`, patched builds only), and the X1 harness (`x1`).
- `scripts/build.sh`: one build for Windows (Git Bash) and Linux; `--stock` builds the negative control.
- `scripts/x1-determinism.sh`: the X1 evidence run.
- `tests/x1/decks/`: two MIT decks from MageZero's pool (see `NOTICE`).

## Patch series

| Patch | Purpose |
|---|---|
| X-P1 `0001-rng-router` | `RandomUtil` delegates to a pluggable `Source` (untagged, per-player and shared generators). With no source installed, XMage behaves as before. |
| X-P2 `0002-rng-call-sites` | Purpose-tagged draws: library shuffle and both random-order library placements per owner; random cards per owner (`seekCard`, `CardsImpl.getRandom`, random mill); coin flips, die rolls and the starting-player toss shared. The five card classes that called an unseeded `Collections.shuffle` become seeded. |
| X-P3 `0003-deterministic-ids` | Every `UUID.randomUUID()` in Mage, Mage.Common and Mage.Sets (66 sites) becomes `RandomUtil.newId()`. The two static random ids become name-based constants. `randomFromCollection` orders hash-ordered collections by id before drawing. |

The router (`overlay/.../rng/GameRandom`) implements Section 11.6:

- Each tagged stream `scope:purpose` (scope `p0`, `p1` or `shared`) is HMAC-SHA256 in counter mode, keyed by `HMAC-SHA256(game_secret, "spellbench/v2/rng:<scope>:<purpose>:0")`.
- Every untagged draw takes its own stream `shared:untagged:<k>`.
- Object ids come from `shared:object_id`.
- `java.util.Random`'s 48-bit state is never used.

Per-viewer object ids follow Section 5.3 (`ids/ObjectIds`). The Section 16 vectors are checked by `DeterminismCheck --selftest`.

## Build

```bash
scripts/build.sh --out <dir outside the repo> --xmage-repo <XMage clone> --m2 <Maven repo>
```

The script runs these steps:

1. `git archive` of the pin with LF line endings.
2. The CABT overlay, plus CABT's own pom preparation.
3. The patches.
4. The Spellbench overlay.
5. `mvn package` with `project.build.outputTimestamp` pinned.
6. Write `lib/` (jars plus `classpath.txt`) and `BUILD-MANIFEST.json` (pins, identity strings, JDK, Maven, jar hashes).

Nothing is installed into the Maven repository. Network use is Maven Central, plus a `git fetch` of the pinned XMage commit when the clone lacks it.

Each engine process runs in its own working directory with its own copy of the card database (`./db`, about 259 MB). The database is built once with `DeterminismCheck --scan-only` and copied.

### Reproducibility (2026-09-30, branch commit 4c4f189)

| Builds | Toolchain | Wall time | Result |
|---|---|---:|---|
| Windows A and B, clean | Oracle JDK 23.0.1, Maven 3.9.8 | 3 to 4 min each | all 41 jars byte-identical, `lib_digest` `e62dd8c81778516c2f6a209ad15e4b1dc662ff5fb4d484d6c07225bc691c774d` |
| Linux L1 and L2 (WSL Ubuntu), clean | OpenJDK 21.0.11, Maven 3.6.3 | about 2 min each | all jars byte-identical, `lib_digest` `72f30dde24f8b5ac464d3006f717bf4d070d08b5128a27ce58ad0021cbc4c935` |

Both platforms compute the same identity strings. The jars differ between platforms because the JDKs differ, and `BUILD-MANIFEST.json` records the JDK. The Windows manifests are in `tests/x1/evidence/`. Known cosmetic residual: Maven 3.6.3 writes ANSI color codes into the manifest's `maven` field.

## X1 determinism

```bash
scripts/x1-determinism.sh --build <patched build> --stock-build <build.sh --stock output> --work <scratch dir>
```

The script runs these checks:

1. The Section 16 self-test.
2. One card-database template per build.
3. Patched build: game S (`game_secret(0)` of the Section 16 run secret; decks Standard16-RG vs Standard16-UB) is recorded with a seeded random driver, then replayed from the recorded answers:
   - in one JVM as S, S2, S;
   - in two fresh processes.
4. A soak: `game_secret(2..5)` recorded in one JVM, then replayed in reverse order in another.
5. The same S plan on the stock build (CABT's `RandomUtil.setSeed` path).

Each engine process has its own working directory and card database.

Results (2026-09-30; Windows and Linux gave the same digests; `tests/x1/evidence/results-windows.jsonl`):

| Build | Runs of S | Decisions | Transcript digest | Verdict |
|---|---|---:|---|---|
| patched | record, fresh 1, fresh 2, JVM first, JVM third (after S2) | 787 each | `054bcc3329f1...` in all five | identical |
| patched soak | 4 secrets, record vs reverse-order replay | 677 to 927 | equal per secret | identical |
| stock | record, fresh 1, fresh 2, JVM first, JVM third | 637 recorded; replays break after 44 to 146 | five different digests; content digests (UUIDs blanked) also differ | diverges |

`X1 verdict: PASS` on both platforms (`tests/x1/evidence/x1-windows.log`).

What it took beyond the patch series:

- **Boot warm-up.** Every framework class is initialized under a fixed boot id stream before the first game. `StackAbility` mints an id in a static initializer, mid-game. Without the warm-up, the first game in a JVM consumed an id that reruns did not, and the third game diverged at decision 147 (exile zones keyed by a shifted id). `-Dspellbench.trace.clinit=true` reports any id a game draws inside a static initializer; the final runs report none.
- **Deck card classes.** These are initialized under the boot stream at each game's setup.

## Byte budget and prune record

Scratch root `D:/e-scratch/xmage-x-spike/` is registered in `collab/ARTIFACTS/catalog.jsonl`, with a projected 3 GiB and a cap of 6 GiB. Linux builds live in WSL `~/x-spike/`.

Pruned at spike closure (2026-09-30, all regenerable with `scripts/build.sh` and `scripts/x1-determinism.sh`):

- every per-process card-database copy (about 259 MB each);
- the superseded X1 work trees and the diagnostic tree;
- the patch-authoring repos;
- Windows build B (its manifest equals A's and is kept in `tests/x1/evidence/`);
- the `src/` trees of the kept builds.

Kept:

- `build-a/lib` and `build-stock/lib` with their manifests;
- `x1-final/` (transcripts, summaries, logs);
- the build logs;
- in WSL: `build-l1`, `build-l2`, `build-lstock` and `x1-linux` (not pruned: WSL stayed off at the request of another lane's timing run).
