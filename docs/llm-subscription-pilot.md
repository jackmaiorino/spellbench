# Luna subscription integration check

On 2026-10-01 Jack approved Spellbench's browser consent. The direct plan API accepted `gpt-6-luna` and returned that model, despite its account catalog listing `gpt-5.6-luna` and omitting GPT-6 Luna. No model substitution was made. Catalog omission did not establish lack of inference access.

The live transport exposed two differences from the initial offline fixtures: SSE was labeled `text/plain`, and the completed response left its output array empty. The adapter now validates finalized output-item snapshots against the matching completed response. It never chooses from deltas or an incomplete/failed stream. Native certificate validation also resolved the Windows Python/OpenSSL expired-chain failure without a TLS bypass.

The v2 host drove the actual agent subprocess and a scoring test engine to a terminal result at commit `7e4a4a8`. This is a protocol integration fixture, not a complete Magic rules game or evidence of playing strength. No container was launched.

| Check | Observed |
|---|---|
| Model returned | `gpt-6-luna` on both inference calls |
| Checked decisions | 4, with 2 Luna calls and 2 scripted opponent choices |
| Terminal classification | `natural`, scoring fixture completed |
| Reported usage | 1,845 input + 30 output = 1,875 tokens |
| Inference latency | 2,320 ms and 1,791 ms |
| Total fixture runtime | 4,390 ms |
| Game digest | `sha256:2261c3b44b11a1dd2084deb368cd7d091c7e19051473dec517853e0e7efd034d` |
| Log SHA-256 | `84745c0265dc3a2fb6e8088b639d02fd08e6611babf5f67b3946d8662037e5af` |

Receipts and failed attempts remain locally under ignored `out/luna-subscription-pilot/`. Seven Responses requests were made during compatibility debugging and the fixture game. Four supplied recorded usage totaling 4,453 input and 60 output tokens; usage for three earlier requests remains unknown. Those are partial reported totals, not the full allowance cost. The shared account meter read 6% weekly use before and after, at insufficient resolution to measure this check's allowance consumption. No dollar cost or live determinism claim follows from these observations.

To repeat the small fixture from this checkout, after sign-in:

```text
uv sync --locked --extra test --extra chatgpt
uv run --no-sync python python/tools/llm_plan_fixture_smoke.py --model gpt-6-luna --out out/llm-plan-fixture-NEW
```

Use a new output directory to preserve previous attempts. The command makes at most two inference requests, records seeds/input hashes/log hash and respects the host clock. Its 1,024-output-token setting is checked after usage; the plan preview has no hard server-side output cap. Tokens must remain valid for the decision deadline. There are no retries, repair calls or model fallback.

Remaining for #11: a real v2 Magic engine run, aggregate usage authorization and qualified throughput before substantial measurement. #10 retains actual isolation-wrapper binding, blocked-egress and teardown checks. The 246 focused local checks pass; full Linux/Windows CI passed at `65d0357`, with final parser changes requiring refreshed CI.
