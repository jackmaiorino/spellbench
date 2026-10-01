# X5 status (for the coordinator)

## 10:40 EDT

- Final run on Jack's PC: P's guard chose 12 workers again (busy-time rates 37.8, 116.3, 106.5 games per minute at
  1, 12, 24 workers; outputs identical). 4,800 of 10,112 games played at 205 per minute, 0 validator violations,
  0 halts. Run ends about 11:06, the hash-perturbation check about 11:12.
- **Estimate past 75 minutes:** after the run I rerun the leak suite on the final build (about 15 min) and
  regenerate the X4b goldens (the catalog and X-P4 change `hello_ok`, which they embed; about 3 min), so Jack's
  PC is clear about 11:30, 84 min after "go". Tell me to skip either and I will run it on HaleysPC later instead.

## 10:10 EDT

- "Jack's PC go" received 10:06. Running `tests/x5/run-final.sh` on Jack's PC at below-normal priority, no WSL:
  build, validate_deck, P's guard (`plan_allocation`, ladder 1, 12, 24 workers), the full 10,112 games on the
  final build, then every tenth game again under another identity-hash mode, then the summary. Then the leak
  suite again on the final build (about 15 min). Estimate: about 65 min for the run, about 80 min with the leak
  suite, so the whole lot slightly exceeds 75 min; the 10,112-game run itself stays under it.
- HaleysPC: idle on my side since 10:05 as asked (no process of mine there).
- New since 08:35:
  - **X-P4 (core patch).** Games with Reckoner Bankbuster were not reproducible run to run: its Treasure and
    Pilot tokens entered in identity-hash order (`CreateTokenEvent` keeps tokens in a `HashMap` keyed by token
    objects). X-P4 makes that map and `TokenImpl`'s created-token set insertion-ordered. The game that showed it
    gave 4 different digests in 6 runs before and 1 digest in 6 runs after. `rules_snapshot_id` changes to
    `...-xpat-6f8a902b...`; `card_pool_identity` is unchanged.
  - **Halt fixes** (overlay): Run Away Together (dependent targets) now rewinds instead of halting; any-combination
    mana is a `choose_color` group; other multi-amount questions outside combat (Glissa Sunslayer removing
    counters) are a `choose_number` group. All 62 games that halted in run 1 end naturally on the fixed build.
  - **Leak tests (HaleysPC, previous build):** counterspell 50 pairs PASS (whole game identical every time; p0
    made 1,001 decisions with its spell on the stack while p1 held Counterspell over two open Islands); cantrip
    50 pairs PASS; randomized 200 pairs flagged 2 divergences, both at a choice decision on turn 1 or 3 of a
    Standard16-RB or Standard16-GB game. Both decks play Duress, which shows the observer the other hand on its
    own spell: a legitimate look the classifier did not know yet. The classifier now accepts exactly that case,
    the rerun on the final build saves the streams of any such pair, and I check them by hand.
