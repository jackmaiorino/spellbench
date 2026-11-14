# Perfect-information track (design note)

Status: proposal for maintainer review, 2026-11-08. No implementation, no runs. Nothing here changes an existing benchmark, engine pin or rating.

## Why

Every Spellbench board rates agents under hidden information (spec 6.8, 13). A community contributor measured, for MageZero on XMage, about +200 Elo from perfect-information search at a 300 budget and +250 at 1000, against about +100 and +120 from PIMC (search over sampled hidden worlds). That gap is a useful number in its own right: it bounds how much a bot could still gain from better inference about hidden cards. Spellbench can measure it under one protocol, one validator and one rating method, if perfect-information play lives on a separate, clearly labelled track that can never feed a fair board.

Two framing points:

- **PIMC is fair play.** Sampling worlds from the seat's own information is what the XMage kit already does (`kit-mad-k` votes over K = 4 sampled worlds). PIMC entries belong on the ordinary hidden-information boards. Only search that reads the true hidden state belongs on this track.
- **CP7 today.** The 2026-09-27 plan was to host native CP7 as a labelled reference because its search reads the whole game. What actually shipped are the kit's fair variants (`xmage-mad7-fair-s1` to `-s10`, one sampled world each). No whole-game CP7 runs on any board yet, so the open CP7 seat proposed below is new work, not a relabel.

## 1. Protocol: opting in and marking runs

### 1.1 What an open seat receives

A new neutral payload, `open_state`, carried as a spec-defined extension so engine-specific readers keep working:

```json
"extensions": {
  "x_open_state_v1": {
    "schema": "spellbench/open-state/v1",
    "level": "full",
    "hands":     {"p0": ["Llanowar Elves", "Forest"], "p1": ["Counterspell"]},
    "libraries": {"p0": ["Island", "..."], "p1": ["..."]},
    "face_down": [{"object_id": "o17", "card_name": "Shock"}],
    "pending_choices": [{"seat": "p1", "kind": "chosen_name", "value": "Lightning Bolt"}]
  }
}
```

- **Levels.** `open_hands` reveals both hands, face-down objects and already-made hidden choices. `full` also reveals both libraries in order (top first). A board declares one level.
- **Never revealed, even at `full`:** the run and game secrets, RNG state, and therefore any future randomness (later shuffles, coin flips, random discards). The engine keeps seeding as spec 11.6 requires. A bot can see the current library order but cannot predict a reshuffle.
- **Ids.** `face_down` reuses the observation's per-decision object ids; hand and library entries are names only, so no stable identity crosses decisions (spec 5.3 still holds).
- **Hands are sorted** by name; library order is the true order.
- Engines may also offer native full-state payloads (`x_kernel_state_v1`, `x_xmage_state_v1`) for engine-native models, enabled per board like any extension.

### 1.2 Rules, entitlement and host checks

- **Rules field.** `rules` (spec 12.2) gains `open_state`: `null` on every existing board (the default, so their manifests and goldens are unchanged in meaning), or `{"level": "open_hands" | "full", "seats": [...]}` naming the seats entitled in this game. Both agents receive the rules, so a hidden-information seat knows when its opponent sees everything.
- **Entitlement is per bot.** A benchmark bot entry declares `"information": "open"`. The host sets `seats` per game from the schedule (the open bot changes seat across a swapped pair).
- **Engine.** The engine declares `open_state` support in `hello_ok` and emits the payload only on decisions of entitled seats.
- **Host verification (fail closed).** The host rejects, as a live-validation violation, any `x_open_state_v1` or native full-state payload on a non-entitled seat's decision, and any open payload on a board whose `open_state` is null. This is checkable without ground truth, unlike leaks through text.
- **Fairness contract.** F1 (perspective) is waived for entitled seats only. F2 to F6 still apply to everything else, and the non-entitled seat keeps the full hidden-information guarantee: the paired-world leak tests run unchanged on its messages.
- **Fairness label.** `information_rules.fairness_label` gains a third value, `open information`, which every open board must carry and no hidden board may carry.
- **Spec version.** This is an additive minor version (v2.x): a new rules field, a new label value and one spec-defined extension.

