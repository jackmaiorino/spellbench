"""The advisor of a human session (``--advisor NAME``): how a bot's model weighs the person's own choices.

The mtg-kernel engine attaches the acting seat's model input to every decision of either seat (``x_kernel_flat_v4``
on the rated boards, ``x_kernel_flat_v7`` on the London human board). A session without an advisor drops the
person's copy. A session with one sends it to a scorer process of its own, loaded with the checkpoint of the bot
entry NAME, and shows the person the probability that model gives each choice (the softmax of its scores, which is
what a sampling bot draws from) and its value estimate.

What it is not: it never answers a decision, it is a separate process from the opponent's scorer (so it draws none
of the game's random numbers and cannot change what the opponent does), and its input is the person's own seat's,
so nothing of the opponent's hidden cards is in it. A game played with it is advised play: the session says so in
every game's log and record, and such a game is not a measure of the person's unassisted play.

Standard library only.
"""

from __future__ import annotations

import json
import math
import os
import queue
import shutil
import struct
import subprocess
import threading
from collections.abc import Mapping, Sequence
from typing import Any

FLAT_EXTENSIONS = ("x_kernel_flat_v7", "x_kernel_flat_v4")
PROPOSAL_SCHEMA = "mtg-kernel-spellbench-completion-proposals/v1"
REQUEST_SCHEMA = "mtg-kernel-spellbench-scorer-request/v1"
CHOICE_SCHEMA = "mtg-kernel-spellbench-scorer-choice/v1"
READY_SCHEMA = "mtg-kernel-spellbench-scorer-ready/v1"
SAMPLED = "sampled-wide-v1"
ARGMAX = "argmax-first-v1"
FLOAT_ENCODING = "ieee754-binary32-u32-bits"
STARTUP_TIMEOUT_S = 180.0  # the scorer loads a checkpoint before its ready record
ANSWER_TIMEOUT_S = 20.0    # a read takes milliseconds; a scorer silent this long is treated as gone
# Flags of a kernel flat bot's command that name its scorer (integrations/mtg_kernel/kernel_flat_bot.py and the
# London copy share them).
SCORER_FLAG, SCORER_ARG_FLAG, CONFIG_FLAG = "--scorer", "--scorer-arg", "--config"


class AdvisorError(Exception):
    """The advisor's scorer cannot go on (it exited, went silent or answered something else). The session plays on
    without it."""


def scorer_argv(command: Sequence[str]) -> list[str]:
    """The scorer command line of a kernel flat bot's command: the program, its arguments, the config.

    Raises ``ValueError`` for a command that names no scorer (a bot that is not a kernel flat policy)."""
    command = list(command)
    program, config, extra = None, None, []
    for index, word in enumerate(command[:-1]):
        if word == SCORER_FLAG:
            program = command[index + 1]
        elif word == CONFIG_FLAG:
            config = command[index + 1]
        elif word == SCORER_ARG_FLAG:
            extra.append(command[index + 1])
    if program is None or config is None:
        raise ValueError(f"the command names no scorer ({SCORER_FLAG} and {CONFIG_FLAG})")
    return [program, *extra, CONFIG_FLAG, config]


def softmax(logits: Sequence[float]) -> list[float]:
    top = max(logits)
    weights = [math.exp(value - top) for value in logits]
    total = sum(weights)
    return [weight / total for weight in weights]


def _f32(bits: Any) -> float:
    if type(bits) is not int or not 0 <= bits < 2**32:
        raise AdvisorError("the scorer sent a value that is not 32 float bits")
    value = struct.unpack("<f", struct.pack("<I", bits))[0]
    if not math.isfinite(value):
        raise AdvisorError("the scorer sent a value that is not finite")
    return value


def unavailable(reason: str) -> dict[str, Any]:
    return {"unavailable": reason}


