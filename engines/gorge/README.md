# gorge adapter

The gorge rules engine as a Spellbench Protocol v2 engine (environment role over stdio), with eight ordinary policy modes and four public-history search modes wrapped as v2 agents. Protocol `spellbench/v2`, `protocol_minor` 0. The adapter is a separate Go module pinned to gorge commit `26257e0eda1779d739a07e835c6500b9c4dabc62`, resolved locally; gorge's tree is read-only. Complete inventory and validation status are in `docs/gorge-roster-20261002.json`.

## Build

```sh
source scripts/env.sh && sh scripts/setup-dev.sh && go build -o bin/ ./cmd/...
```

`scripts/env.sh` selects the local Go 1.27.1 toolchain (`GOTOOLCHAIN=local`, caches on D:), sets `GORGE_SRC` and `GORGE_CARDS`, and enables `GOFLAGS=-overlay=.../go-overlay.json`. CI remains pinned to Go 1.25.8. `setup-dev.sh` invokes Python 3 to verify the source revision and write the git-ignored `go.work`, generated source copies and overlay manifest. The nested `strategies` module accesses gorge's internal search packages; overlays add public collector bindings, actor-only replay boundaries, identity retirement and declared mulligan setup without editing the upstream checkout. The card corpus is fetched with gorge's `forgec fetch` and is never shipped (Forge scripts are GPL-3.0); binaries load it at run time through `-corpus` or `GORGE_CARDS`.

Rated preparation uses `spellbench-gorge-corpus -corpus "$GORGE_CARDS" -out PATH` in a registered job artifact tree. It verifies actual card script bytes against the source pin, records token script bytes, recompiles without using the development cache and prints a small receipt with the output SHA-256. Pass that file and digest with `-registry PATH -registry-sha256 SHA` to the engine and search agents. They load that exact file without recompilation or cache pruning. The existing reference launcher hashes, pins and checks regular files named in commands; no shared host change is needed. Registry IR stays outside Git and binaries. Preserve the single frozen file rather than assuming a second compilation writes identical bytes.

## CI

The module's `go.sum` holds only the `golang.org/x/text` hashes; the pinned gorge module resolves through the git-ignored `go.work` replace, builds use no network, and `scripts/env.sh` holds this machine's D: paths (G1-6, G2-31). The CI job (`.github/workflows/gorge.yml`, on changes under `engines/gorge/`):

