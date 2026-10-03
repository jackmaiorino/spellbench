# Isolated XMage model backend

This backend prepares real neural inputs for the XMage game adapter. It does
not speak Spellbench's agent protocol or claim full-game qualification.
See [the coverage inventory](../../engines/xmage/BOTS.md) for unfinished work.

Fetch all public inputs as opaque, hash-verified files into an owned job root:

```powershell
uv run python python/tools/xmage_release_assets.py fetch --root D:/e-scratch/JOB --report D:/e-scratch/JOB/INPUTS.json
uv run python python/tools/xmage_release_assets.py archives --root D:/e-scratch/JOB --report D:/e-scratch/JOB/ARCHIVES.json
docker build --tag spellbench-xmage-models:local integrations/xmage-models
docker image inspect spellbench-xmage-models:local --format '{{.Id}}'
```

Use that observed immutable image ID, not the tag:

```powershell
uv run python python/tools/xmage_checkpoint_backend.py probe --root D:/e-scratch/JOB --checkpoint draftzero-exp1-gen33 --image sha256:IMAGE_ID --report D:/e-scratch/JOB/GEN33.json
```

Repeat the probe for gen0 and gen10. All three genuine public checkpoints have
passed loading, finite-output and repeated-inference checks. Receipts record
the input manifest hash, actual image, four read-only mounts, launch arguments,
package versions, encoding, head width, output hash and any failure. Failures
are retained. No checkpoint or upstream Python source is imported on the host.

`serve` uses the same confinement and pins. It emits a readiness line, then
accepts NDJSON requests with `id`, `features` and `encoding`. Each response
contains four raw policy heads and a scalar value. Features are mapped through
the checkpoint's saved dense vocabulary with the original deduplication and
unknown-feature handling. An input with no known features is refused. Legal
candidate mapping and the original search belong to the game adapter.

MageZero v0.2 source is wired as a separate architecture. A supplied weight
needs a pinned manifest entry, a deck ID and deck-association evidence before
it can launch. The loader requires the recorded wide hash range and strict
128-slot model shape. Its source contract passed using synthetic initialized
weights only. No actual pretrained MageZero checkpoint has been qualified;
complete game play remains unfinished.

For an author-supplied `.mz` export, stage the opaque file in an owned input
root and add its asset to an external copy of `releases.json`, then add that
asset ID to `inference_backends.magezero-v02.checkpoints`. Record these fields:

```json
{
  "id": "magezero-author-deck-version",
  "filename": "author-export.mz",
  "kind": "checkpoint",
  "transport": "local-file",
  "provenance": "Author and source of the supplied export",
  "bytes": 123,
  "sha256": "REPLACE_WITH_ACTUAL_FILE_SHA256",
  "checkpoint_format": "magezero-mz",
  "deck_id": "sha256:REPLACE_WITH_EXACT_DECK_FILE_SHA256",
  "deck_association_evidence": "Author confirmation associating this model with the pinned deck",
  "export_metadata": {"deck": "EXACT_EXPORT_DECK_NAME", "version": 1}
}
```

Replace all placeholders with observed values. Pass the external manifest with
`--manifest` when probing or serving. The bundle must contain exactly
`metadata.json` and `model.pt.gz`; its deck name and integer version must match
the manifest. Members are streamed inside the container without extraction,
and weights still use `torch.load(weights_only=True)`. The metadata's deck name
alone does not establish association with an exact deck list. Extra, duplicate,
linked, encrypted or oversized metadata entries are refused.

Raw `.pt.gz` and `.pt` inputs use `checkpoint_format` values `torch-gzip` and
`torch`. They require the same exact deck hash and association evidence but no
`export_metadata`. Public download assets still require an HTTPS source.
Local assets require recorded provenance and an already staged, hash-matching
file; the preparation tool never downloads or deserializes a local checkpoint.

The container is limited to one CPU, 3 GiB RAM, 64 processes and a 64 MiB
ephemeral temporary filesystem. It has no network, a read-only root filesystem,
no privileges and no host socket. Probe timeout cleanup removes only the
launcher's uniquely named container. Large evaluated workloads must still
pass the existing useful-throughput guard.
