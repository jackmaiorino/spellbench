# Manabrew interoperability notice

This directory is Spellbench's own code. It lets a person play a Spellbench session through the Manabrew client
by acting as a room host on a Manabrew relay. It contains no code from the Manabrew project.

- The engine-to-client messages (StateUpdate with `gameView`, AgentPrompt and the prompt inputs and outputs,
  errors, log entries) follow "The Manabrew Protocol" documentation by the Manabrew contributors
  (https://docs.manabrew.app/protocol/), licensed CC-BY-4.0
  (https://creativecommons.org/licenses/by/4.0/). Field and type names are taken from that documentation; the
  code here is an independent implementation, not a copy of it.
- The relay messages (Authenticate, CreateRoom, JoinRoom, SetDeckSelection, SetReady, StartGame, EndGame,
  BroadcastState, StateUpdate) and the envelope that carries engine messages were read from the upstream
  repository https://github.com/witchesofthehill/manabrew at commit
  8c1d79da381e785faa8df063ce5e047f7ad6d4a2, for interoperability only.
- The Manabrew relay (`manabrew-server`) and client are separate programs licensed AGPL-3.0-or-later. Spellbench
  runs them as separate processes on the player's own machine; it does not link, vendor or redistribute them.
  The relay is unmodified. The launcher serves, by default, a client built on the player's machine from the pinned
  commit plus one local patch (a side panel that lists the engine's game-log messages, which the stock client
  receives but does not display); `-Stock` serves the unmodified build instead. The patch keeps their license
  headers, stays on that machine, and is not part of this repository or offered upstream.
- `cards.json` (rules text, costs and type lines of the nine training decks and the tokens they make) is built by
  `build_cards.py` from Oracle card data served by the Scryfall API (https://scryfall.com/docs/api), used under
  Scryfall's API guidelines: a descriptive User-Agent and Accept header, requests spaced 200 ms apart, replies kept
  rather than asked for again, no paid or paywalled use. The text of the cards is Wizards of the Coast's; Spellbench
  is not affiliated with Wizards of the Coast, Scryfall or the Manabrew project. Four legacy token entries
  (Goblin, Elf Warrior, Bird, Spirit) are written by hand.
- Mana and tap symbols: the client asks its own server for `/scryfall-symbols/<name>.svg`. `serve_client.py` answers
  from a folder on the player's machine, filling it on first use from https://svgs.scryfall.io/card-symbols/ (one
  request at a time, 100 ms apart, never again for a file already kept). The symbol files are not part of this
  repository. Card pictures are fetched by the client itself from Scryfall, as it does without Spellbench.
