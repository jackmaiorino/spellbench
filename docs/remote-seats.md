# Remote seats

A remote seat lets a bot play on a Spellbench board from its author's own machine. Use it for a bot that cannot run on the host within the board's clock, or that needs hardware or software the host does not have. The engine, the run secret and the live validator stay on the host. The bot still sees only its own seat's protocol v2 messages, the same ones a local bot would get.

A remote seat runs none of the isolation of a verified sandbox (spec 11.7). The author's process can keep state across games, and its timing and hardware are outside the host's control. A run with any remote seat is therefore self-reported, and its board page says so.

## How it works

`python/spellbench/remote_seat.py` has two halves, and every game uses one TLS connection between them:

- **`serve`** runs on the author's machine. It listens on a port, checks each connection's token, starts a fresh bot process for that game, and copies lines both ways until either side closes.
- **`relay`** runs on the host as the seat's agent process. The host starts it like any subprocess bot, a fresh process per game. It dials the author's endpoint and checks the server certificate against a pinned SHA-256 before it sends the token. After that it copies the seat's NDJSON lines unchanged in both directions.

Only the host dials out, so the host never accepts inbound connections. The author's endpoint must be reachable from the host.

Before any protocol line, each side sends one handshake line. The relay sends `{"remote_seat": "spellbench-remote-seat/1", "token": ...}`. The server answers `{"remote_seat": "spellbench-remote-seat/1", "ok": true}`. If it refuses, it answers `ok: false` with `error` set to `unauthorized`, `busy` or `bot did not start`, then closes. From then on, the connection carries exactly what the bot's stdin and stdout would carry locally.

## Clocks and failures

The host times the relay process, so network latency is charged to the seat's clock. Connecting and the TLS handshake count against `startup_ms`. If the endpoint is unreachable, refuses the seat, or drops mid-game, the relay exits. The host then records the same forfeit a crashed local bot gets (`transport_error`), and these availability losses count. There is no reconnect within a game.

## For bot authors

The module needs only the Python standard library. You can install spellbench, or copy the single file `remote_seat.py`.

1. Make a certificate. Self-signed is fine, because the host pins its fingerprint:
   `openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -keyout key.pem -out cert.pem -days 365 -subj /CN=spellbench-seat`
2. Make a token and keep it private: `python -m spellbench.remote_seat token > seat.token`
3. Print the certificate's pin: `python -m spellbench.remote_seat fingerprint cert.pem`
4. Serve your bot. The command after `--` is any protocol v2 agent that speaks NDJSON on stdin and stdout:
   `python -m spellbench.remote_seat serve --listen 0.0.0.0:7443 --cert cert.pem --key key.pem --token-file seat.token --max-games 4 -- python my_bot.py`
5. Send the maintainer the endpoint (`host:port`) and the pin. Send the token over a private channel. Set `--max-games` at least as high as the board's worker count, because games past it are refused as busy, and a refusal is a forfeit.

Test locally first with `spellbench run` against the builtins, using the relay as your bot's command, before asking for a rated entry.

## For the operator

A bot entry is a remote seat when its command starts with exactly:

```json
["${SPELLBENCH_REMOTE_SEAT}", "-m", "spellbench.remote_seat", "relay",
 "--endpoint", "bots.example.org:7443", "--server-sha256", "<pin>", "--token-file", "${SEAT_TOKEN_EXAMPLE}"]
```

Set `SPELLBENCH_REMOTE_SEAT` to the arena's own Python, in the environment or in `benchmarks/local.json`. Point each seat's token-file placeholder at a file outside Git. The manifest records the entry as `remote-self-reported`, and the isolation rule admits it whatever its owner, because nothing of the author's runs on the host. A command that starts with the placeholder but is not followed by the relay is an ordinary unsandboxed subprocess. Unless its owner is on the allowlist, it is refused.

The published config keeps the endpoint and the pin, never the token. Before a rated run, qualify the seat at the board's worker count. Treat its measured latency as part of the entry, not of the host.