### 1.3 Keeping tracks from mixing

Defence in depth, each check mechanical:

1. **Benchmark field.** `benchmark.json` gains `"information": "hidden" | "open"` (absent means hidden). Board ids for open boards carry an `-open` suffix (for example `fdn-open-v1`).
2. **Bot names.** Entitled bots end in `-open` (for example `xmage-mad7-open-s6`). The site build and `bench prepare` refuse a bot with `"information": "open"` on a hidden board, and refuse an `-open` name anywhere outside an open board.
3. **Manifests and ledgers** record `open_state` with the information rules. Changing information rules already invalidates a panel's blocks (docs/reference-panels.md); S2 adds a test that an open run can never be composed into a hidden snapshot.
4. **Site.** The Hero chart ("Elo above the random bot") skips any leaderboard whose manifest says open, reading the manifest rather than trusting `tracks.json`. The tracks loader refuses a track that mixes open and hidden boards.
5. **Engine bytes.** Open support ships as a sibling engine entry point (the pattern `kernel_engine_infoset_v2.py` uses), so pinned engine commands and hashes of existing boards stay byte-identical.
6. **Measurement only.** As with CP7, open-board results never feed model or experiment selection for mtg-kernel.

## 2. Engines

| Engine | Fit | What it needs | Rough effort |
|---|---|---|---|
| **XMage** (first host) | Best. CP7, MCTS and MageZero all search XMage `Game` copies, and the overlay's `ObservationBuilder` already has the whole game in hand. | Emit `x_open_state_v1` from the overlay for entitled seats; keep the observation itself unchanged; rerun `tests/x5` leak tests on the non-entitled seat; add tests that an open payload matches engine state. | 3 to 5 agent-days |
| **XMage kit, open mode** | Gives open twins of the existing fair entries. | `WorldBuilder` takes hidden zones from the payload instead of the `Sampler`, K = 1. New frozen entries (`mad7-open-sN`, `kit-mcts-open`) with their own identities. The existing round-trip diagnostics (`RoundTrip`, `ObsCompare`) check the rebuilt world against the payload. Reconstruction limits (register horizons, unsupported states) still apply, so this is close to, not identical with, native CP7. | 3 to 4 agent-days |
| **MageZero** | The contributor's measurement is on MageZero. | Its encoder and search are wired in the confined runtime, but trained exports, exact decks and play settings are still missing (engines/xmage/BOTS.md). Once supplied: a hidden entry (PIMC over sampled worlds) and an open entry at the same budgets (300, 1000). Its decks are Standard, which points at a Standard board. | 2 to 4 agent-days after inputs arrive |
| **mtg-kernel v2** (`integrations/mtg_kernel/kernel_engine_v2.py`) | Feasible. The native bridge already holds the private state in process and serves clone and preview requests; `kernel_engine_infoset_v2.py` shows the pattern of a bridge flag plus a sibling wrapper that forwards a per-seat canonical payload. | A new bridge flag emitting the full canonical state (both hands, library order) for entitled seats, a sibling wrapper forwarding it as `x_kernel_state_v1` and `x_open_state_v1`, and the host check above. The bridge change lives in mtg-kernel, outside this repo. Kernel search entrants themselves are separate work in the research lead's lane. | 2 to 3 agent-days here, plus the bridge change |
| **gorge** | Cheap. Its view already has an `omniscient` projection (spec Annex B uses `seat`). | Build `x_open_state_v1` from the omniscient view for entitled seats. | about 2 agent-days |

## 3. Board design

