# CABT Decision Surface Audit

This document explains where the CABT bridge's decision space comes from and
why. The machine-readable version is `CabtDecisionSurfaceAudit.entries()` in
`mage.player.cabt`; the tests in `CabtDecisionSurfaceAuditTest` keep the two
in sync with XMage's actual APIs.

## 1. XMage does not expose one complete legal-decision enum

There is no single engine type that enumerates "all legal actions". Decisions
reach a player implementation through many independent callback methods, each
with its own shape (targets, modes, piles, amounts, mana, combat, triggers,
replacements).

## 2. The complete adapter surface is the union of three sources

- **Player callback methods** — `mage.players.Player` is the authoritative
  engine prompt interface: `priority`, `choose`, `chooseTarget`,
  `chooseTargetAmount`, `chooseMulligan`, `chooseUse`, `choosePile`,
  `playMana`, `announceX`, `getAmount`, `getMultiAmount`,
  `getMultiAmountWithIndividualConstraints`, `chooseReplacementEffect`,
  `chooseTriggeredAbility`, `chooseMode`, `selectAttackers`, `selectBlockers`,
  and the `declareAttacker`/`declareBlocker` commit APIs.
- **Priority playable-object APIs** — `getPlayable(Game, boolean)`,
  `getPlayableOptions(Ability, Game)`, `getPlayableObjects(Game, Zone)`,
  `getPlayableActivatedAbilities(MageObject, Zone, Game)`.
- **Client callback prompt methods** — `GameSessionPlayer.choosePile`,
  `chooseChoice`, `playMana`, `playXMana`, `getAmount`, `getMultiAmount`.
  In addition, `GameSessionPlayer.prepareGameView(...)` populates UI-visible
  priority playable objects via
  `gameView.setCanPlayObjects(priorityPlayer.getPlayableObjects(sourceGame, Zone.ALL))`
  — this is the existing XMage path for showing a human client what is
  playable while holding priority.

## 3. getPlayable/getPlayableObjects are only for priority playable actions

They enumerate what can be cast or activated while a player holds priority.
They are **not** the full action space, and treating them as such would
silently drop every other decision class.

## 4. Non-priority decisions come from their own Player callbacks

Target, mode, mana-payment, combat, replacement-ordering, and trigger-ordering
decisions each arrive through a dedicated `Player` callback listed above. Each
needs its own prompt-specific option builder in the bridge.

## 5. Arena/17Lands-style replay data confirms the state + prompt + response model

Arena-style logs are state/prompt/response based, not a small fixed action enum.
17Lands replay rows are useful telemetry, but they do not enumerate legal decisions.

17Lands replay data is telemetry, not a legal-action enumerator. This is why
the adapter's decision model is based on XMage prompt callbacks and option
builders, not on a static strategic action list.

## 6. Unknown actions fail closed

An action or prompt the bridge does not recognize must fail the audit and its
tests. There is deliberately no `UNKNOWN_PLAYABLE` (or similar) fallback enum
value anywhere in the project — a catch-all bucket would hide gaps in the
decision surface instead of surfacing them.

## Status legend

- `SURFACED` — already routed through `CabtBridgeController` as an
  option-index prompt.
- `AUTO_SELECTED` — a prompt family the bridge resolves automatically because
  exactly one legal outcome exists (whole-surface shortcuts; single-option
  shortcuts inside surfaced families stay `SURFACED`).
- `DELEGATED` — deliberately left to the inherited/engine implementation
  (commit APIs whose decision is made in another prompt).
- `FAIL_CLOSED` — a real decision not yet surfaced; the bridge override
  throws `CabtUnhandledDecisionException` rather than letting the inherited
  AI silently decide it. Needs a prompt-specific option builder before games
  exercising it are trusted.
- `REFERENCE_ONLY` — a query API or design note used when building option
  payloads, not itself a prompt.

## Coverage gate

Every `SURFACED`/`DELEGATED`/`FAIL_CLOSED` audit entry names its
implementation class and test class; `CabtPromptAudit` resolves both on the
classpath and `CabtPromptAuditTest` fails the suite when a surfaced prompt
lacks coverage. New prompt surfaces are added as audit entry +
implementation + tests, never one without the others.
