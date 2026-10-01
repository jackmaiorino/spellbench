# Run an LLM bot

This adapter requires the **v2 reference stack and a v2 engine observation**. It is not compatible with the published v1 board. Chat Completions and optional ChatGPT-plan Responses transports are tested against local fixtures. Live provider compatibility and rated measurement remain tracked in [#6](https://github.com/jackmaiorino/spellbench/issues/6). The [stdio broker](llm-broker.md) supplies inference to an isolation wrapper; actual container admission remains unverified.

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

## ChatGPT subscription usage

An eligible ChatGPT account can explicitly grant Spellbench permission to use its plan through [Sign in with ChatGPT](https://developers.openai.com/siwc/token-sharing-open-source/sign-in). Install the optional dependency and sign in outside a game:

```text
uv sync --locked --extra chatgpt
uv run --no-sync python -m spellbench.llm.login
uv run --no-sync python -m spellbench.llm --provider chatgpt-plan --model gpt-6-luna --reasoning-effort low --max-calls-per-game 3 --log-dir out/llm
```

The sign-in command opens a browser to review Spellbench's permission request, validates the loopback callback with state and PKCE, verifies the OpenAI ID token's signature, issuer, audience, expiry and nonce, and checks the granted plan-usage scope. It makes no model requests. Registration and credentials belong to Spellbench; existing Codex credentials are not read or copied. Default credentials are under `%LOCALAPPDATA%/Spellbench/` on Windows or `$XDG_CONFIG_HOME/spellbench/` (otherwise `~/.config/spellbench/`) on Unix. Windows uses current-user DPAPI encryption; Unix uses atomic owner-only files. `--credentials PATH` selects a separate account profile on both commands. Do not place credentials in a game log, repository or child sandbox. Reauthorization must match the selected profile's verified identity and issued client ID.

This first version requires another sign-in when the access token expires, between games. It stores the refresh token securely but does not refresh automatically or retry a request. Inference rejects credentials that could expire within the decision deadline. JWT validation and native TLS validation require the `chatgpt` extra; other transports retain their dependency-free runtime.

The plan provider sends only the adapter's explicit developer/user prompt and bounded game history to `https://api.openai.com/v1/responses`. It uses `store=false`, streaming and strict structured output, without tools or a persistent conversation. A choice is accepted only from `response.completed`; streamed deltas, late failures and interrupted streams never select an action. TLS validation stays enabled, proxies and redirects are disabled, and a failed exchange stops further calls on that provider instance. Errors do not reveal tokens or remote bodies. The model must be available to the signed-in account; the example is a candidate for a pilot, not a verified entitlement or strength claim. See [models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference).

Plan inference and sign-in use a per-client [Truststore TLS context](https://truststore.readthedocs.io/en/latest/) to validate certificates through the system trust store. This avoids the Python/OpenSSL expired-chain failure observed on the Windows development host, where native validation succeeds. Hostname, chain and expiry checks remain enabled; SSL behavior is not changed globally. Tests verify that untrusted certificates, wrong hostnames and expired certificates prevent HTTP requests from reaching the local test server. Auth discovery and public JWKS retrieval have also succeeded with verified TLS on that host; this does not establish account entitlement or inference compatibility.

The [plan preview does not support `max_output_tokens`](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations). For this transport `--max-completion-tokens` is an acceptance limit checked **after usage has occurred**, including reasoning tokens. An overrun records known usage and produces an error. Prompt-byte reservations, call limits and deadlines reduce exposure but do not impose a hard subscription allowance or dollar cap. Use a short correctness pilot first and measure actual consumption before authorizing a larger run. The provider defaults to low reasoning effort and rejects temperature, alternate endpoints, JSON-object format and local-key overrides. Subscription usage and API-key billing are separate access routes.

## Inputs and settings

The prompt carries the current neutral observation, decision context, group, all legal candidate semantics/descriptions, the agent's own deck and its last eight own decisions. It excludes native extensions, raw envelopes, agent seeds, clocks and engine metadata. Opponent decklists are not used by this first adapter. The host remains responsible for validating its observation. The adapter additionally rejects a visible opponent hand, mismatched viewer or missing own hand.

Optional `--card-catalog PATH` reads a pinned UTF-8 JSON file:

```json
{"schema":"spellbench-card-text/v1","cards":{"Lightning Bolt":"Lightning Bolt deals 3 damage to any target."}}
```

Only text for names in the prompt is sent. Missing catalog entries are listed explicitly. Without a catalog, the model relies on its prior card knowledge; the adapter does not download card text. The catalog file hash is logged. Printed text does not replace current engine characteristics or implement card rules.

Defaults: 20-second request ceiling, 256 API attempts per game, 250,000 reported tokens per game, 64,000 prompt bytes, and 1,024 completion tokens including any provider reasoning tokens. Configure these with `--timeout-ms`, `--max-calls-per-game`, `--max-tokens-per-game`, `--max-prompt-bytes`, `--max-completion-tokens` and `--history-decisions`. The host's remaining clock and per-decision limit can shorten the timeout. No candidate list is silently truncated.

For Chat Completions, `--temperature` and `--reasoning-effort` are omitted unless explicitly supplied because model support varies. Strict JSON schema is the default. Set `--response-format json_object` for a compatible server that lacks schema support. There is no automatic format or model fallback. The request uses `max_completion_tokens`; endpoints supporting only a different field need a separate adapter. Request format follows [official Chat Completions documentation](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) and the [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs).

## Results and limits

Single-candidate decisions are answered without a model call. All other decisions require one API response containing exactly an integer candidate ID from the offered list. Refusals, invalid outputs, incomplete responses, API errors and exhausted budgets produce an agent error. The arena applies its existing adjudication. No heuristic fallback or repair call masks these failures. A failed game cannot issue more API calls; a new game resets budgets and history.

Logs are unique per agent process under `out/llm` by default, avoiding worker collisions. They record configuration/prompt/catalog hashes, requested and returned model, response ID/fingerprint when supplied, tokens, latency, forced choices and failures. `--record-prompts` also stores actual player-visible prompts locally. It can produce large private files; keep these under an ignored output directory. Credentials and raw provider error bodies are never logged. Logs are local diagnostics, not new fields in the arena's publication ledger.

Token reservations use prompt UTF-8 bytes plus the requested completion limit before each call. Actual provider usage is then checked. This is conservative for standard byte-tokenized models and is not an exact tokenizer or dollar cap. Missing usage or any uncertain provider failure stops that game. A timed-out remote call may still complete and incur a charge; no retry is made. Per-game limits reset with every game, so an entire tournament needs a separate authorized aggregate spend cap and launcher qualification before live measurement. API model aliases can drift; record the returned model and use a snapshot identifier when available. Bit-identical live inference is not promised.
