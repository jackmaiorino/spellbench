# pauper-london-human-v1: London mulligans for human play

A human-only board. It is a copy of `pauper-ladder-v2` made by `tools/make_london_human_board.py` into a scratch
folder, never into `benchmarks/`. Games on it are unrated and never training data. The rated board, its engine inputs,
its bridge and its bots are not touched.

## What differs from pauper-ladder-v2

- The engine is `integrations/mtg_kernel/london_human/kernel_engine_london_human_v1.py`. It declares
  `rules_supported.mulligan: ["london"]` and starts the London bridge (`agent_bridge_v1 --pauper-london-human-v1
  --x-kernel-flat-v7 --private-v2-support`, built from the mtg-kernel commit the bots trained on).
- The pregame is protocol-native: a `mulligan` decision (`keep` true or false) for each seat, and after a mulligan an
  `order_pick` group with `purpose: mulligan_bottom` (`count` = the seat's mulligans taken, one item per hand card).
  The engine bottoms a mulligan's cards right after the new seven are drawn, before the next keep or mulligan answer,
  so the group precedes that decision.
- The bots run `kernel_flat_bot_london_human_v1.py`: the same bot with the FlatV7 identity. Their mulligan and
  bottom choices are their model's own. There is no mulligan rule and no keep lean anywhere in the path.

## Visibility and policy inputs

- Model input: `x_kernel_flat_v7`, the acting seat's own FlatV7 tensor. In-game rows equal the V4 rows; a pregame row
  carries the actor's own hand, the mulligans taken by both seats, whether the other seat has kept, and whether it
  announced a mulligan this round. Nothing else of the other seat is in it.
- Public facts of the opening: each seat's mulligans taken (also `players[].mulligans_taken` in the observation) and,
  once the game begins, that the other seat kept `7 - taken` cards. Never a card of the other seat's hand, never what it
  put on the bottom, never the library order.
- A seat sees its own hand during the pregame (`players[].hand`) and only a count of the other's.
- The human's relay drops the model input of both generations (`DROPPED_EXTENSIONS`); the public history never names a
  card the viewer could not see.

## Full priority for the person (`--full-priority`)

By default both seats have the priority windows the bots trained on: the two main phases, declare attackers and
declare blockers, with one action per combat priority round and no second action on one's own fresh spell. A person
could not act in the opponent's end step or in their own upkeep.

`python -m spellbench.human --client manabrew --full-priority` gives the person's seat every priority window the rules
have: upkeep, draw, beginning of combat, combat damage, end of combat and the end step of either turn, and priority
while their own spell or ability is on the stack. Each game's engine is started with `--engine-windows-seat` (the
person's seat), and the bridge is asked for `engine_window_seats` in its reset. A bridge built without the feature
refuses that reset, so a session never plays without the windows it promised.

The bot's seat is unchanged, by construction: its decisions, its legal actions and its model input are those of a game
without the option whenever the person passes at the new windows, bit for bit. What follows from that:

- The bot does not respond to anything the person does in the six new steps. Its priority there is passed for it, as
  it always was, because its model never had a priority decision in those steps. An instant or a flash creature cast
  in the bot's end step or in the person's own upkeep cannot be countered.
- In the main phases and the declare steps the bot responds as before. When the person holds priority and puts several
  objects on the stack, the bot's first window comes after all of them.
- The person is no longer held to one action per combat priority round. The bot still is.

Host behaviour with the option: a stop or pass-until the client sets in any of the six steps is taken in that step
(without it, the nearest step with a window); a window in which the person has only mana abilities is sent to the
client, whose AUTOPASS countdown or Full control answers it (`--keep-mana-autopass` keeps the session passing those
itself); a window with nothing but passing is passed by the session. The advisor shows no numbers at a priority window
in the six steps or while the person's own object is on top of the stack. It still reads one kind of new window: a
second action of the person's in one combat priority round, which the bot's surface does not have either.

These games are unrated and never training data, like every game on this board.

New windows are ordinary decisions: each one the person is given (also one the session passes for them) counts
toward the game's step and decision caps, and the engine's own decision counters in the person's and the bot's
observations advance with them. Those counters are not model input. Everything else of the bot's decisions is
unchanged, as above.

## Graveyard order for the person (`--auto-graveyard-order`)

The engine asks a seat for the order in which cards that go to its graveyard together are put there, one card at a
time: Balustrade Spy milling a library is dozens of decisions. No card of the eight catalog decks reads graveyard
order (a test checks every deck card's rules text for it).

`python -m spellbench.human --client manabrew --auto-graveyard-order` starts each game's engine with
`--graveyard-order-seat` (the person's seat). For that seat the London human engine answers a pure graveyard ordering
itself and poses nothing: each position takes the first card the prompt would have listed (card name, then object
id). That covers a mill and the order of several discarded cards after the person has chosen them; choosing which
cards to discard, the order of cards put on top of a library, and every other choice stay the person's.

Nothing else moves: the bridge receives exactly the native steps of the game in which the person takes the first
candidate of every ordering decision by hand, so the bot is shown the same decisions, byte for byte. One difference
remains: a settled ordering is not a step or a decision of the game, so the game's step and decision counts are lower
by the prompts not posed, and a game that runs into a step or decision cap reaches it later than the by-hand game
would. The bot's seat is still asked for the order of its own mill, as on every board that uses this bridge. Leave the
option out to be asked card by card.

The audit behind "no card reads graveyard order" is a pinned list in
`integrations/mtg_kernel/london_human/tests/test_graveyard_order_v1.py`: the 18 deck cards whose rules text mentions a
graveyard, each read by hand. A deck change that adds one fails that test until the new card has been read. The text
pattern beside it is a heuristic only.
