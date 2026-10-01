# Inference through a network-less sandbox

The child-side adapter now supports `--broker-stdio`. It requests inference over the same stdin/stdout pipes used for v2 game decisions. It reads no provider key and opens no socket. A maintainer-owned `BrokerSession` holds the provider and forwards only the final v2 response to the arena.

This is the transport part of [#10](https://github.com/jackmaiorino/spellbench/issues/10). Container launch, OS confinement and cleanup remain owned by the submission isolation wrapper (sub-project D). **This library is not a verified sandbox wrapper. Do not set `${SPELLBENCH_SANDBOX}` to it or change the admission allowlist.** The local checks run a subprocess with a stripped environment, not a container. Docker's Linux engine is unavailable on the checked Windows host; its startup failed on a stale `dockerInference` socket, which could not be moved by native PowerShell. No container isolation claim is made.

## Integration contract

The isolation owner creates its confined child process and supplies a peer implementing `write_line(bytes)`, `read_line()`, `set_timeout(seconds)` and `close()`. Pass that peer and a host-owned provider to `BrokerSession`, then run `serve_broker`. The wrapper must keep provider credentials and the host log outside the child's mounts and environment, enforce its existing network-less launch, and tear down the container on error, timeout, EOF or arena termination. A host subprocess kill alone does not guarantee that Docker removed a container.

```python
from spellbench.llm.broker import BrokerSession, serve_broker
from spellbench.llm.provider import ChatCompletionsProvider

session = BrokerSession(
    confined_peer, ChatCompletionsProvider(provider_config),
    settings=provider_config.public_settings(),
    max_completion_tokens=provider_config.max_completion_tokens,
    log=host_log,
)
serve_broker(session)
```

The child command is `python -m spellbench.llm --broker-stdio --model MODEL`. Its model argument is descriptive; the broker's configured provider and returned model are authoritative and logged. Align child and broker settings in the roster. Child prompt code may be customized, but it receives only the seat-visible request that the arena already licensed to it.

## Capability and budgets

An internal inference request has exactly `broker`, `request_id`, `messages` and `timeout_ms`. The broker name is `spellbench-inference/v1`. Messages contain only text roles `system`, `user` or `assistant`; there are no tool calls, endpoint URLs, model overrides, generation-setting overrides or credentials in the request schema. The child cannot extend its clock, trigger inference outside an active choose request, ask twice for one decision or invoke inference for a forced choice.

The broker fixes the model, endpoint and inference settings. It enforces prompt-byte, per-game call/token and connection-lifetime call/token limits before issuing a single request. The host clock and broker timeout bound the whole child exchange, including inference and the final choice. Actual provider usage is checked afterwards, and the returned candidate must be offered in the current decision. An invalid request or uncertain provider failure poisons the connection; a new game ID cannot clear it. No repair request or fallback is issued.

Connection limits default to 1,024 attempts and 1,000,000 reported tokens. These are not an aggregate tournament dollar cap: the arena may start a fresh wrapper per game. [#11](https://github.com/jackmaiorino/spellbench/issues/11) still owns aggregate spending controls and qualification before paid measurement. Prompt-byte reservations have the same tokenizer limitations as the direct adapter.

The host log records fixed settings, prompt hashes, returned model, usage, latency and stable errors. `record_prompts=True` records full prompts outside the sandbox. Provider keys and raw provider errors are never forwarded to the child. The library makes no promise that customized submitted prompt code plays well.

## Before verified admission

Finish the D wrapper binding, then run an actual container check: no provider key or host secret in the child, external egress blocked, legitimate inference through the pipe succeeds, and timeout/crash/arena-kill cleanup leaves no container behind. Docker's [`none` network driver](https://docs.docker.com/engine/network/drivers/none/) creates only loopback; the [run reference](https://docs.docker.com/reference/cli/docker/container/run/) defines the confinement options. Merely constructing those flags is insufficient verification. The manifest's existing `verified-sandbox` classification is left unchanged.