- **Track.** A new entry in `benchmarks/tracks.json`, `perfect-info`, titled "Perfect information (reference only)", with an `"information": "open"` key (the loader's strict key set grows by one optional key). Its pages carry a fixed banner: "Entries marked open see hidden cards. These ratings are not comparable to any other board."
- **First board.** One XMage board. Two candidates:
  - `fdn-open-v1` on a subset of the 16 FDN decks, where the CP7 fair variants are already wired; or
  - `standard-open-v1` on MageZero's own Standard decks, if its exports arrive with them.
- **Roster.** `uniform` (anchor at 1000, as on every board), `heuristic`, and twin pairs that differ only in information: `xmage-mad7-fair-s6` and `xmage-mad7-open-s6`; `kit-mad-k` (PIMC, hidden) beside them; later MageZero hidden, PIMC and open at budgets 300 and 1000.
- **Who plays whom.** Open entries play the hidden panel (via `opponent_panel`) but not each other in v1. Every rating then answers one question: how much does seeing everything buy against the same hidden-information opponents. Open-versus-open play is a different game and is left to a later board.
- **Side by side.** Yes, on the open board only. Hidden twins play there too, against the same panel, so the gap is Elo(open) minus Elo(hidden) on one board, with a bootstrap interval over game pairs. The board page adds a dumbbell chart, one row per twin pair (hidden dot, open dot, gap with its interval), next to the normal leaderboard. The fair board never shows open rows; a bot page may link to its gap.
- **Sanity check.** A hidden twin's Elo on the open board should agree, within intervals, with its Elo on the matching fair board when the panel overlaps. A large disagreement points at a harness problem, not a skill gap.
- **Site code.** `python/spellbench/site/` needs the Hero exclusion, the track check, the banner, and the gap chart (a new chart in `charts.py`). About 2 to 3 agent-days with tests.

## 4. Staged plan

| Stage | Work | Effort | Depends on |
|---|---|---|---|
| S0 | This note; maintainer answers the open questions | none | |
| S1 | Spec v2.x amendment: `rules.open_state`, `x_open_state_v1` schema, `open information` label, host strip and verify, manifest and ledger fields, conformance goldens on the reference fake engine | 3 to 4 days | S0 |
| S2 | Separation in tooling and site: benchmark field, name checks, composition refusal test, Hero exclusion, track check, banner, gap chart | 2 to 3 days | S1 |
| S3 | XMage engine emits the open payload; leak tests on the non-entitled seat; payload-matches-engine tests | 3 to 5 days | S1 |
| S4 | Kit open mode and frozen open entries | 3 to 4 days | S3 |
| S5 | First open board: definition, compute qualification under COMPUTE-POLICY, commitment, run, publish. Game count and hours sized at qualification. | 1 to 2 days plus compute | S2, S4 |
| S6 | MageZero hidden, PIMC and open entries | 2 to 4 days | author inputs, S5 |
| S7 | Optional: mtg-kernel and gorge open payloads | 2 to 3 days each | S1; kernel bridge change |

S1 to S5 is roughly 12 to 18 agent-days before compute.

## 5. Open questions for the maintainer

1. **Level.** Should the first board use `full` (library order visible) or `open_hands`? `full` most likely matches what the MageZero numbers measured, since XMage AI game copies keep library order; worth confirming with the contributor.
2. **Open versus open.** Keep v1 to open-versus-hidden only, as proposed?
3. **Native CP7.** Is the kit's open mode (protocol path, live validator, reconstruction approximations) enough, or is an engine-hosted CP7 seat wanted too (faithful to native CP7, but outside the agent path, so no agent clock or isolation)?
4. **First board.** FDN subset now, or wait for MageZero inputs and start on Standard?
5. **Naming.** "Perfect information" with an `-open` suffix, or another term?
6. **Self-reported runs.** May the MageZero author run open entries on their own machine through a remote seat (labelled self-reported), or only verified sandboxed runs?
7. **Spec scope.** Is an additive v2.x amendment acceptable, given v2 is still a community-review draft?
