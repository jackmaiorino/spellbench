"""Isolated MageZero, DraftZero and the maintainer's checkpoint inference.

Use only through a no-network Docker container. The host supplies pinned
checkpoints and exact model/encoder inputs, each mounted read-only.
This backend scores already encoded features. A legal Spellbench agent also
needs the audited encoder, action mapping and sampled-world search adapter.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from importlib.metadata import version
from pathlib import Path

from checkpoint_format import checkpoint_stream


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_pin(path: Path, expected: str) -> None:
    if not path.is_file() or path.is_symlink() or file_hash(path) != expected:
        raise ValueError(f"checkpoint backend input changed: {path.name}")


class Runtime:
    def __init__(self, checkpoint: Path, checkpoint_sha256: str, source: Path,
                 model_sha256: str, vocab_sha256: str, actions: Path | None, actions_sha256: str | None,
                 architecture: str, checkpoint_format: str = "torch-gzip",
                 expected_export: dict | None = None):
        # The actual confinement boundary is the host's Docker command; this
        # additional refusal catches an accidental direct invocation on the host.
        if not Path("/.dockerenv").is_file():
            raise ValueError("checkpoint loading requires the no-network container launcher")
        check_pin(checkpoint, checkpoint_sha256)
        check_pin(source / "model.py", model_sha256)
        check_pin(source / "vocab.py", vocab_sha256)
        if architecture == "draftzero-exp1":
            if actions is None or actions_sha256 is None:
                raise ValueError("DraftZero Exp1 requires its pinned action vocabulary")
            check_pin(actions, actions_sha256)
        elif architecture != "magezero-v02":
            raise ValueError("unknown checkpoint architecture")
        if checkpoint_format == "magezero-mz" and architecture != "magezero-v02":
            raise ValueError("MageZero exports require the MageZero architecture")
        import torch
        self.torch = torch
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        os.environ["MZ_DEVICE"] = "cpu"
        os.environ.pop("MZ_ACTION_VOCAB", None)
        os.environ.pop("MZ_EMBED_ROWS", None)
        os.environ.pop("MZ_PAD_BUCKET", None)
        # weights_only has no unsafe fallback and admits no arbitrary pickle globals.
        with checkpoint_stream(checkpoint, checkpoint_format, expected_export) as (stream, export_metadata):
            state = torch.load(stream, map_location="cpu", weights_only=True)
        if not isinstance(state, dict) or "model_state_dict" not in state or "feature_vocab" not in state:
            raise ValueError("checkpoint lacks model weights or its feature vocabulary")
        for name in ("model", "vocab"):
            spec = importlib.util.spec_from_file_location(f"xmage_pinned_{name}", source / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            setattr(self, name + "_module", module)
        self.vocab = self.vocab_module.FeatureVocab.from_state_dict(state["feature_vocab"])
        if architecture == "draftzero-exp1":
            if self.model_module.GLOBAL_MAX != 2000000:
                raise ValueError("DraftZero Exp1 source uses a different feature hash range")
            self.model = self.model_module.build_model_from_checkpoint(state).to("cpu").eval()
            self.width = self.model_module.policy_width(self.model)
            action_dim = None
            for line in actions.read_text(encoding="utf-8").splitlines():
                if line.startswith("dim\t"):
                    action_dim = int(line.split("\t")[1])
                    break
            if action_dim != self.width or self.width != 1024:
                raise ValueError("action vocabulary width does not match the checkpoint's policy heads")
        else:
            if self.model_module.GLOBAL_MAX != 2147483647 or self.vocab.encoding()["feature_hash_bins"] != 2147483647:
                raise ValueError("MageZero v0.2 requires its recorded wide feature hash range")
            # Match the original server: dense vocabulary size and four fixed
            # policy heads. Strict loading refuses older or differently sized exports.
            self.model = self.model_module.NetTransformer(num_embeddings=len(self.vocab)).to("cpu").eval()
            self.model.load_state_dict(state["model_state_dict"], strict=True)
            self.width = 128
        self.vocab.require_encoding(self.model_module.GLOBAL_MAX)
        recorded_encoding = self.vocab.encoding()
        # Exp1's format-1 vocab predates the bin-count field. Its pinned model
        # and Java encoder both use GLOBAL_MAX=2,000,000. Preserve the missing
        # record separately and require the effective identity at every request.
        self.encoding = {**recorded_encoding,
                         "feature_hash_bins": self.model_module.GLOBAL_MAX}
        self.summary = {"checkpoint_sha256": checkpoint_sha256,
                        "checkpoint_format": checkpoint_format, "export_metadata": export_metadata,
                        "model_source_sha256": model_sha256, "vocab_source_sha256": vocab_sha256,
                        "action_vocab_sha256": actions_sha256,
                        "architecture": architecture,
                        "model_class": type(self.model).__name__, "policy_width": self.width,
                        "embedding_rows": int(state["model_state_dict"]["embedding.weight"].shape[0]),
                        "encoding": self.encoding, "recorded_encoding": recorded_encoding,
                        "vocab_format": state["feature_vocab"]["format_version"],
                        "dependencies": {name: version(name) for name in ("torch", "numpy", "scipy")},
                        "device": "cpu", "weights_only": True}
        self.probe_features = state["feature_vocab"]["ids"][:32].tolist()
        del state

    def evaluate(self, features: list[int], encoding: dict) -> dict:
        if encoding != self.encoding:
            raise ValueError("encoded features do not match this checkpoint's encoder identity")
        if not isinstance(features, list) or not features or any(
                type(x) is not int or not 0 <= x < self.encoding["feature_hash_bins"] for x in features):
            raise ValueError("features must be a non-empty list of nonnegative integer ids")
        if len(features) > 16384:
            raise ValueError("encoded feature input exceeds the declared token bound")
        # The original inference server maps through this saved dense vocabulary
        # and drops unknown raw features. Do not replace it with modulo hashing.
        mapped, starts = self.vocab.map_bags(features, [0])
        if not len(mapped):
            raise ValueError("checkpoint vocabulary contains none of the encoded features")
        torch = self.torch
        indices = torch.tensor(mapped, dtype=torch.long)
        offsets = torch.tensor(starts, dtype=torch.long)
        with torch.inference_mode():
            values = self.model(indices, offsets)
        if len(values) != 5 or any(not torch.isfinite(x).all().item() for x in values):
            raise ValueError("model returned invalid policy/value outputs")
        return {"priority": values[0][0].tolist(), "opponent_priority": values[1][0].tolist(),
                "target": values[2][0].tolist(), "binary": values[3][0].tolist(),
                "value": values[4][0].item()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("probe", "serve"))
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--checkpoint-format", choices=("torch", "torch-gzip", "magezero-mz"),
                        default="torch-gzip")
    parser.add_argument("--export-deck")
    parser.add_argument("--export-version", type=int)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--model-sha256", required=True)
    parser.add_argument("--vocab-sha256")
    parser.add_argument("--actions", type=Path)
    parser.add_argument("--actions-sha256")
    parser.add_argument("--architecture", choices=("draftzero-exp1", "magezero-v02", "maintainer-rl-april"), required=True)
    parser.add_argument("--mulligan", type=Path)
    parser.add_argument("--mulligan-sha256")
    parser.add_argument("--mulligan-source-sha256")
    parser.add_argument("--mulligan-format", choices=("keep-logit", "keep-mull-q"), default="keep-logit")
    parser.add_argument("--encoder-sha256")
    parser.add_argument("--callback-sha256")
    parser.add_argument("--embeddings", type=Path)
    parser.add_argument("--embeddings-sha256")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    expected_export = None
    if args.export_deck is not None or args.export_version is not None:
        expected_export = {"deck": args.export_deck, "version": args.export_version}
    if args.architecture == "maintainer-rl-april":
        from maintainer_runtime import MaintainerRuntime
        if (args.checkpoint_format != "torch" or expected_export is not None
                or any(value is None for value in (args.mulligan, args.mulligan_sha256,
                    args.mulligan_source_sha256, args.encoder_sha256, args.callback_sha256,
                    args.embeddings, args.embeddings_sha256))):
            raise ValueError("the maintainer's inference requires raw weights and all paired source/encoder/embedding pins")
        runtime = MaintainerRuntime(args.checkpoint, args.checkpoint_sha256, args.source, args.model_sha256,
                              args.mulligan, args.mulligan_sha256, args.mulligan_source_sha256,
                              args.encoder_sha256, args.callback_sha256, args.embeddings, args.embeddings_sha256,
                              args.mulligan_format)
    else:
        if args.vocab_sha256 is None:
            raise ValueError("MageZero/DraftZero inference requires the pinned vocabulary source")
        runtime = Runtime(args.checkpoint, args.checkpoint_sha256, args.source, args.model_sha256,
                          args.vocab_sha256, args.actions, args.actions_sha256, args.architecture,
                          args.checkpoint_format, expected_export)
    if args.mode == "probe":
        first = runtime.probe() if args.architecture == "maintainer-rl-april" else runtime.evaluate(runtime.probe_features, runtime.encoding)
        second = runtime.probe() if args.architecture == "maintainer-rl-april" else runtime.evaluate(runtime.probe_features, runtime.encoding)
        raw = json.dumps(first, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if first != second:
            raise ValueError("repeated checkpoint inference differs")
        result = {"schema": "spellbench-xmage-checkpoint-probe/v1", **runtime.summary,
                  "finite_outputs": True, "repeated_inference_identical": True,
                  "output_sha256": hashlib.sha256(raw).hexdigest(),
                  "scope": "real checkpoint load and synthetic encoded-feature inference; no Magic game or rating"}
        if args.report:
            with args.report.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, indent=2, allow_nan=False)
                stream.write("\n")
        print(json.dumps(result, sort_keys=True, allow_nan=False), flush=True)
        return 0
    print(json.dumps({"ready": True, **runtime.summary}), flush=True)
    for line in sys.stdin:
        request = json.loads(line)
        result = runtime.evaluate(request["features"], request["encoding"])
        print(json.dumps({"id": request["id"], **result}, allow_nan=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
