# X3 evidence: the observation builder

Task X3 (issue #16): the Section 6 observation of `mage.player.spellbench.observe`, checked with the reference
validator of the protocol-v2 branch.

## Command

On HaleysPC, engine built from branch `xmage-x0-x1` at `0619c3d` (`BUILD-MANIFEST-haleyspc.json`; identity strings
unchanged from X1), reference stack at protocol-v2 `4b588a1`:

```bash
scripts/x3-observe.sh --build ~/x-spike/build --db ~/x-spike/db --p2 ~/x-spike/p2 --work ~/x-spike/x3/evidence
```

The script runs `ObservationSoak` (seeded random two-seat games in-process, both seats' observations built at every
prompt, the X1 random driver answering), then `check_observations.py`. For every observation the checker runs the
live validator's own checks in rule order: V1, V2, V4, V5, V6, V7 (one `IdTracker` per seat over the whole game),
V8 and V9. V3 and V10 concern the mapper and the server. The acting seat's option references go in as
`select_object` candidates, so V1, V4 and V5 also check what X4's candidates will carry. It also checks these
invariants against an engine-side audit (internal keys, face-down objects, hidden names):

| | Invariant |
|---|---|
| I1 | no id appears in both seats' streams |
| I2 | an id always stands for one internal key |
| I3 | an object seen under a new zone change counter has a new id |
| I4 | a look keeps its id across consecutive observations; a later look gets an id the seat never saw |
| I5 | no string in a seat's observation is a name borne only by cards hidden from it |
| I6 | a face-down object is named exactly for the seat XMage's `CardView` lets look; unnamed in exile, it has no characteristics |

`mutation_test.py` injects eight faults into a copy of one game file. The checker catches all eight
(`mutation-haleyspc.txt`).

## Results (2026-10-01)

| | Catalog decks | Face-down decks | Total |
|---|---:|---:|---:|
| Games | 240 (RG vs UB, both seatings, both starting seats) | 120 | 360 |
| Prompts | 176,024 | 93,738 | 269,762 |
| Observations checked (both seats) | 352,048 | 187,476 | 539,524 |
| Validation failures | 0 | 0 | 0 |
| Invariant violations | 0 | 0 | 0 |

- Verdict `X3 verdict: PASS` (`x3-haleyspc.log`, `check-haleyspc.json`, per-game rows in `games-haleyspc.jsonl`).
- Coverage: 1,653 looks (library searches, the other seat's hand), 19,561 zone changes, 76,368 stack entries.
  Face-down objects checked for each seat: 16,730 on the battlefield, 291 on the stack, 179,411 in exile.
- Determinism: a fresh process replays games 0 to 7 with the same per-game digests (8 of 8).
- 358 games ended naturally. Two face-down games (251, 278) hit CABT's fail-closed multi-amount enumeration cap,
  which X4's `distribute` replaces. No game halted in the observation builder.
- 174 option ids name no held object: the sources of resolving abilities that left (a sacrificed Map token). They
  become null references (Section 5.1).
- Wall time: 324 s for the soak in 6 processes, 7 min with the check.

## Decks

`decks/BGRoots.dck` and `Standard-MonoG.dck` come from MageZero's fork (see `../../NOTICE`); they add disguise and
face-down exile. `decks/X3-FaceDown-UG.dck` is Spellbench's own list for foretell, disguise, manifest dread and
cloak: in 120 trial games, BGRoots's single Hoarding Broodlord never reached face-down exile.
