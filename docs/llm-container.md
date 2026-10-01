# LLM container binding

This is a maintainer integration of the [host-owned inference broker](llm-broker.md), tracked in #10. The arena's admission allowlist and isolation labels remain under the existing review path. The actual container checks are in the `LLM container isolation` workflow; local transport tests are not confinement evidence.

`python/tools/llm_container_image.py --out NEW_MANIFEST.json` snapshots public package `.py` files into a temporary build context. It copies no repository metadata, credentials, logs or host data. The base image is pinned by registry digest. The resulting local image ID, package hash, Dockerfile hash and Git commit are recorded. Runtime accepts that immutable image ID and never pulls an image.

`DockerPeer` supplies the existing `BrokerSession` peer interface. It runs a private network namespace, read-only image, no host mounts, a bounded tmpfs, 512 MiB RAM, one CPU and 64 processes. A trusted PID 1 needs only SETUID/SETGID to start the bot as UID/GID 65534; the bot has zero effective capabilities and inherits `no-new-privileges`. The supervisor is not dumpable, and the bot cannot reopen its root-owned controller pipes. Provider credentials stay in the host-owned provider, and the bot's environment is an explicit public allowlist.

`BrokerPeer(session)` binds the session to the reference `AgentProcess`; its host deadline bounds the child exchange and inference. Inject that `AgentProcess` through `SubprocessDriver.agent_factory` to retain the reference hello, bot identity, choice and clock checks. No alternate arena driver or relaxed candidate validation is used.

The supervisor forwards only protocol payloads to the bot. Host heartbeats renew a 30-second lease by default, including while inference waits outside the container. A bot cannot send its own heartbeat to that input channel. EOF, child exit or lease expiration ends PID 1 and all namespace descendants. Ordinary close additionally force-removes the unique owned container. The lease covers hard host termination, for which a Python `finally` block cannot guarantee cleanup.

The CI checks use an actual built image and runtime: host-file/environment/controller access denied, host-listener and external egress blocked, read-only root, zero child capabilities, a complete fixture game with HTTP inference only on the host, and cleanup after close, crash, broker timeout, lost heartbeats and a killed host with child descendants. The image and small receipts are retained as a CI artifact. None of these checks calls a subscription model or estimates playing strength.

Jack's PC currently has an active research quiet window, and HaleysPC has no Docker/Linux runtime. CI runtime evidence does not by itself establish a live Luna Magic pilot on either machine. That pilot remains required by the active goal.
