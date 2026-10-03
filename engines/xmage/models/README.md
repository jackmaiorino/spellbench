# DraftZero priority encoder slice

This is the tested connection from permitted XMage observations to Exp1's
feature hash and legal priority-action slots. It is not a complete agent.

The source staging tool verifies the pinned public Java encoder files before
making explicit compatibility edits for the reviewed base engine. The staged
source hashes and every rewrite are recorded. Card sorting, entity names and
permanent ordering use the public fork's rules. Optional debug pairs use a
small local value type instead of JavaFX. Micro-decision history is empty and
the activation-in-progress flag is false at this priority slice. Soulbond
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
priority record. Seeds are 32-byte hex strings. The encoder receives no live
engine game, opponent hand or actual library order. Opponent-hand encoding is
disabled. Reconstruction and watcher approximations remain explicit in the
output. An unsupported Kaito emblem in a saved Standard fixture was correctly
refused before inference.

Full dialog history, all decision families, original search, complete-game
tests and rating qualification remain to be implemented. No policy-equivalence
or playing-strength claim follows from this priority check.
