# X5 status (for the coordinator)

## 12:35 EDT: warm-up fix verified on HaleysPC

- Rebuilt on HaleysPC at below-normal priority (`lib_digest e8e5a42b`, commit `b5ce052`), stayed out of
  `x-spike/kit`. Small check only: 17 + 217 games, each under the default identity hash and `-XX:hashCode=3`,
  in different process layouts. 0 violations, all natural (`evidence/warmup-verify.json`).
- **Warm-up fix works.** All 10 divergent games of Standard16-RW and -MonoW now give one digest in both modes, equal
  to the main run. The check's 169 games outside Standard16-UG (46 RW, 44 MonoW, 80 other cells) are all equal
  across modes; 168 equal the main run, and the remaining one was a first-in-process game in the main run.
- **Second cause, open (Standard16-UG only):** 16 of 47 UG `heuristic`-vs-`uniform` games (and 5 of its 7
  divergent ones) still change with the hash mode. Traced in game 4187 to `ability_index` of abilities that
  Agatha's Soul Cauldron grants to Sentinel of the Nameless City: their order follows identity hash codes.
  Proposed mapper fix (visible ordering of granted abilities) in `README.md`; not implemented. UG plays 316 of the
  10,112 games.
- HaleysPC `~/x-spike/x5` pruned to 1.4 MB (rows, comparisons, leak summaries); builds and sources removed.
  Nothing of mine is running there. The full 1,011-game recheck waits for Jack's PC.

## 11:50 EDT: final

- **Jack's PC is clear.** No java, javac, maven or engine process of mine remains (checked); engine work
  directories removed; scratch `D:/e-scratch/xmage-x-spike` pruned to 0.8 GiB (cap 6 GiB). WSL distributions
  "Ubuntu" and "docker-desktop" are running, but I did not start them (none ran at 07:10 or 08:28; I never ran a
  WSL command other than listing), so I left them alone.
- **HaleysPC:** idle on my side since 10:05. Leftover scratch there: `~/x-spike/x5` (builds, about 1.2 GiB).
- **Final run** (Jack's PC, P's guard chose 12 workers): 10,112 games in 50 min (200.6 per minute), all natural,
  **0 validator violations** over 5,982,064 decisions, 0 halts, 0 truncations. Leak suite on the final build:
  counterspell 50, cantrip 50, randomized 200 pairs, all PASS. X4b goldens regenerated (5 of 5 PASS).
- **Open (needs HaleysPC or Jack's PC later):** every tenth game replayed under another identity-hash mode: 994 of
  1,011 equal, 17 differ. Traced: process history, not hashing. XMage's AI class `MagicAbility` mints ids in its
  static initializer, which first runs mid-game when engine autopay ranks objects. The fix (boot warm-up also
  initializes `mage/player/ai/`, `Warmup.java`) is committed but not built or verified: rebuild, replay the
  affected games (Standard16-UG, -RW, -MonoW, `heuristic` against `uniform`), rerun the hash check.
- Details, numbers and questions for P: `README.md`.
