# DraftZero decision adapter slices

This is the tested connection from permitted XMage observations to Exp1's
feature hash and legal priority, target and binary policy slots. It is not a
complete agent. The neural connector selects directly from these trained
heads; its declared variant does not run the original MCTS search.

The source staging tool verifies the pinned public Java encoder files before
making explicit compatibility edits for the reviewed base engine. The staged
source hashes and every rewrite are recorded. Card sorting, entity names and
permanent ordering use the public fork's rules. Optional debug pairs use a
small local value type instead of JavaFX. Micro-decision history is empty and
the activation-in-progress flag is false at these slices. Soulbond
pairs and unsupported reconstructed worlds are refused.

Build with the pinned JDK 23.0.1 and reviewed engine inputs:

```powershell
uv run python python/tools/xmage_model_build.py --inputs D:/e-scratch/JOB --engine ENGINE_BUILD --out D:/e-scratch/JOB/BUILD
```

Run `spellbench.kit.xmage.ModelEncoderCheck` with `BUILD/model`, `BUILD/core`,
`BUILD/kit` and the engine jars on the classpath, in a working directory
holding its own pinned `db`. Set `-Dmz.actionVocab` to the verified `FDN_SPG.tsv`.
The real fixture reaches precombat priority with Stab, checks identical feature
and action outputs across varied sampled hidden worlds, and confirms that a
visible life change alters the features. Generation 33 then scores those real
features inside the no-network backend and produces repeat-identical scores
for offered candidates.

`ModelEncoderMain DECISION.json WORLD_SEED ID_SEED` also accepts a saved kit
decision record. Seeds are 32-byte lowercase hex strings. `--stdio` keeps the
same audited encoder warm on a private NDJSON pipe. Each request supplies `id`,
`game_start`, `decision`, `world_seed` and `id_seed`. Replies retain that ID
and either the encoded snapshot or a refusal. A malformed seed is refused
without poisoning the following valid request.

The encoder receives no live
engine game, opponent hand or actual library order. Opponent-hand encoding is
disabled. Reconstruction and watcher approximations remain explicit in the
output. Targets use the original entity-name vocabulary, including the stop
slot. True/false callbacks use slots 1/0. Every slot retains the offered
candidate ID and the encoding binds to the canonical decision SHA-256.
Unsupported callback families and reconstructed worlds are refused. A Kaito
emblem and an incomplete optional-kicker stack were correctly refused before
inference.

`ModelCallbackCheck OUTPUT_DIRECTORY` reaches two real engine dialogs: Stab
targeting two creatures and Campus Guide's optional library search. It writes
the permitted records and encodings, checks their original policy slots,
varies sampled hidden hands/libraries, and checks sensitivity to visible life.
Both fixtures pass and their output is identical across the retained builds.
The persistent pipe reproduces those snapshots. The original priority fixture
also retains its exact output SHA-256.

The isolated client maps real scores only to the bound offered candidates:

```powershell
uv run python python/tools/xmage_neural_decisions.py --root D:/e-scratch/JOB --checkpoint draftzero-exp1-gen33 --image sha256:OBSERVED_IMAGE_ID --record D:/e-scratch/JOB/target-record.json --encoded D:/e-scratch/JOB/target-encoded.json --report D:/e-scratch/JOB/target-result.json
```

Use the immutable image and hash-verified inputs described in
[the backend instructions](../../../integrations/xmage-models/README.md).
All three public checkpoints have selected offered candidates repeatedly on
both real callbacks. The client validates all policy widths and finite values,
the checkpoint/source readiness hashes, and the request ID. Writes, reads and
validation share one deadline. A failed exchange closes the owned container
and prevents subsequent use. There is no native or random-policy fallback.
Direct inference takes the largest offered raw logit and resolves ties by the
lowest candidate ID. That choice rule and the encoder approximations must
remain part of any future entry identity.

Full dialog history, the remaining decision families, original search, complete-game
tests and rating qualification remain to be implemented. No policy-equivalence
or playing-strength claim follows from these decision checks. Evidence is
indexed in [the input and adapter receipt summary](evidence/2026-10-03-neural-inputs.md).
