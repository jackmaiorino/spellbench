"""Human-play London agent for mtg-kernel FlatV7 policies.

A human-only copy of kernel_flat_bot.py (the rated board's bot, which is never
edited) for the London human-play path. The bridge run with
--pauper-london-human-v1 --x-kernel-flat-v7 attaches the acting seat's model
input to every decision as x_kernel_flat_v7: the FlatV7 tensor (in-game rows
equal V4's, pregame rows carry the London facts) plus the map from model rows
to Spellbench candidate ids. This bot forwards the tensor to the native scorer
(mtg-kernel spellbench_scorer_v1), which loads one pinned checkpoint under the
V7 identity and picks a row, and answers with the mapped candidate id. Every
mulligan and bottom decision is the model's own; there is no mulligan rule and
no keep lean here. Standard library only.

`--keep-after-mulligan` declares a rule for a bot entry named for it (the name part `keep6`): after the bot's
first mulligan it keeps whatever hand it has without scoring the question, so it is never asked Keep or Mulligan at six
cards or fewer. The seven-card decision and every put-back choice stay the model's own. It is a stopgap while mulligan
training continues, and an entry that uses it says so in its table name, its decision log and its record; a bot started
without the flag never applies it. The flag and the name part `keep6` go together like the keep-seven pair below.

`--test-keep-seven` is a test mode for a bot entry named for it: the bot keeps
at every `mulligan` decision without scoring it. It exists to check the human's
London flow against an ordinary game while the model's own mulligan play is
untrained; a played game never mixes it with a learned entry's name: the flag and
the name part `keep7` go together (a bot started with one and not the other is
refused, here and in the board generator and the entrant registration).

A numeric choice (Nyxborn Hydra's X) cannot be encoded in the FlatV7 contract, so
its tensor would be the V4 fill: off the inputs the model trained on. The bot
refuses such a decision unless started with `--allow-numeric-v4-fill`, which a
session names only for flow testing (the launcher says so on screen and in the
record); otherwise the decks that contain it are left out of London sessions.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "python"))

from spellbench.bot import Decision, GameOver, GameStart, serve  # noqa: E402
from spellbench.builtins.uniform import SplitMix64  # noqa: E402

EXTENSION = "x_kernel_flat_v7"
EXTENSION_SCHEMA = "mtg-kernel-spellbench-flat-v7/v1"
PROPOSAL_SCHEMA = "mtg-kernel-spellbench-completion-proposals/v1"
PROPOSAL_MAPPING = "deterministic-completion-logprob/v1"
PROPOSAL_ENCODING = "integer-rle/v1"
PROPOSAL_TABLE_ENCODING = "integer-rle-table/v1"
REQUEST_SCHEMA = "mtg-kernel-spellbench-scorer-request/v1"
CHOICE_SCHEMA = "mtg-kernel-spellbench-scorer-choice/v1"
READY_SCHEMA = "mtg-kernel-spellbench-scorer-ready/v1"
LOG_SCHEMA = "spellbench-kernel-bot-log/v1"
KEEP_SEVEN_NAME_PART = "keep7"
KEEP_SEVEN_TEST_NOTE = "test-keep-seven: answered keep at a mulligan decision without scoring"
KEEP_RULE_NAME_PART = "keep6"
KEEP_RULE_NOTE = "keep-after-mulligan rule: kept at a mulligan decision after a mulligan without scoring"
FEATURE_CONTRACT_DIGEST = "1f894f0dcaaeb4e5ac0233e3f39d866c0dddca494f1afc8152107bded0551a4d"
FEATURE_ENCODING_DIGEST = "4c592d136a74240f40b12c638203ab1758ed3cd63748ab7cd2788a60a78850a3"
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
        expect_model_state: str | None = None, test_keep_seven: bool = False, allow_numeric_v4_fill: bool = False,
        keep_after_mulligan: bool = False,
    ) -> None:
        if test_keep_seven != (KEEP_SEVEN_NAME_PART in name):
            raise BotError(
                f"the keep-seven test mode and the name part {KEEP_SEVEN_NAME_PART!r} go together: "
                f"--test-keep-seven is {'on' if test_keep_seven else 'off'} for the bot named {name!r}"
            )
        if keep_after_mulligan != (KEEP_RULE_NAME_PART in name):
            raise BotError(
                f"the keep-after-mulligan rule and the name part {KEEP_RULE_NAME_PART!r} go together: "
                f"--keep-after-mulligan is {'on' if keep_after_mulligan else 'off'} for the bot named {name!r}"
            )
        if keep_after_mulligan and test_keep_seven:
            raise BotError("--keep-after-mulligan and --test-keep-seven are different bots: not both")
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
        self._test_keep_seven = test_keep_seven
        self._keep_after_mulligan = keep_after_mulligan
        self._allow_numeric_v4_fill = allow_numeric_v4_fill

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
                "test_keep_seven": self._test_keep_seven, "keep_after_mulligan": self._keep_after_mulligan,
                "allow_numeric_v4_fill": self._allow_numeric_v4_fill,
            })

    def choose(self, decision: Decision) -> int:
        started = time.perf_counter_ns()
        if self._test_keep_seven:
            keeps = [c.candidate_id for c in decision.candidates
                     if c.semantic.get("kind") == "mulligan" and c.semantic.get("keep") is True]
            if len(keeps) == 1 and all(c.semantic.get("kind") == "mulligan" for c in decision.candidates):
                self._write_log({"kind": "decision", "step": decision.seat_step, "candidate_id": keeps[0],
                                 "note": KEEP_SEVEN_TEST_NOTE})
                return keeps[0]
        if self._keep_after_mulligan:
            forced = self._forced_keep(decision)
            if forced is not None:
                self._write_log({"kind": "decision", "step": decision.seat_step, "candidate_id": forced,
                                 "note": KEEP_RULE_NOTE})
                return forced
        extension = decision.extensions.get(EXTENSION)
        if not isinstance(extension, dict):
            raise self._fail("decision lacks x_kernel_flat_v7; run the bridge with --x-kernel-flat-v7")
        rows = self._validated_rows(decision, extension)
        if extension.get("numeric_choice_v4_fill") and not self._allow_numeric_v4_fill:
            raise self._fail(
                "a numeric choice (a Nyxborn Hydra X) arrived as the V4 fill, which is not an input the V7 model "
                "trained on; leave Elves and Wildfire out of the session, or start the bot with "
                "--allow-numeric-v4-fill for flow testing only"
            )
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
            # A numeric choice (an X value) the V7 contract cannot encode: its tensor is the V4 fill, outside any
            # trained V7 input. Recorded so a played game says where the model was asked off its inputs.
            "numeric_choice_v4_fill": bool(extension.get("numeric_choice_v4_fill")),
        })
        return rows[row]

    @staticmethod
    def _forced_keep(decision: Decision) -> int | None:
        """The keep candidate of a Keep-or-Mulligan question asked after a mulligan (the rule), else None.

        Only a decision that is wholly a mulligan question, with one keep answer, and whose every candidate says at
        least one mulligan has been taken, is answered by the rule. The seven-card question (no mulligan taken) and
        every other decision, the put-back included, go to the model."""
        candidates = decision.candidates
        if not candidates or any(c.semantic.get("kind") != "mulligan" for c in candidates):
            return None
        taken = [c.semantic.get("mulligans_taken") for c in candidates]
        if any(type(n) is not int or n < 1 for n in taken):
            return None
        keeps = [c.candidate_id for c in candidates if c.semantic.get("keep") is True]
        return keeps[0] if len(keeps) == 1 else None

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
            raise self._fail("x_kernel_flat_v7 identity does not match the model")
        if extension.get("acting_seat") != decision.acting_seat or decision.acting_seat != self._seat:
            raise self._fail("x_kernel_flat_v7 is not for this seat")
        if type(decision.seat_step) is not int or decision.seat_step < 0 or extension.get("step") != decision.seat_step:
            raise self._fail("x_kernel_flat_v7 is not for this step")
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
            raise self._fail("tensor fields differ from the V7 wire")
        return rows

    def _write_log(self, record: dict[str, Any]) -> None:
        if self._log is not None:
            self._log.write(_dumps(record) + "\n")
            self._log.flush()

    @staticmethod
    def _fail(message: str) -> BotError:
        print(f"kernel_flat_bot: {message}", file=sys.stderr)
        return BotError(message)


def build_parser() -> argparse.ArgumentParser:
    """The bot's command line (also read by the human session's --bot-native, which passes the bot's own scorer, seed
    and expected model state to the engine with exactly the bot's parsing)."""
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
    parser.add_argument(
        "--test-keep-seven", action="store_true",
        help="TEST MODE: keep at every mulligan decision without scoring it (a bot entry named for it only)",
    )
    parser.add_argument(
        "--keep-after-mulligan", action="store_true",
        help="RULE: after its first mulligan the bot keeps any hand without scoring the question (a bot entry named "
             "for it only); the seven-card decision and the put-backs stay the model's",
    )
    parser.add_argument(
        "--allow-numeric-v4-fill", action="store_true",
        help="FLOW TESTING ONLY: score a numeric choice on its V4 fill (off the model's trained inputs) instead of refusing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.seed < 0:
        parser.error("--seed must be nonnegative")
    if args.test_keep_seven != (KEEP_SEVEN_NAME_PART in args.name):
        parser.error(f"--test-keep-seven and the name part {KEEP_SEVEN_NAME_PART!r} go together")
    if args.keep_after_mulligan != (KEEP_RULE_NAME_PART in args.name):
        parser.error(f"--keep-after-mulligan and the name part {KEEP_RULE_NAME_PART!r} go together")
    if args.keep_after_mulligan and args.test_keep_seven:
        parser.error("--keep-after-mulligan and --test-keep-seven are different bots: not both")
    try:
        scorer = ScorerProcess([args.scorer, *args.scorer_arg, "--config", args.config])
        bot = KernelFlatBot(
            scorer, seed=args.seed, decision_log=args.decision_log, name=args.name, version=args.version,
            expect_model_state=args.expect_model_state, test_keep_seven=args.test_keep_seven,
            allow_numeric_v4_fill=args.allow_numeric_v4_fill, keep_after_mulligan=args.keep_after_mulligan,
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
