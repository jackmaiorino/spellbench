# Jack original priority fidelity

The current Java priority pipe qualifies feature reconstruction and paired-network inference. It does not implement the original player's priority policy. Preserve this distinction when assembling the complete adapter.

The pinned private April callback is `ComputerPlayerRL.java`, SHA-256 `b45257a66fc3914506fca4dd83461b6c8853d129b3e1f38b2d3aeba6137bd0c6`, at revision `750b3ff88c98f00a0d3218a54c16198b69b8a24c`. Private source bytes remain outside public Git.

| Behavior | Original April player | Current feature pipe |
| --- | --- | --- |
| Options | Original playable order, ability-text deduplication, separate mana sources, activation/alternative-cost validation, pass first | Received public candidate order and mapped features |
| Slots | First 64 original options | Refuses more than 64 public options |
| Phases | Acts in both main phases; acts then passes in attacker/blocker priority; passes directly in the other listed phases | Encodes a received priority root without implementing this dispatch |
| Single option | Returns directly, consuming no model or chooser work | Produces features; no original action-policy session exists |
| Mana | Individual mana abilities can enter priority selection | `SeatPlayer.priority` excludes activated-mana and special-mana-payment abilities under engine autopay |

Source locations are April `priorityPlay` at lines 5199-5254, `calculateRLAction` at 6050-6244, `getPlayableForCurrentState` at 504-532, and `validatePlayableAbility` at 664-692. The public comparison is `JackEncoder.encode` and `SeatPlayer.priority` in the current source tree. The engine overlay's priority source is unchanged from reviewed revision `004913a4fd8e2455f8dfcbcd73a15c568a56bcc2`.

The five paired checkpoints' strict loading, finite inference and existing feature checks remain valid within their tested scope. They do not prove original candidate order, phase behavior, activation filtering, mana choices or completed games.

The complete adapter must implement and qualify those original behaviors. A changed public-option or automatic-mana policy must receive a distinct identity and cannot count as the requested original player. Preserve the existing frozen component recipes and results while implementing the missing policy.
