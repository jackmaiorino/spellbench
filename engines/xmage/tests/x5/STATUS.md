# X5 status (for the coordinator)

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
