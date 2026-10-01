# X5 status (for the coordinator)

- 07:42 EDT: catalog has both pools (32 decks, all pass validate_deck). First qualification on Jack's PC was refused
  by P's guard: one game's digest depended on the games its engine process had played before (XMage's parsed
  mana-cost cache). Fixed in the overlay (commit 8ba4df9); rerunning the qualification. HaleysPC is refused by
  P's guard (54.6 GiB free on C:, reserve 60 GiB), so the run is Jack's PC only.
- Projection: about 1.7 s per game per worker; the 10,112-game run should take well under an hour on Jack's PC.
  Finish of benchmark plus run expected well before 11:00 EDT.
