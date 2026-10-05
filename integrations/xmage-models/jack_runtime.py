"""Isolated inference for Jack's pinned April candidate and mulligan networks."""

from __future__ import annotations

import importlib.util
import math
import sys
from importlib.metadata import version
from pathlib import Path


HEADS = ("action", "target", "card_select", "attack", "block")


def vector(value, width: int, *, integers: int | None = None, boolean: bool = False):
    if not isinstance(value, list) or len(value) != width:
        raise ValueError("encoded vector does not match its declared width")
    if boolean:
        if any(type(item) is not bool for item in value):
            raise ValueError("encoded mask must contain booleans")
    elif integers is not None:
        if any(type(item) is not int or not 0 <= item < integers for item in value):
            raise ValueError("encoded ids exceed the vocabulary")
    elif any(type(item) not in (int, float) or not math.isfinite(item) or abs(item) > 1e6 for item in value):
        raise ValueError("encoded features must be finite bounded numbers")
    return value


def matrix(value, width: int):
    if not isinstance(value, list) or not 1 <= len(value) <= 512:
        raise ValueError("encoded matrix exceeds its row bound")
    return [vector(row, width) for row in value]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class JackRuntime:
    def __init__(self, checkpoint: Path, checkpoint_sha256: str, source: Path,
                 model_sha256: str, mulligan: Path, mulligan_sha256: str,
                 mulligan_source_sha256: str, encoder_sha256: str, callback_sha256: str,
                 embeddings: Path, embeddings_sha256: str, mulligan_format: str):
        from checkpoint_runtime import check_pin
        if not Path("/.dockerenv").is_file():
            raise ValueError("checkpoint loading requires the no-network container launcher")
        for path, pin in ((checkpoint, checkpoint_sha256), (source / "model.py", model_sha256),
                          (mulligan, mulligan_sha256), (source / "mulligan_model.py", mulligan_source_sha256),
                          (source / "StateSequenceBuilder.java", encoder_sha256),
                          (source / "ComputerPlayerRL.java", callback_sha256), (embeddings, embeddings_sha256)):
            check_pin(path, pin)
        import torch
        self.torch = torch
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        mulligan_state = torch.load(mulligan, map_location="cpu", weights_only=True)
        if (not isinstance(state, dict) or not isinstance(state.get("config"), dict)
                or not isinstance(state.get("state_dict"), dict)
                or not isinstance(mulligan_state, dict)
                or not isinstance(mulligan_state.get("model_state_dict"), dict)):
            raise ValueError("Jack checkpoint lacks its original network state/configuration")
        weights, mulligan_weights = state["state_dict"], mulligan_state["model_state_dict"]
        expected_width = {"keep-logit": 1, "keep-mull-q": 2}.get(mulligan_format)
        if expected_width is None or int(mulligan_weights["output.weight"].shape[0]) != expected_width:
            raise ValueError("mulligan weights do not match the declared policy format")
        self.mulligan_format = mulligan_format
        if any(not torch.is_tensor(value) or not torch.isfinite(value).all().item()
               for value in [*weights.values(), *mulligan_weights.values()]):
            raise ValueError("Jack checkpoint contains invalid network tensors")
        parameters = dict(state["config"])
        parameters.update(cand_feat_dim=int(weights["cand_feat_proj.0.weight"].shape[1]),
                          token_vocab=int(weights["token_id_emb.weight"].shape[0]),
                          action_vocab=int(weights["action_id_emb.weight"].shape[0]))
        module = load_module("jack_pinned_model", source / "model.py")
        self.model = module.MTGTransformerModel(**parameters).to("cpu").eval()
        self.model.load_state_dict(weights, strict=True)
        vocab_size, embed_dim = mulligan_weights["card_embed.weight"].shape
        explicit = int(mulligan_weights["fc1.weight"].shape[1]) - 1 - int(embed_dim) - 32
        if not 0 <= explicit <= 64:
            raise ValueError("unsupported Jack mulligan feature width")
        self.mulligan_parameters = {"vocab_size": int(vocab_size), "embed_dim": int(embed_dim),
                                    "max_hand": 7, "max_deck": 60, "num_explicit": explicit}
        module = load_module("jack_pinned_mulligan", source / "mulligan_model.py")
        self.mulligan = module.MulliganNet(**self.mulligan_parameters).to("cpu").eval()
        self.mulligan.load_state_dict(mulligan_weights, strict=True)
        self.parameters = parameters
        self.encoding = {"state_encoder_sha256": encoder_sha256, "callback_sha256": callback_sha256,
                         "card_embeddings_sha256": embeddings_sha256,
                         "mulligan_source_sha256": mulligan_source_sha256, "mulligan_format": mulligan_format,
                         "input_dim": parameters["input_dim"], "candidate_dim": parameters["cand_feat_dim"],
                         "token_vocab": parameters["token_vocab"], "action_vocab": parameters["action_vocab"],
                         "mulligan_dim": 1 + explicit + 7 + 60}
        self.summary = {"architecture": "jack-rl-april", "checkpoint_sha256": checkpoint_sha256,
                        "model_source_sha256": model_sha256, "mulligan_sha256": mulligan_sha256,
                        "mulligan_source_sha256": mulligan_source_sha256, "encoding": self.encoding,
                        "parameters": parameters, "mulligan_parameters": self.mulligan_parameters,
                        "candidate_heads": list(HEADS), "device": "cpu", "weights_only": True,
                        "model_class": type(self.model).__name__, "mulligan_class": type(self.mulligan).__name__,
                        "dependencies": {name: version(name) for name in ("torch", "numpy")},
                        "strict_load": True, "finite_weights": True,
                        "source_scope": "pinned historical network; exact game/encoder association still needs qualification"}
        del state, weights, mulligan_state, mulligan_weights

    def evaluate(self, features: dict, encoding: dict) -> dict:
        if encoding != self.encoding or not isinstance(features, dict):
            raise ValueError("encoded features do not match this checkpoint's encoder identity")
        torch = self.torch
        kind = features.get("kind")
        with torch.inference_mode():
            if kind == "mulligan":
                values = vector(features.get("values"), self.encoding["mulligan_dim"])
                split = 1 + self.mulligan_parameters["num_explicit"]
                vector(values[split:], 67, integers=self.mulligan_parameters["vocab_size"])
                if not any(values[split:split + 7]):
                    raise ValueError("encoded mulligan hand contains only padding")
                logits = self.mulligan(torch.tensor([values], dtype=torch.float32))
                if not torch.isfinite(logits).all().item():
                    raise ValueError("mulligan network returned invalid logits")
                if self.mulligan_format == "keep-mull-q":
                    keep, mull = logits[0].tolist()
                    return {"q_keep": keep, "q_mulligan": mull, "keep": keep >= mull}
                return {"keep_logit": logits.item(), "keep_probability": torch.sigmoid(logits).item()}
            if kind not in ("candidates", "legacy_actor"):
                raise ValueError("unsupported Jack inference request")
            sequence = matrix(features.get("sequence"), self.parameters["input_dim"])
            count = len(sequence)
            mask = vector(features.get("padding"), count, boolean=True)
            if all(mask):
                raise ValueError("encoded state contains only padding")
            token_ids = vector(features.get("token_ids"), count, integers=self.parameters["token_vocab"])
            sequence = torch.tensor([sequence], dtype=torch.float32)
            mask = torch.tensor([mask], dtype=torch.bool)
            token_ids = torch.tensor([token_ids], dtype=torch.long)
            if kind == "legacy_actor":
                logits, probabilities, value = self.model(sequence, mask, token_ids=token_ids)
            else:
                head = features.get("head")
                if head not in HEADS:
                    raise ValueError("unsupported Jack candidate head")
                candidates = matrix(features.get("candidate_features"), self.parameters["cand_feat_dim"])
                candidate_ids = vector(features.get("candidate_ids"), len(candidates),
                                       integers=self.parameters["action_vocab"])
                candidate_mask = vector(features.get("candidate_mask"), len(candidates), boolean=True)
                if not any(candidate_mask):
                    raise ValueError("encoded candidates contain no legal choice")
                probabilities, value = self.model.score_candidates(
                    sequence, mask, token_ids, torch.tensor([candidates], dtype=torch.float32),
                    torch.tensor([candidate_ids], dtype=torch.long),
                    torch.tensor([candidate_mask], dtype=torch.bool), head_id=head)
                logits = None
            if any(not torch.isfinite(tensor).all().item() for tensor in (probabilities, value)):
                raise ValueError("policy network returned invalid outputs")
            result = {"probabilities": probabilities[0].tolist(), "value": value.item()}
            if logits is not None:
                if not torch.isfinite(logits).all().item():
                    raise ValueError("policy network returned invalid logits")
                result["logits"] = logits[0].tolist()
            return result

    def probe(self) -> dict:
        base = {"sequence": [[0] * self.parameters["input_dim"] for _ in range(8)],
                "padding": [False] * 8, "token_ids": list(range(1, 9))}
        result = {}
        for head in HEADS:
            request = {**base, "kind": "candidates", "head": head,
                       "candidate_features": [[0] * self.parameters["cand_feat_dim"] for _ in range(3)],
                       "candidate_ids": [1, 2, 3], "candidate_mask": [True] * 3}
            result[head] = self.evaluate(request, self.encoding)
        result["legacy_actor"] = self.evaluate({**base, "kind": "legacy_actor"}, self.encoding)
        result["mulligan"] = self.evaluate({"kind": "mulligan",
            "values": [0] + [1] * self.mulligan_parameters["num_explicit"] + list(range(1, 68))}, self.encoding)
        return result
