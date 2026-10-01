# X5 status (for the coordinator)

## 08:35 EDT

- **Stopped on Jack's PC (your 08:2x message):** the 10,112-game run (`x5run.py run`, machine main-pc, 12 workers,
  started 08:15 after P's guard chose 12 workers). Your kill took it and its engines; I then confirmed no java,
  javac, maven or engine process is left on Jack's PC (python processes left there are mtg-kernel's and VS Code's,
  not mine), no WSL distro is running, and I removed the engine work directories. 2,216 games had finished and are
  recorded with their ledger rows and digests (0 validator violations, 62 halted, 2,154 natural).
- **HaleysPC cannot host the run under P's guard:** `plan_allocation` refuses it before the first game because its
  only volume (C:) has 54.6 GiB free, below the 60 GiB reserve (ARTIFACT-LAW.md clause 1). My own files there are
  under 1.2 GiB, so I cannot clear that legitimately, and I will not bypass the guard. Options: (a) the remaining
  7,896 games wait for "Jack's PC go"; (b) Jack or Haley frees about 6 GiB on HaleysPC's C:; (c) you or Jack
  grant an explicit exception to the reserve for this run (its own footprint there is about 3 GiB of transient
  engine scratch and 15 MB of rows). Until one of these, I do only small correctness work on HaleysPC.
- **Meanwhile on HaleysPC (small, below-normal priority):** paired-world leak tests (counterspell position: 50
  pairs done, p0's stream identical over the whole game in every pair) and two engine fixes for the only halt
  causes seen so far (all 62 halts come from two decks):
  - FDN_top_21511_WUR, Run Away Together ("two target creatures controlled by different players"): the mapper
    offered a first target with no legal second one, `dead_end:choose_target` (Section 7.1 no dead ends; the
    engine declares rewind, so it must rewind, not halt);
  - Standard16-RB, Chandra, Hope's Beacon +2 ("two mana in any combination of colors"): XMage asks a multi-amount
    question outside combat, `unsupported:multi_amount`.
- Projection once Jack's PC is back: qualification about 5 min plus the full 10,112 games at about 210 games per
  minute, about 50 min (I would rerun all of them on the fixed build, so the evidence is one build).
