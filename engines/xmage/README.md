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
| `rules_snapshot_id` | `xmage-<XMage commit>-xpat-<sha256 of patches/xmage/*.patch concatenated in name order>` | IDENTITY_RULES |
| `card_pool_identity` | `xmage-sets-<git tree id of Mage.Sets at the pin>-xpat-<sha256 of the patch sections under Mage.Sets/>` | IDENTITY_POOL |

The pool identity hashes the Mage.Sets patch sections because X-P2 and X-P3 edit 23 card classes. A tree id is used instead of "the last commit touching Mage.Sets", which a shallow clone cannot compute. `scripts/build.sh` computes both strings and writes them to `BUILD-MANIFEST.json`. The build-only patch in `patches/build/` does not change rules and is not hashed.

## Layout

- `vendor/cabt/`: CABT's `Mage.Player.AI` overlay, its `LICENSE`, and `services/engine/prepare_reference.py`.
- `patches/xmage/`: the core patch series, applied in name order (below).
- `patches/build/`: build-only patches, applied to every build. Today this is one patch, which pins the jar manifest's `Build-Time`.
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

BUILD_EVIDENCE

## X1 determinism

X1_EVIDENCE

## Byte budget

Scratch root `D:/e-scratch/xmage-x-spike/` (registered in `collab/ARTIFACTS/catalog.jsonl`): projected 3 GiB, cap 6 GiB. Builds are about 350 MB each, a card database about 259 MB per engine process. WSL builds live in `~/x-spike/`.
