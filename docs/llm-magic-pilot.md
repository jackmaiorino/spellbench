# GPT-6 Luna full-game pilot

GPT-6 Luna completed two full 60-card Spellbench v2 Magic games through the maintainer's authorized ChatGPT-plan grant on October 1, 2026. Both ended naturally. The reference host checked all 768 decisions without a legality or protocol violation. This is engineering evidence, with no rated-entry or playing-strength claim.

| Mirror deck | Luna seat | Luna outcome | Host decisions checked | Luna legal choices | Model requests | Reported tokens | Game wall time |
|---|---|---|---:|---:|---:|---:|---:|
| Standard16-RG | p0 | Win, opponent life zero | 260 | 130 | 44 | 138,887 | 141.478 s |
| Standard16-UB | p1 | Loss, own life zero | 508 | 224 | 35 | 162,169 | 119.774 s |

The opponent was the reference heuristic bot. Format was `standard-2022-25-bo1`, seed `20261001`, reasoning effort `low`, and history one decision. Starting player was p0 in both games, so Luna played first then second. Forced choices bypassed inference: 86 in game 0 and 189 in game 1. Every non-forced Luna choice used a completed response from the exact requested model. All 79 response IDs were distinct; no model substitution or request retry occurred.

The complete pilot took 263.915 seconds including startup and cleanup. Usage was 299,394 input tokens and 1,662 output tokens, 301,056 total. There were zero failed requests and zero requests with unknown usage in this pilot. Request latency was 2.513 s median, 5.436 s nearest-rank p95, and 10.182 s maximum. The rounded shared weekly meter was 6 percent before and after; the credit balance was 62,500 both times. Those readings cannot establish incremental allowance use or a dollar price. Earlier transport-debugging requests and their unknown usage remain recorded in [the initial transport report](llm-subscription-pilot.md).

The run used the host implementation at `895ed9073b8c6b2ba0d4caf33229da06c0a3aae0`, a protected Spellbench profile separate from Codex credentials, and an explicit grant renewal before starting. The bot ran in the [confined Docker binding](llm-container.md). Both owned containers were removed, and the actual credential strings were absent from every run file. Six actual confinement/cleanup checks passed in Linux CI and on this Windows Docker Desktop runtime. The arena's admission labels and allowlist were not changed.

The pinned CI image archive has SHA-256 `f8346c5416d8199a5c75c01c495607130aef85f5dbeab042c166188e1cc48b9c`. Its CI image ID was `sha256:02a1ef3ff63ed51995675fd4dce0d51d472fcb61007fde36b92dfef343c5e6f5`; Docker Desktop imported it as `sha256:3d3be1ba7fdbc2a7d791749fb6fd8050e6cc849148762e3210a6c6291ac75eaa`. The archive and runtime layer identities match. The public package hash in the CI receipt is `1da39daff132972fc7daeb2c0769719d2854a39f377986b53738cf92560ba647`. Runtime image identity and import mapping are preserved with the receipts.

All 41 XMage jars matched the source build manifest before staging. Its SHA-256 is `7f06bfd1780fb9c482e619092acf10875d76c27ebcc8986cf1d612e871e40c4b`. Engine hello matched its declared rules and card-pool identities, and both catalogue decks passed validation. A fresh engine replay of game 0 matched all 263 responses, including hello, deck validation and terminal, in 13.205 seconds without model calls. The expected and replayed canonical JSON-lines output stores share SHA-256 `aa617d4570a2f866ff4e86525253c985140b98432dba4e7013777beb041c2d63`. This proves regeneration of the recorded engine path; it does not claim deterministic model outputs.

The source transcripts, usage journal, manifests, image import mapping, isolation receipts and replay stores are sealed under `E:/spellbench-llm-pilot-20261001/`. Binary inputs resolve by hash under `E:/pinned-binaries/`. The closure archive has a second local copy; [the retention record](llm-pilot-prune.json) lists its hash and recovery recipe. Bulk evidence is excluded from Git.

To run a new bounded pilot, first build or import the public image, prepare a private per-process XMage database copy, and supply its engine argv and manifest:

```text
uv run --no-sync python python/tools/llm_plan_magic_pilot.py --model gpt-6-luna --image sha256:LOCAL_IMAGE_ID --engine-command ENGINE_ARGV.json --engine-manifest BUILD-MANIFEST.json --out NEW_SSD_DIRECTORY
```

Use `python/tools/llm_pilot_replay.py --engine-command ENGINE_ARGV.json --transcript GAME.transcript.jsonl --out NEW_REPLAY_DIRECTORY` for a model-free engine replay. Every attempt uses a new directory and retains its failures. The pilot stops at two games, its fixed request/token/wall/log limits, or any non-natural ending. It is not a substantial-evaluation launcher; rated admission and representative serial/parallel throughput qualification remain separate work under #11.