class Advisor:
    """One scorer child (one JSON object per line each way) read for the person's decisions."""

    def __init__(self, argv: Sequence[str], *, name: str, label: str | None = None,
                 startup_timeout_s: float = STARTUP_TIMEOUT_S, answer_timeout_s: float = ANSWER_TIMEOUT_S) -> None:
        argv = list(argv)
        if os.path.basename(argv[0]) == argv[0]:
            argv[0] = shutil.which(argv[0]) or argv[0]
        self.name = name
        self.label = label or name
        self._timeout = answer_timeout_s
        self._lines: queue.Queue[bytes] = queue.Queue()
        self._requests = 0
        try:
            self._proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        except OSError as exc:
            raise AdvisorError(f"the scorer did not start: {exc}") from exc
        threading.Thread(target=self._pump, daemon=True).start()
        try:
            ready = self._read(startup_timeout_s)
            if ready.get("schema") != READY_SCHEMA:
                raise AdvisorError(f"the scorer did not become ready: {ready.get('code') or ready.get('schema')!r}")
            if ready.get("float_encoding") != FLOAT_ENCODING:
                raise AdvisorError(f"the scorer's float encoding {ready.get('float_encoding')!r} is not {FLOAT_ENCODING}")
            if ready.get("selection") not in (SAMPLED, ARGMAX):
                raise AdvisorError(f"unknown scorer selection {ready.get('selection')!r}")
        except AdvisorError:
            self.close()
            raise
        self.ready = ready

    def _pump(self) -> None:
        assert self._proc.stdout is not None
        try:
            for line in self._proc.stdout:
                self._lines.put(line)
        except (OSError, ValueError):
            pass
        self._lines.put(b"")

    def _read(self, timeout: float) -> dict[str, Any]:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            raise AdvisorError(f"the scorer did not answer within {timeout:g} s") from None
        if not line:
            raise AdvisorError(f"the scorer exited (code {self._proc.poll()})")
        try:
            value = json.loads(line)
        except ValueError as exc:
            raise AdvisorError("the scorer sent a line that is not JSON") from exc
        if not isinstance(value, dict):
            raise AdvisorError("the scorer sent a record that is not an object")
        return value

    def identity(self) -> dict[str, Any]:
        """What the session writes in each game's record header."""
        return {"name": self.name, "label": self.label, "model_state_sha256": self.ready.get("model_state_sha256"),
                "selection": self.ready.get("selection")}

    def read(self, game_id: str, decision: Mapping[str, Any], extension: Any) -> dict[str, Any]:
        """The model's read of one decision of the person's: ``{"rows": [{"id", "p"}], "value", "win"}`` in the order
        of the model's rows, or ``{"unavailable": reason}`` for a decision it cannot read (no model input came with
        it, the input is another model family's, an X the input cannot encode). ``value`` is the model's own
        estimate of the game's outcome for the person (-1 a loss, +1 a win) and ``win`` the same as a share of 1;
        both are None for a grouped decision (blocks, orderings), which the scorer scores without a value.

        Raises ``AdvisorError`` when the scorer itself fails; the caller stops using this advisor."""
        if not isinstance(extension, Mapping):
            return unavailable("no model input came with this decision")
        ready = self.ready
        if (extension.get("feature_contract_digest"), extension.get("feature_encoding_digest"),
                extension.get("card_db_hash")) != (ready.get("feature_contract_digest"),
                                                   ready.get("feature_encoding_digest"), ready.get("card_db_hash")):
            return unavailable(f"{self.label} reads another model input than this game's")
        if extension.get("numeric_choice_v4_fill"):
            return unavailable("an X choice the model's input cannot encode")
        candidates = decision.get("candidates") or []
        rows = extension.get("row_candidate_ids")
        seat, step = decision.get("acting_seat"), decision.get("seat_step")
        if (not isinstance(rows, list) or not rows or len(set(rows)) != len(rows)
                or any(type(row) is not int or not 0 <= row < len(candidates) for row in rows)
                or seat not in ("p0", "p1") or type(step) is not int):
            return unavailable("the model input does not match this decision's choices")
        proposals = extension.get("schema") == PROPOSAL_SCHEMA
        self._requests += 1
        request: dict[str, Any] = {
            "schema": PROPOSAL_SCHEMA if proposals else REQUEST_SCHEMA,
            "request_id": f"advisor:{game_id}:{step}:{self._requests}",
            "game_id": str(game_id), "seat": seat, "step": step,
            "feature_contract_digest": extension["feature_contract_digest"],
            "feature_encoding_digest": extension["feature_encoding_digest"],
            "row_candidate_ids": rows,
            # A sampling scorer needs a seed for the row it picks; the pick is not used, only the scores are.
            "sample_seed": 0 if ready["selection"] == SAMPLED else None,
        }
        if proposals:
            key = "proposals_zlib" if "proposals_zlib" in extension else "proposals"
            if key not in extension:
                return unavailable("the model input does not match this decision's choices")
            request[key] = extension[key]
            if "tensor_encoding" in extension:
                request["tensor_encoding"] = extension["tensor_encoding"]
        else:
            if not isinstance(extension.get("tensor"), Mapping):
                return unavailable("the model input does not match this decision's choices")
            request["tensor"] = extension["tensor"]
        line = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
        limit = ready.get("max_request_bytes")
        if type(limit) is int and len(line) > limit:
            return unavailable("this decision's model input is larger than the scorer takes")
        assert self._proc.stdin is not None
        try:
            self._proc.stdin.write(line + b"\n")
            self._proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise AdvisorError(f"the scorer's input closed: {exc}") from exc
        choice = self._read(self._timeout)
        if choice.get("schema") != CHOICE_SCHEMA or choice.get("request_id") != request["request_id"]:
            raise AdvisorError(f"the scorer answered {choice.get('schema')!r} code {choice.get('code')!r}")
        bits = choice.get("logits_bits")
        if not isinstance(bits, list) or len(bits) != len(rows):
            raise AdvisorError("the scorer's scores do not match the rows")
        shares = softmax([_f32(b) for b in bits])
        value = None if proposals else _f32(choice.get("value_bits"))
        return {"rows": [{"id": row, "p": share} for row, share in zip(rows, shares)], "value": value,
                "win": None if value is None else min(1.0, max(0.0, (value + 1.0) / 2.0))}

    def close(self, timeout: float = 2.0) -> None:
        """End the scorer in bounded time whatever it does: the process first (terminate, then kill), then the
        streams. A read stuck writing to a scorer that stopped reading holds the input stream's lock until the pipe
        breaks, so the streams are closed in a thread of their own, waited for at most ``timeout``."""
        proc = self._proc
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    pass
            except OSError:
                pass

        def close_streams() -> None:
            for stream in (proc.stdin, proc.stdout):
                try:
                    if stream is not None:
                        stream.close()
                except (OSError, ValueError):
                    pass

        closer = threading.Thread(target=close_streams, daemon=True)
        closer.start()
        closer.join(timeout)
