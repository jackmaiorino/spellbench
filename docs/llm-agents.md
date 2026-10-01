# Run an LLM bot

This adapter requires the **v2 reference stack and a v2 engine observation**. It is not compatible with the published v1 board. The first implementation is tested against a local mock endpoint; a live provider, rated run and sandbox inference broker are separate tracked work in [#6](https://github.com/jackmaiorino/spellbench/issues/6).

Run from an installed Spellbench v2 checkout:

```text
uv run python -m spellbench.llm --model YOUR_MODEL --log-dir out/llm
```

Set the provider key in `OPENAI_API_KEY` through your local environment. Never put it in a command, tournament config or committed file. `--api-key-env` selects a different variable name. The default endpoint is `https://api.openai.com/v1`; `--base-url` selects another Chat Completions endpoint. HTTP is accepted only on loopback. Local servers can use `--allow-no-api-key`. This command serves stdin/stdout; use it as the command of a v2 subprocess bot, replacing the model placeholder with an explicit identifier.

```json
["python", "-m", "spellbench.llm", "--model", "YOUR_MODEL", "--log-dir", "out/llm"]
```

The bot reports name `llm-YOUR_MODEL` and version `0.1.0`; use those values in the v2 roster, whose driver checks the handshake identity. Varying inference settings must be reflected in the recorded command and run metadata.

Do not change the arena's submission isolation policy to run this command. Direct API access is for maintainer-authored trusted bots or local development. Submitted bots remain subject to the network-less sandbox; [#10](https://github.com/jackmaiorino/spellbench/issues/10) owns the controlled inference transport.

## Inputs and settings

The prompt carries the current neutral observation, decision context, group, all legal candidate semantics/descriptions, the agent's own deck and its last eight own decisions. It excludes native extensions, raw envelopes, agent seeds, clocks and engine metadata. Opponent decklists are not used by this first adapter. The host remains responsible for validating its observation. The adapter additionally rejects a visible opponent hand, mismatched viewer or missing own hand.

Optional `--card-catalog PATH` reads a pinned UTF-8 JSON file:

```json
{"schema":"spellbench-card-text/v1","cards":{"Lightning Bolt":"Lightning Bolt deals 3 damage to any target."}}
```

Only text for names in the prompt is sent. Missing catalog entries are listed explicitly. Without a catalog, the model relies on its prior card knowledge; the adapter does not download card text. The catalog file hash is logged. Printed text does not replace current engine characteristics or implement card rules.

Defaults: 20-second request ceiling, 256 API attempts per game, 250,000 reported tokens per game, 64,000 prompt bytes, and 1,024 completion tokens including any provider reasoning tokens. Configure these with `--timeout-ms`, `--max-calls-per-game`, `--max-tokens-per-game`, `--max-prompt-bytes`, `--max-completion-tokens` and `--history-decisions`. The host's remaining clock and per-decision limit can shorten the timeout. No candidate list is silently truncated.

`--temperature` and `--reasoning-effort` are omitted unless explicitly supplied because model support varies. Strict JSON schema is the default. Set `--response-format json_object` for a compatible server that lacks schema support. There is no automatic format or model fallback. The request uses `max_completion_tokens`; endpoints supporting only a different field need a separate adapter. Request format follows [official Chat Completions documentation](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) and the [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs).

## Results and limits

Single-candidate decisions are answered without a model call. All other decisions require one API response containing exactly an integer candidate ID from the offered list. Refusals, invalid outputs, incomplete responses, API errors and exhausted budgets produce an agent error. The arena applies its existing adjudication. No heuristic fallback or repair call masks these failures. A failed game cannot issue more API calls; a new game resets budgets and history.

Logs are unique per agent process under `out/llm` by default, avoiding worker collisions. They record configuration/prompt/catalog hashes, requested and returned model, response ID/fingerprint when supplied, tokens, latency, forced choices and failures. `--record-prompts` also stores actual player-visible prompts locally. It can produce large private files; keep these under an ignored output directory. Credentials and raw provider error bodies are never logged. Logs are local diagnostics, not new fields in the arena's publication ledger.

Token reservations use prompt UTF-8 bytes plus the requested completion limit before each call. Actual provider usage is then checked. This is conservative for standard byte-tokenized models and is not an exact tokenizer or dollar cap. Missing usage or any uncertain provider failure stops that game. A timed-out remote call may still complete and incur a charge; no retry is made. Per-game limits reset with every game, so an entire tournament needs a separate authorized aggregate spend cap and launcher qualification before live measurement. API model aliases can drift; record the returned model and use a snapshot identifier when available. Bit-identical live inference is not promised.
