# Everyone on the board (program)

Status: direction set by Jack 2026-09-26 ("work towards getting them all on
the leaderboard; that's how we get engagement"). Decisions below were made
under Jack's standing authorization and are reported, not blocking.

## Goal

Every MTGRL community bot or model rated on the Spellbench leaderboard,
starting with the ones that exist today. Success is measured by bots on the
board, not by features: each sub-project below ends with a named bot rated.

## Where each project stands (research 2026-09-26)

Full notes (kept out of the repository): `E:/spellbench-archive/program-research/`
(`research-community-landscape.md`, `research-C-kernel-models.md`).

| Project | What exists | Path to the board | Blocked on |
|---|---|---|---|
| mtg-kernel (Jack) | g115, A48, c12 checkpoints; Codex's local branch | Bridge ported to Codex's evaluation commit `cd41885e`, g115 input extension, stdlib bot around the existing scorer | Engine port (3.5 to 4 agent-days); Codex owns the inputs (read-only use) |
| gorge | Go engine (91.6% of Forge cards), 3 bots, per-seat fair view | gorge as a second engine: Go stdio adapter + `x_gorge_view_v1` + a Go agent wrapping his bots | Protocol v2 decision kinds (or declared defaults); Go toolchain and gorge source on this PC |
| DraftZero | FDN Limited models on XMage (pickled checkpoints) | FDN Limited on XMage; its search runs on a copy of the real game, so a rated entry needs policy-only play through an audited extension or its own search over sampled worlds (its position rebuilder does most of this) | XMage adapter; v2.1 rotating pairs with hidden lists; pickles only inside a sandbox |
| MageZero | Deck-local models, 16-deck Standard 2022-25 pool | Standard 2022-25 on XMage with a bring-your-own-deck benchmark type; same fair-search gap as DraftZero, and its shipped config appears to feed the opponent's hand to the network | XMage adapter; v2.1 fixed-deck benchmarks and legality lists; fair mode |
| Manafold | Engine without real cards yet; tracks a "UCI-like" agent protocol (issue #128) | Protocol co-review now; adapter after his M4 milestone | His roadmap |
| Other Discord members | Nothing public found | Ask | Outreach |
| Also found | pauper_sim (5 archetypes overlap our pool), Phase (Rust engine, fair AI), Argentum (FDN cards), NMaass CABT (MIT XMage NDJSON bridge) | Board view (pauper_sim); engine adapters (Phase, Argentum); CABT as the XMage adapter core | Same as above |

## Sub-projects, in order

1. **C: Jack's models on `pauper-kernel`.** Port the bridge to `cd41885e`,
   add `x_kernel_flat_v4` (g115's input computed by the evaluation's own Rust
   code in a lockstep training-mode copy, plus the model-row to candidate-id
   map), a stdlib Python bot around the existing scorer (v4 mode, seeded
   sampling), halts for missing inputs. Then A48 and c12 by config. Re-run the
   launch benchmark on the new engine identity.
2. **P: Protocol v2.** (Plan: `docs/design/2026-09-27-protocol-v2-plan.md` on
   branch `protocol-v2`, 44 tasks, 24.5 agent-days, about 6.5 days elapsed
   with parallel agents.) A neutral, hidden-information-safe board view for the
   acting seat; the missing decision kinds (mulligan, library arrangement for
   scry and surveil, naming, replacement and trigger order, starting player);
   the acting seat's own decklist at `game_start`; a declared fairness
   contract; and a fixed-deck ("bring your own deck") benchmark type. Clean
   break from v1 while no outside bot depends on it. Reference stack, arena,
   builtins, conformance tests, then the mtg-kernel bridge (after C's port).
3. **G: gorge as the second engine.** (Plan: `docs/design/2026-09-27-gorge-adapter-plan.md`
   on branch `gorge-adapter`, 30 tasks, 17.25 agent-days, runs beside P; only
   its last task, the rated run, waits for P.) Go environment adapter, gorge bots as
   agents, a gorge benchmark (the 8 Pauper lists if gorge covers them, for a
   cross-engine comparison), gorge's bots rated. Offer gorge's author the
   adapter as a pull request, or let them own it.
4. **D: Join kit.** Join page and guide, a starter bot on v2, local try-out
   against the builtins, and a submission path with two tiers: self-reported
   runs (labelled) and verified runs, where the maintainer runs the bot in a
   network-less Docker container on this PC. Prebuilt bridge binaries once
   publishing is decided.
5. **X: XMage for FDN Limited and Standard 2022-25.** A Java overlay that
   vendors CABT (reusing its callback coverage, not its observation, which
   leaks face-down exile and shares ids across seats) plus a small XMage
   random-number patch offered upstream. Estimate 21 to 27 agent-days for the
   engine and both benchmark definitions; getting DraftZero and MageZero
   rated fairly adds 10 to 16 days shared with their authors. Needs v2.1:
   fixed-deck benchmarks, rotating pairs with hidden lists, legality lists,
   per-benchmark time controls. FDN mirror matches work on v2.0. Research
   notes: `E:/spellbench-archive/program-research/x-xmage-brief.md`.
6. **Later:** Phase and Argentum adapters, Forge, Manafold after its M4.

## Decisions (standing authorization)

- Protocol v2 now, as a clean break: the only v1 bots are ours.
- The fairness contract is part of v2: engines never leak hidden state,
  every published benchmark declares it, and bots that need clairvoyance
  cannot enter. Spellbench as the harness where peeking is impossible is a
  selling point (DraftZero's own audit found its search reads hidden cards).
- Community bots never run on this PC outside a Docker container with no
  network, and pickled checkpoints load only inside that container. Engine
  sources needed for adapters (gorge now, XMage and CABT later) are built and
  run on the host, and so are bots the maintainer builds from the same
  pinned, reviewed source (gorge's own bots). Submitted binaries, checkpoints
  and pickles always need the sandbox; the host enforces this with an
  allowlist (P, Decision on isolation).
- Codex-owned kernel code and checkpoints are used read-only; nothing of
  Codex's is pushed; Spellbench results are measurement only.
- Outreach (Discord posts, GitHub issues on members' repositories) is drafted
  here and sent by Jack.

## Approved by Jack (2026-09-26, "Approved for all")

1. Downloading and building community code for adapters: the Go toolchain
   and gorge's source first, later XMage and CABT.
2. Telling Codex about the bridge port (posted to the collab mailbox).
3. Outreach drafts, which Jack sends.
