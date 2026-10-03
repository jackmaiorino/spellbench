"""Spellbench v2 agent for mtg-kernel Phase 1 policies (g115, A48, c12).

The mtg-kernel bridge run with --x-kernel-flat-v4 attaches the acting seat's
model input to every decision as x_kernel_flat_v4: the actor-visible V4
tensor from the kernel's own encoder plus the map from model rows to
Spellbench candidate ids. This bot forwards the tensor to the native scorer
(mtg-kernel spellbench_scorer_v1), which loads one pinned checkpoint and
picks a row, and answers with the mapped candidate id. Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

from spellbench.bot import Decision, GameOver, GameStart, serve  # noqa: E402
from spellbench.builtins.uniform import SplitMix64  # noqa: E402

EXTENSION = "x_kernel_flat_v4"
EXTENSION_SCHEMA = "mtg-kernel-spellbench-flat-v4/v1"
PROPOSAL_SCHEMA = "mtg-kernel-spellbench-completion-proposals/v1"
PROPOSAL_MAPPING = "deterministic-completion-logprob/v1"
PROPOSAL_ENCODING = "integer-rle/v1"
PROPOSAL_TABLE_ENCODING = "integer-rle-table/v1"
REQUEST_SCHEMA = "mtg-kernel-spellbench-scorer-request/v1"
CHOICE_SCHEMA = "mtg-kernel-spellbench-scorer-choice/v1"
READY_SCHEMA = "mtg-kernel-spellbench-scorer-ready/v1"
LOG_SCHEMA = "spellbench-kernel-bot-log/v1"
FEATURE_CONTRACT_DIGEST = "c4af415a3b0cf1e9c9960dbe2bc2d134c63e9f08206a9a364e113121fea5538b"
FEATURE_ENCODING_DIGEST = "271c0e5a0fdce75663c897e89a9d7280ab1a3bbb6679bd10ecb5f524991952de"
SAMPLED = "sampled-wide-v1"
ARGMAX = "argmax-first-v1"
SAMPLER_IDENTITY = "f32-q8-expq63-hamilton-splitmix64-wide-v1"
FLOAT_ENCODING = "ieee754-binary32-u32-bits"
TENSOR_KEYS = frozenset({
    "state", "object_features", "object_card_ids", "object_groups", "object_node_ids",
    "edge_features", "edge_source_indices", "edge_target_indices", "action_features",
    "action_ref_features", "action_ref_card_ids", "action_ref_action_indices", "action_ref_node_indices",
})
MASK64 = (1 << 64) - 1
SEED_DOMAIN = b"spellbench-kernel-flat-bot/v1"


class BotError(Exception):
    """A condition the bot refuses to guess past (answered as internal_error)."""


def seat_stream_seed(seed: int, game_id: str, seat: str) -> int:
    digest = hashlib.sha256(SEED_DOMAIN + b"\0" + game_id.encode("utf-8") + b"\0" + seat.encode("ascii")).digest()
    return (seed ^ int.from_bytes(digest[:8], "big")) & MASK64


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class ScorerProcess:
    """The native scorer child: one JSON object per line each way."""

    def __init__(self, argv: list[str]) -> None:
        argv = list(argv)
        # A bare program name resolves on PATH (with PATHEXT on Windows), as
        # spellbench.wire.SubprocessPeer does, so one command runs on both.
        if os.path.basename(argv[0]) == argv[0]:
            argv[0] = shutil.which(argv[0]) or argv[0]
        self._proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.ready = self._read()
        if self.ready.get("schema") != READY_SCHEMA:
            raise BotError(f"scorer did not become ready: {self.ready!r}")

    def _read(self) -> dict[str, Any]:
        assert self._proc.stdout is not None
        line = self._proc.stdout.readline()
        if not line:
            raise BotError(f"scorer exited (code {self._proc.poll()})")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise BotError("scorer sent a non-object record")
        return value

    def score(self, request: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
        assert self._proc.stdin is not None
        line = _dumps(request).encode("utf-8")
        try:
            self._proc.stdin.write(line + b"\n")
            self._proc.stdin.flush()
        except OSError as exc:
            raise BotError(f"scorer input closed: {exc}") from exc
        return line, self._read()

    def close(self) -> None:
        if self._proc.stdin is not None and not self._proc.stdin.closed:
            self._proc.stdin.close()
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()


class KernelFlatBot:
    def __init__(
        self, scorer: ScorerProcess, *, seed: int, decision_log: Path | None, name: str, version: str,
        expect_model_state: str | None = None,
    ) -> None:
        ready = scorer.ready
        if (ready.get("feature_contract_digest"), ready.get("feature_encoding_digest")) != (
            FEATURE_CONTRACT_DIGEST, FEATURE_ENCODING_DIGEST,
        ):
            raise BotError("scorer serves a different feature contract")
        if ready.get("sampler_identity") != SAMPLER_IDENTITY:
            raise BotError(f"scorer sampler {ready.get('sampler_identity')!r} is not {SAMPLER_IDENTITY}")
        if ready.get("float_encoding") != FLOAT_ENCODING:
            raise BotError(f"scorer float encoding {ready.get('float_encoding')!r} is not {FLOAT_ENCODING}")
        if ready.get("selection") not in (SAMPLED, ARGMAX):
            raise BotError(f"unknown scorer selection {ready.get('selection')!r}")
        if expect_model_state is not None and ready.get("model_state_sha256") != expect_model_state:
            raise BotError(
                f"scorer loaded model state {ready.get('model_state_sha256')}, expected {expect_model_state}"
            )
        self._scorer = scorer
        self._seed = seed
        self._log_dir = decision_log
        self._identity = (name, version)
        self._card_db: str = ready["card_db_hash"]
        self._selection: str = ready["selection"]
        self._state: str = ready["model_state_sha256"]
        self._seat: str | None = None
        self._rng: SplitMix64 | None = None
        self._log = None

    def on_game_start(self, request: GameStart) -> None:
        engine = request.engine
        if engine.get("name") != "mtg-kernel" or not str(engine.get("card_pool_identity", "")).endswith(f"carddb-{self._card_db}"):
            raise self._fail("engine identity lacks the required card registry")
        if request.seat not in ("p0", "p1"):
            raise self._fail("game_start has no valid seat")
        self._seat = request.seat
        stream_seed = seat_stream_seed(self._seed, request.game_id, request.seat)
        self._rng = SplitMix64(stream_seed)
        if self._log_dir is not None:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            path = self._log_dir / f"{request.game_id}.{request.seat}.jsonl"
            self._log = open(path, "w", encoding="utf-8", newline="\n")
            self._write_log({
                "schema": LOG_SCHEMA, "kind": "header", "game_id": request.game_id, "seat": request.seat,
                "bot_name": self._identity[0], "bot_version": self._identity[1], "selection": self._selection,
                "stream_seed": stream_seed, "model_state_sha256": self._state,
            })

    def choose(self, decision: Decision) -> int:
        started = time.perf_counter_ns()
        extension = decision.extensions.get(EXTENSION)
        if not isinstance(extension, dict):
            raise self._fail("decision lacks x_kernel_flat_v4; run the bridge with --x-kernel-flat-v4")
        rows = self._validated_rows(decision, extension)
        assert self._rng is not None
        sample_seed = self._rng.next() if self._selection == SAMPLED else None
        request = {
            "schema": PROPOSAL_SCHEMA if extension["schema"] == PROPOSAL_SCHEMA else REQUEST_SCHEMA,
            "request_id": f"{decision.game_id}:{decision.seat_step}",
            "game_id": decision.game_id, "seat": decision.acting_seat, "step": decision.seat_step,
            "feature_contract_digest": FEATURE_CONTRACT_DIGEST, "feature_encoding_digest": FEATURE_ENCODING_DIGEST,
            "row_candidate_ids": rows, "sample_seed": sample_seed,
        }
        if extension["schema"] == PROPOSAL_SCHEMA:
            if "proposals_zlib" in extension:
                request["proposals_zlib"] = extension["proposals_zlib"]
            else:
                request["proposals"] = extension["proposals"]
            if "tensor_encoding" in extension:
                request["tensor_encoding"] = extension["tensor_encoding"]
        else:
            request["tensor"] = extension["tensor"]
        line, choice = self._scorer.score(request)
        if choice.get("schema") != CHOICE_SCHEMA or choice.get("request_id") != request["request_id"]:
            raise self._fail(f"scorer answered {choice.get('schema')!r} code {choice.get('code')!r}")
        if choice.get("request_sha256") != hashlib.sha256(line).hexdigest():
            raise self._fail("scorer hashed a different request")
        if request["schema"] == PROPOSAL_SCHEMA and choice.get("mapping") != PROPOSAL_MAPPING:
            raise self._fail("scorer used another neutral completion mapping")
        row = choice.get("selected_row")
        if type(row) is not int or not 0 <= row < len(rows) or choice.get("selected_candidate_id") != rows[row]:
            raise self._fail("scorer choice does not match the row map")
        self._write_log({
            "kind": "decision", "step": decision.seat_step, "candidate_id": rows[row], "selected_row": row,
            "sample_seed": sample_seed, "logits_bits": choice["logits_bits"], "value_bits": choice["value_bits"],
            "request_sha256": choice["request_sha256"], "elapsed_us": (time.perf_counter_ns() - started) // 1000,
        })
        return rows[row]

    def on_game_over(self, request: GameOver) -> None:
        self._close_log()

    def close(self) -> None:
        self._close_log()
        self._scorer.close()

    def _close_log(self) -> None:
        if self._log is not None:
            self._log.close()
            self._log = None

    def _validated_rows(self, decision: Decision, extension: dict[str, Any]) -> list[int]:
        if (
            extension.get("schema") not in (EXTENSION_SCHEMA, PROPOSAL_SCHEMA)
            or extension.get("feature_contract_digest") != FEATURE_CONTRACT_DIGEST
            or extension.get("feature_encoding_digest") != FEATURE_ENCODING_DIGEST
            or extension.get("card_db_hash") != self._card_db
        ):
            raise self._fail("x_kernel_flat_v4 identity does not match the model")
        if extension.get("acting_seat") != decision.acting_seat or decision.acting_seat != self._seat:
            raise self._fail("x_kernel_flat_v4 is not for this seat")
        if type(decision.seat_step) is not int or decision.seat_step < 0 or extension.get("step") != decision.seat_step:
            raise self._fail("x_kernel_flat_v4 is not for this step")
        rows = extension.get("row_candidate_ids")
        if (
            not isinstance(rows, list) or not rows or len(set(rows)) != len(rows)
            or any(type(r) is not int or not 0 <= r < len(decision.candidates) for r in rows)
        ):
            raise self._fail("row_candidate_ids is not an injective map into the candidates")
        if extension["schema"] == PROPOSAL_SCHEMA:
            if extension.get("mapping") != PROPOSAL_MAPPING:
                raise self._fail("unknown neutral completion mapping")
            if extension.get("tensor_encoding") not in (None, PROPOSAL_ENCODING, PROPOSAL_TABLE_ENCODING):
                raise self._fail("unknown completion tensor encoding")
            if "proposals_zlib" in extension:
                if ("proposals" in extension or not isinstance(extension["proposals_zlib"], str)
                    or not extension["proposals_zlib"]):
                    raise self._fail("invalid compressed completion proposals")
                return rows
            if extension.get("tensor_encoding") == PROPOSAL_TABLE_ENCODING:
                raise self._fail("vector-table completion requires a compressed payload")
            proposals = extension.get("proposals")
            if not isinstance(proposals, list) or len(proposals) != len(rows):
                raise self._fail("completion proposals differ from the candidate rows")
            tensors = []
            for steps in proposals:
                if not isinstance(steps, list) or not steps or len(steps) > 4096:
                    raise self._fail("invalid completion trajectory")
                for step in steps:
                    if not isinstance(step, dict) or set(step) != {"tensor", "selected_row"} or type(step["selected_row"]) is not int or step["selected_row"] < 0:
                        raise self._fail("invalid completion row")
                    tensors.append(step["tensor"])
        else:
            tensors = [extension.get("tensor")]
        if any(not isinstance(tensor, dict) or set(tensor) != TENSOR_KEYS for tensor in tensors):
            raise self._fail("tensor fields differ from the V4 wire")
        return rows

    def _write_log(self, record: dict[str, Any]) -> None:
        if self._log is not None:
            self._log.write(_dumps(record) + "\n")
            self._log.flush()

    @staticmethod
    def _fail(message: str) -> BotError:
        print(f"kernel_flat_bot: {message}", file=sys.stderr)
        return BotError(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scorer", required=True, help="spellbench_scorer_v1 executable")
    parser.add_argument("--scorer-arg", action="append", default=[], help="argument placed before --config")
    parser.add_argument("--config", required=True, help="scorer config JSON")
    parser.add_argument("--name", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--decision-log", type=Path, default=None)
    parser.add_argument(
        "--expect-model-state", metavar="SHA256", default=None,
        help="exit before hello unless the scorer reports this model_state_sha256",
    )
    args = parser.parse_args(argv)
    if args.seed < 0:
        parser.error("--seed must be nonnegative")
    try:
        scorer = ScorerProcess([args.scorer, *args.scorer_arg, "--config", args.config])
        bot = KernelFlatBot(
            scorer, seed=args.seed, decision_log=args.decision_log, name=args.name, version=args.version,
            expect_model_state=args.expect_model_state,
        )
    except (BotError, OSError, ValueError) as exc:
        print(f"kernel_flat_bot: {exc}", file=sys.stderr)
        return 1
    try:
        return serve(bot, name=args.name, version=args.version,
                     requires_extensions=(EXTENSION,), extensions_accepted=(EXTENSION,))
    finally:
        bot.close()


if __name__ == "__main__":
    sys.exit(main())