1. clones gorge at the pin with `core.autocrlf=true` and exports `GORGE_SRC` (gorge's `CompilerFingerprint` hashes the source bytes, and the pinned value comes from the qualified Windows checkout; an LF checkout reports `59486de15e72099cf8b90914881a89c0` and is refused);
2. runs `forgec fetch -ref 95f04e8a04c8925fa97cb226fc3341cabcc90a53` into `GORGE_CARDS` and exports it;
3. runs `sh scripts/setup-dev.sh` and enables the generated overlay;
4. runs vet, affected policy/payment checks and the nested public-search tests;
5. runs `go test -timeout 60m ./...` (the mini-host, agent and ordinary qualification packages run past `go test`'s 10-minute default).

Tests fail, never skip, when `GORGE_CARDS` is unset.

## Declared profile (`hello_ok`)

- `formats ["pauper-bo1"]`, `deck_sources ["catalog"]`: the five catalog decks Wildfire, Rally, Spy, Burn and CawGates (`internal/catalog`).
- `rules_supported {"mulligan": ["london", "none"], "starting_player": ["host_assigned"]}`.
- Observation flags (`observe.Flags`): 13 declared, true only for `pending_triggers` and `keywords`.
- `engine_defaults {"trigger_order": null, "replacement_order": null, "combat_damage_assignment": "engine_order", "mana_payment": null}`.
- `rewind` false, `fairness {"noninterference_probe": false}`.
- `extensions [{"name": "x_gorge_view_v1", "native_ids": false}]`.
- `decision_kinds` (`server.DecisionKinds`): the 24 kinds `pass`, `play_land`, `cast_spell`, `activate_mana_ability`, `activate_ability`, `special_action`, `choose_target`, `finish_target_selection`, `choose_cost_target`, `choose_spell_mode`, `choose_color`, `choose_number`, `choose_boolean`, `choose_name`, `select_object`, `finish_selection`, `optional_cost`, `optional_cast`, `mulligan`, `order_pick`, `arrange_card`, `choose_replacement`, `declare_attack`, `declare_block`.

## Engine procedures and limits

- Combat damage assignment is declared `engine_order` (spec 7.6): gorge's blocker order, lethal damage to each blocker, the rest to the last blocker or to the defender with trample; no `distribute` is posed, and `distribute` is not one of the 24 kinds. gorge measures lethal as the blocker's toughness (1 against deathtouch), without subtracting damage already marked. The other engine defaults are null.
- The default engine maps manual mana choices. With `-auto-pay`, it additionally offers the native planner's atomic normal-cast witnesses. Triggered costs still offer interactive mana choices, so `mana_payment` remains null. The benchmark uses this mode. Every selected atomic cast commits the original offered witness. An existing pool-only cast retains its ordinary intent, with the auto-pay agent's native intent and explicit translation recorded separately. Hybrid-pip allocation from floating mana is engine-internal: the engine answers with gorge's first offered option (Decision 3).
- Unless costs can be paid only from floating mana (no activation during the unless ask), so `optional_cost` offers pay:true only when the floating pool already covers the cost, with no activation candidates (Decision 2).
- `known_cards` is false and there is no text channel: every `display_text`, `context.text`, stack `text` and pending-trigger `label` is null.
- Only `host_assigned` starting players.
- Retransmission: the engine caches every response since the last accepted reset, so an identical older request of the same game gets its cached response; a request id from an earlier game is not recognized.
- Phased-out permanents are omitted (gorge's view treats them as absent).
- `ability_index`: a non-mana ability counts the face's non-mana abilities in Oracle order. A mana ability takes gorge's stage-1 numbering of the source's available mana abilities, which is Oracle order when all are available; a source with one available ability reads 0.
- Changeling is a known gap: subtypes show gorge's derived types (Masked Vandal reads `shapeshifter`), not every creature type.
- Cast modes that fail closed as `unmapped_decision`: `optionalcost`, `multikicked`, `replicated`, `squadded`, `warped`, `warp_recast`, `mayhem`, `harmonize`, `retrace`, `jumpstart`, `aftermath`, `adventure_recast`, `room_alt`, `defeat_cast`, and the special actions `foretell` and `suspend`. An Omen face (Roost Seek) is cast with method `other`, which the vocabulary offers for it.
- A mana payment window that does not lead to a trigger-cost ask halts the game `engine_contract_failure:unmapped_decision`: a cast payment window (gorge poses one when a cost grows after announcement) or an `unless_mana` window. Bot play never reaches one; another agent can.
- Where gorge fixes a pile-B order (an arrange ask that is not Restable), each order pick offers one card. A `dig_bottom` ask with no take ask before it is an arrangement whose partitions are all `bottom`.

## `x_gorge_view_v1`

The extension payload carries `version`, `native_index`, `view` (gorge's own seat view), `decision` (gorge's native decision), `policy_facts`, `followups` (the folded follow-up decisions, by payload key) and `ops` (`internal/xview`). Ids are re-keyed to per-seat non-native integers, so `native_ids` is false; the Extender keeps each seat's last native-to-payload renumbering, by native key, for the qualification audit only. Hidden, absent and zero references are 0, option groups are relabelled, and the policy facts restore the server-side fields gorge's bot reads, including the card views' mana production flags. In auto-pay mode, every payment action and witness is reissued using these public incarnations and the seat-local decision index; native digests and source-zone event counters are removed. A hidden payment source refuses the payload.

The wrapped bots see per-seat ids and name-sorted hidden options, so their games are not byte-identical to native gorge games; that is by design (Decision 6). Parity means the adapter commits exactly the intent, follow-up answers included, the bot chose (Task 28b).

## `x_gorge_search_v1`

The engine's explicit `-search` flag adds actor-only public history and bindings from the current view IDs to observer-local history IDs. Search agents require both extensions and load static card definitions with `-corpus` or `GORGE_CARDS`. All four modes keep shipped sampling and rollout settings; the redeal modes reconstruct a fallback root from public observations when native replay starves. Their source adaptations, bounded parity evidence and remaining qualification work are documented in `docs/gorge-search-bridge-20261002.md`. The profile conservatively declares `native_ids:true` for this extension. It must have the required published identity audit before rated use.

## Benchmark: `pauper-gorge`

`benchmarks/pauper-gorge/benchmark.json` (schema `spellbench-benchmark/v2`): the five catalog decks, 4 seat-swapped pairs per matchup/deck, both gorge extensions, and fourteen entrants: `uniform` (the rating anchor), `heuristic`, and all twelve gorge modes. The search modes are `search`, `search-mana`, `search-redeal`, and `search-mana-redeal`; the other modes are `bot`, `lethal-pressure`, `ar8`, `blocks`, `explore`, `legacy`, `bot-auto-pay`, and `lethal-pressure-auto-pay`. The engine command enables `-auto-pay` and `-search` and names `${GORGE_REGISTRY}` and `${GORGE_REGISTRY_SHA256}`. This remains a draft 3,640-game full round robin. The complete pinned inventory, aliases, qualification and publication status are in `docs/gorge-roster-20261002.json`.

The adapter uses the upstream constructors and native legacy PCG seed derivation. The embedded default `cast-profile` equals `DefaultCastWeights`, so it uses the `gorge-bot` identity. Unknown or unfinished policies are refused. Native policy errors produce an agent error instead of silently substituting a fallback policy. The bounded public checkpoint search is recorded in `docs/gorge-public-model-search-20261002.json`; no compatible PolicyNet weights were recovered.

`spellbench-gorge-agent -audit-dir PATH` (or `GORGE_AGENT_AUDIT_DIR`) writes one aggregate policy receipt after stdin closes. It records the public game/seat labels, native mapping counts and search coverage, sampled/redealt worlds, rollout work and reconstruction refusals. It contains no observations, intents or sampled game states and adds no game-wire fields. The subprocess and `gorgequal` use the same coverage fold. Qualification joins these receipts to reference-host outcomes before claiming that a search mode ran.

The loader fixes the information rules, so the file states none: opponent decklist visible, mulligan `auto` (london where the engine supports it; gorge declares `london` and `none`, so `pauper-gorge` plays london per spec 12.2 and Decision 4), host-assigned starting player with seat p0, and no probe. Cross-engine note: `pauper-kernel` plays mulligan `none`, so the comparison is not like for like.

Differences from the plan's draft, all forced by P2's loader (Task 30 reconciles any remaining difference):

- no `rules` block: unknown fields are errors, and the rules above are benchmark-fixed;
- no `engine.timeout_ms`: a v1 field, carried by `time_control.engine_step_ms`;
- `stats_seed` is required and was not in the draft; this file uses 20261002;
- `extensions` is a top-level field, not a rules field.

`internal/server/benchmark_test.go` pins the file against `catalog.Decks`, `server.DecisionKinds` and `observe.Flags`, so a profile drift fails loudly.

## Qualification and goldens

- Golden transcripts (Task 27): `go test ./internal/server/ -run Golden` replays `testdata/goldens/` byte-exact and recomputes the Section 11.8 digests; `-update` regenerates the files. Scenarios cover `hello`, the five decks' first decisions, a uniform Burn game, every reachable error code, and the arrangement, attack-declaration, order-pick and mana-payment groups. Every scenario resets without `x_gorge_view_v1`, whose payload carries gorge cost strings compiled from Forge scripts, which this module never ships.
- Qualification (Tasks 28a and 28b): `gorgequal -games N -out report.json` (`-resample K`, `-workers W`, `-audit` default true, `-policies all` or an explicit recorded subset). Every game is played twice from the same run secret, audited and plain, and the digests must match; the report counts validator violations, resample failures, leak-scan hits, inconsistent candidates, parity mismatches including full payment witnesses, and forced or fallback mapping answers (gated per policy and deck under 1%). Selected search modes must cover a decision on each deck; their sampling and rollout coverage and delegation reasons are recorded separately. Halts, truncations and agent errors fail qualification. Throughput counts completed natural games. Substantial qualification and rated runs require the supported reference-host throughput guard under `COMPUTE-POLICY.md`; this diagnostic executable does not enforce that guard by itself.
