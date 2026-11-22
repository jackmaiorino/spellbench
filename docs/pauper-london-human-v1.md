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

## Graveyard order (`--auto-graveyard-order`)

Graveyard order is a real rule (CR 404.3): the owner of cards put into a graveyard at once orders them, and the engine
asks one card at a time (Balustrade Spy milling a library is dozens of decisions). Every training episode of the bots'
lineages runs the engine's rule `resolution-boundary-v1`: that order is never asked, and the cards keep the order the
effect put them there (a mill: library order, top first).

`python -m spellbench.human --client manabrew --auto-graveyard-order` mirrors the rule where it can have an effect and
asks nobody where it cannot:

- **A game in which no card of either deck list reads graveyard order** (every game of the eight decks today): each
  game's engine is started with `--auto-graveyard-order` and asks the bridge for the training rule
  (`auto_graveyard_order` on its reset). Neither the person nor the bot is asked; the graveyard ends up in the order
  training produced. The one ordering the protocol itself adds, the order of the cards of a multi-card discard after
  they have been chosen, is completed by the engine for both seats with the first card listed (the completion the
  bot's own proposals for the discard are scored with). The bot's decisions are byte for byte those of a game
  without the option up to the first ordering it would have been asked.
- **A game with such a card:** both players are asked, as the rules say. The person orders each batch in one step.
  The bot is asked as before, card by card through its model.
- Which cards read graveyard order is data: `python/spellbench/human/graveyard_order_cards_v1.json`, with its audit
  note. Readers today: Gurmag Angler (Delve; this engine exiles the oldest cards first), in no deck of the pool. Every
  deck card whose rules text mentions a graveyard is listed as a reader or a non-reader with the reason;
  `integrations/mtg_kernel/london_human/tests/test_graveyard_order_v1.py` fails when a deck card that mentions a
  graveyard is in neither list. The engine keeps its own check (it refuses the rule for a game with a Delve card);
  if it refuses where the data saw no reader, the game is not played: the client is told why, nothing is recorded,
  and the session ends. Add the card to the data readers before starting again. The session reads relevance from
  the catalog the engine is started with, so the engine command must name exactly one `--catalog PATH`.
- **Card orderings the person is still asked** (the order of cards going back on a library, the cards of a look,
  graveyard orders in a game with a reader) are one `reorder` step in the client, whose description says what the
  first card means. The order of cards one look puts into the person's hand is never asked (a hand has no order),
  nor, in a game without a reader, the order of a look's cards going to the graveyard; the session takes the first
  card listed and records the answer as `auto_order`.

A bridge without the rule refuses the reset, so a session never plays without what it promised. Leave the option out
to be asked card by card.

## Planned line (`--planned-line`, with `--advisor`)

The advisor panel also lists the model's own line from the person's decision: its top choice, played forward on a
copy of the game, then its top choice at the person's next decision, and so on. It is labelled "Bot's line (its top
choice at each step), if the opponent does not respond". It is not a search and never "the best line".

- **Where it is played:** the engine wrapper asks the bridge (`private_line`, human-play London server only) to play
  the person's choices on a clone; the game itself is never touched. A scorer of the wrapper's own, loaded with the
  advisor's checkpoint, picks each step from the person's own model input on the clone.
- **The opponent:** only a bare priority pass is taken for them, always, whatever they hold. Any other decision of
  theirs (blocks, targets, a sacrifice, a discard) ends the line. Nothing about their options reaches the panel.
- **Hidden cards and chance:** the line stops before a step that would draw, mill, search, look at or reveal a card,
  change the opponent's hand, or draw a random outcome. It also stops when the turn ends, at an order (cards,
  triggers), or after 8 of the person's choices (a block declaration is never cut: it counts once whole). There is no wall-clock bound: the clone's speed depends
  on whether the opponent's windows were posed, so time never decides what is shown. A hidden card and a random
  outcome are one stop ("a hidden card or a random outcome would be seen"): which of the two a resolution produces
  can depend on the hidden cards. The line's scorer gets 2 s for all its reads of one line, supervised from outside
  the exchange, or is dropped for the session. Not claimed: that the person's decision arrives at the same moment
  whatever the opponent holds (the line's computing time varies by milliseconds with the opponent's posed windows),
  or any bound on a bridge that hangs (the game's own process).
- **Declarations (the bot's line):** at the first question of an attack or block declaration, the panel shows the line
  as "The bot's line": the whole attack or block the bot would declare, then its top choice at each step. The engine
  asks one creature at a time (a block: one attacker and blocker pair at a time, attacker by attacker); each question
  is answered with the model's top choice given its own answers before, on the clone, and a block is shown blocker by
  blocker. It is one plan of the bot's, not separate advice for each creature: the per-creature reads beside it are
  scored on their own. Later questions of the declaration show no line. The playing bot is asked nothing new.
- **Game end:** "wins this turn if the opponent does not respond" when the line ends the game this turn.
- **What travels:** the extension `x_advisor_line_v1` on the person's ordinary decisions and the first question of
  their block declarations only (never the bot's, never the pregame), enabled only for such a session: the steps, how the line ends, and the result. No counts, no timing.
  The hub takes it off the decision as it takes the model input, and the relay drops it without an advisor.
- **Client:** the local panel patch in `dist-advisor-4`.
