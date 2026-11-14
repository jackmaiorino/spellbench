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
  runs them unmodified, as separate processes, on the player's own machine; it does not link, vendor or
  redistribute them.
- `cards.json` (rules text for the Pauper pool) is built by `build_cards.py` from the XMage card data file in our
  mage repository; token text is written by hand.
