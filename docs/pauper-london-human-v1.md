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
