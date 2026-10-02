"""One or two full catalogue games with a confined subscription-backed LLM.

A bounded engineering pilot, not a rated tournament or throughput-qualified
measurement launcher. Every attempt gets a new output directory and preserved
failure records. Inference is performed only by the host-owned provider.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

from spellbench import wire
from spellbench.agent_messages import OwnDeck
from spellbench.arena.config import BotSpec
from spellbench.arena.drivers import BuiltinDriver, SubprocessDriver
from spellbench.builtins import BUILTIN_VERSIONS
from spellbench.digests import card_name_domain, deck_id
from spellbench.host.agent_process import AgentProcess
from spellbench.host.engine_process import EngineProcess
from spellbench.host.game import GameSetup, play_game
from spellbench.llm.agent import AgentConfig
from spellbench.llm.broker import BrokerLimits, BrokerPeer, BrokerSession
from spellbench.llm.chatgpt import ChatGptConfig, ChatGptProvider
from spellbench.llm.docker_peer import DockerPeer
from spellbench.llm.login import default_credentials_path, refresh_credentials
from spellbench.llm.provider import ProviderError
from spellbench.messages import Limits, Resources, Rules, TimeControl, WireDeck
from spellbench.run_secret import RunSecret


def save(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


class UsageBudget:
    def __init__(self, provider, *, model: str, requests: int, tokens: int, deadline: float, log) -> None:
        self.provider, self.model, self.deadline, self.log = provider, model, deadline, log
        self.max_requests, self.max_tokens = requests, tokens
        self.calls = self.tokens = self.unknown = 0
        self.failed = False

    def complete(self, prompt, *, timeout_s):
        if self.failed:
            raise ProviderError("pilot_already_failed")
        if self.calls >= self.max_requests or self.tokens + prompt.bytes + 1024 > self.max_tokens:
            raise ProviderError("pilot_budget_exhausted")
        timeout_s = min(timeout_s, self.deadline - time.monotonic())
        if timeout_s <= 0:
            raise ProviderError("pilot_deadline_exhausted")
        self.calls += 1
        start = time.monotonic()
        event = {"request": self.calls, "prompt_sha256": prompt.sha256, "status": "attempting",
                 "unknown_usage": True}
        self.log.write(wire.canonical_json_line(event).decode())
        self.log.flush()
        try:
            result = self.provider.complete(prompt, timeout_s=timeout_s)
            if any(type(count) is not int or count < 0 for count in (result.prompt_tokens, result.completion_tokens)):
                raise ProviderError("invalid_provider_usage")
            self.tokens += result.prompt_tokens + result.completion_tokens
            event.update(unknown_usage=False, prompt_tokens=result.prompt_tokens,
                         completion_tokens=result.completion_tokens, returned_model=result.model)
            if result.model != self.model:
                raise ProviderError("pilot_model_mismatch")
            if self.tokens > self.max_tokens:
                raise ProviderError("pilot_token_budget_exceeded")
            event["status"] = "completed"
            return result
        except Exception as exc:
            self.failed = True
            self.unknown += int(event["unknown_usage"])
            event.update(status="failed", error=exc.code if isinstance(exc, ProviderError) else "provider_internal_error")
            raise
        finally:
            event.update(elapsed_ms=round((time.monotonic() - start) * 1000), calls=self.calls, tokens=self.tokens)
            self.log.write(wire.canonical_json_line(event).decode())
            self.log.flush()


class StorageBudget:
    """Bound all traffic and usage logs before writes, including forced choices."""
    def __init__(self, limit: int):
        self.limit, self.written = limit, 0

    def wrap(self, stream):
        budget = self

        class Log:
            def write(self, value):
                size = len(value.encode("utf-8"))
                if budget.written + size > budget.limit:
                    raise ProviderError("pilot_storage_budget_exhausted")
                budget.written += size
                return stream.write(value)

            def flush(self):
                stream.flush()

        return Log()


class RecordingPeer:
    def __init__(self, peer, log, outgoing: str, incoming: str, deadline: float):
        self.peer, self.log, self.outgoing, self.incoming, self.deadline = peer, log, outgoing, incoming, deadline

    def set_timeout(self, seconds):
        remaining = max(0.001, self.deadline - time.monotonic())
        self.peer.set_timeout(remaining if seconds is None else min(seconds, remaining))

    def _record(self, direction, raw):
        self.log.write(wire.canonical_json_line({"dir": direction, "message": wire.strict_json_loads(raw)}).decode())
        self.log.flush()

    def write_line(self, raw):
        self.peer.write_line(raw)
        self._record(self.outgoing, raw)

    def read_line(self):
        raw = self.peer.read_line()
        self._record(self.incoming, raw)
        return raw

    def stderr_text(self):
        return self.peer.stderr_text()

    def close(self):
        self.peer.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--image", required=True, help="immutable local Docker image ID")
    parser.add_argument("--engine-command", type=Path, required=True, help="JSON argv; executed without a shell")
    parser.add_argument("--engine-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="new SSD scratch directory")
    parser.add_argument("--credentials", type=Path)
    parser.add_argument("--format", default="standard-2022-25-bo1")
    parser.add_argument("--deck", action="append", help="one or two catalogue IDs; one full mirror game per ID")
    parser.add_argument("--seed", type=int, default=20261001)
    parser.add_argument("--max-requests", type=int, default=256)
    parser.add_argument("--max-tokens", type=int, default=750_000)
    parser.add_argument("--max-wall-seconds", type=int, default=1800)
    args = parser.parse_args()
    decks = args.deck or ["Standard16-RG", "Standard16-UB"]
    if (not 1 <= len(decks) <= 2 or not 1 <= args.max_requests <= 512 or not 1 <= args.max_tokens <= 1_000_000
            or not 60 <= args.max_wall_seconds <= 1800):
        parser.error("pilot is limited to two games, 512 requests, one million reported tokens and 30 minutes")
    command_raw = args.engine_command.read_bytes()
    command = json.loads(command_raw)
    if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
        parser.error("engine command must be a nonempty JSON argv")
    engine_raw = args.engine_manifest.read_bytes()
    pin = json.loads(engine_raw)
    output = args.out.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < 60 * 2**30:
        parser.error("scratch volume must retain the standing 60 GiB reserve")
    output.mkdir(exist_ok=False)
    (output / "engine-command.json").write_bytes(command_raw)
    (output / "engine-manifest.json").write_bytes(engine_raw)
    root = Path(__file__).resolve().parents[2]
    manifest = {"kind": "bounded-live-Magic-integration-pilot", "status": "preparing", "model": args.model,
                "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                "image_id": args.image, "engine_manifest_sha256": hashlib.sha256(engine_raw).hexdigest(),
                "engine_command_sha256": hashlib.sha256(command_raw).hexdigest(), "decks": decks,
                "format": args.format, "seed": args.seed, "gpu_ordinal": None,
                "python": platform.python_version(), "linker": "not applicable: Python; engine toolchain in its manifest",
                "maximum_requests": args.max_requests, "maximum_reported_tokens": args.max_tokens,
                "maximum_wall_seconds": args.max_wall_seconds, "hard_output_cap_available": False,
                "reasoning_effort": "low", "history_decisions": 1, "projected_output_bytes": 60 * 2**20,
                "storage_cap_bytes": 256 * 2**20, "games": [], "containers": [],
                "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "non_claims": ["engineering pilot, not a rated or strength estimate", "no model-output determinism claim",
                               "reported token limits are not a hard provider allowance cap",
                               "no substantial serial/parallel throughput qualification"]}
    save(output / "manifest.json", manifest)
    storage = StorageBudget(manifest["storage_cap_bytes"] - 2**20)
    started = time.monotonic()
    deadline = started + args.max_wall_seconds
    exit_code = 2
    with (output / "usage.jsonl").open("x", encoding="utf-8", newline="\n") as usage_stream:
        usage = storage.wrap(usage_stream)
        budget = None
        try:
            profile = refresh_credentials(args.credentials or default_credentials_path(),
                                          minimum_valid_seconds=args.max_wall_seconds + 60)
            provider_config = ChatGptConfig(args.model, profile["access_token"], "low", profile["expires_at"])
            budget = UsageBudget(ChatGptProvider(provider_config), model=args.model, requests=args.max_requests,
                                 tokens=args.max_tokens, deadline=deadline, log=usage)
            secret = RunSecret(hashlib.sha256(f"spellbench-llm-pilot:{args.seed}".encode()).digest())
            for index, catalog_id in enumerate(decks):
                if budget.failed or deadline <= time.monotonic():
                    break
                with (output / f"game-{index}.transcript.jsonl").open("x", encoding="utf-8", newline="\n") as traffic, \
                        (output / f"game-{index}.broker.jsonl").open("x", encoding="utf-8", newline="\n") as broker_log:
                    traffic, broker_log = storage.wrap(traffic), storage.wrap(broker_log)
                    engine = seat = opponent = None
                    game_started = time.monotonic()
                    try:
                        engine = EngineProcess(peer=RecordingPeer(wire.SubprocessPeer(command, timeout_s=60), traffic,
                                               "host_to_engine", "engine_to_host", deadline), timeout_s=60)
                        hello = engine.hello()
                        if (hello.engine.rules_snapshot_id != pin["rules_snapshot_id"]
                                or hello.engine.card_pool_identity != pin["card_pool_identity"]):
                            raise ValueError("engine identity differs from its pinned manifest")
                        deck = next(item for item in hello.catalog if item.catalog_id == catalog_id)
                        if sum(row.count for row in deck.decklist) < (40 if args.format == "fdn-limited-bo1" else 60):
                            raise ValueError("the pilot requires a full-size catalogue deck")
                        engine.validate_deck(format=args.format, catalog_id=catalog_id)
                        own = OwnDeck(deck_id([row.to_json() for row in deck.decklist]), deck.name, deck.decklist)
                        wire_deck = WireDeck(own.deck_id, catalog_id=catalog_id)
                        rules = Rules.from_json({"opponent_decklist": "visible", "mulligan": "london",
                                                 "starting_player": "host_assigned", "starting_seat": "p0",
                                                 "card_name_domain": card_name_domain([row.name for row in deck.decklist]),
                                                 "extensions": [], "probe": False})
                        setup = GameSetup(index, secret.game_id(index), secret.game_secret(index).hex(), args.format,
                                          (wire_deck, wire_deck), (own, own), rules,
                                          TimeControl(60000, 10000, 600000, 2000, 30000, 30000),
                                          Limits(10000, 100000, 500, 4999, 49999), Resources(1, 512, False, 1),
                                          (secret.agent_seed(index, "p0"), secret.agent_seed(index, "p1")))
                        llm_seat = "p0" if index == 0 else "p1"
                        remaining_calls, remaining_tokens = args.max_requests - budget.calls, args.max_tokens - budget.tokens
                        config = AgentConfig(max_calls_per_game=remaining_calls, max_tokens_per_game=remaining_tokens,
                                             timeout_ms=30000, history_decisions=1)

                        def factory():
                            child = DockerPeer(args.image, ["python", "-m", "spellbench.llm", "--broker-stdio",
                                "--model", args.model, "--history-decisions", "1", "--timeout-ms", "30000",
                                "--max-calls-per-game", str(remaining_calls), "--max-tokens-per-game", str(remaining_tokens),
                                "--log-dir", "/tmp/llm"], timeout_s=10)
                            manifest["containers"].append(child.name)
                            try:
                                save(output / "manifest.json", manifest)
                                session = BrokerSession(child, budget, settings=provider_config.public_settings(),
                                    max_completion_tokens=1024, log=broker_log, config=config,
                                    limits=BrokerLimits(remaining_calls, remaining_tokens, 10000))
                                peer = RecordingPeer(BrokerPeer(session), traffic, "host_to_agent", "agent_to_host", deadline)
                                return AgentProcess(peer=peer, startup_timeout_s=10)
                            except Exception:
                                child.close()
                                raise

                        seat = SubprocessDriver(BotSpec(name="llm-" + args.model, version="0.1.0", type="subprocess",
                                                       command=("injected-confined-broker",)), startup_ms=10000, agent_factory=factory)
                        opponent = BuiltinDriver(BotSpec(name="heuristic", version=BUILTIN_VERSIONS["heuristic"],
                                                         type="builtin", seed=secret.agent_seed(index, "p1" if index == 0 else "p0")))
                        result = play_game(setup, engine=engine, seats={llm_seat: seat,
                                          "p1" if llm_seat == "p0" else "p0": opponent})
                        manifest["games"].append({"index": index, "deck": catalog_id, "llm_seat": llm_seat,
                            "agent_seeds": setup.agent_seeds, "elapsed_ms": round((time.monotonic()-game_started)*1000),
                            **{key: getattr(result, key) for key in ("classification", "outcome", "winner", "reason", "adjudication",
                                     "step_count", "decision_count", "decisions_checked", "game_digest", "violation", "diagnostics")}})
                        save(output / "manifest.json", manifest)
                    finally:
                        try:
                            if seat is not None:
                                seat.close()
                        finally:
                            try:
                                if opponent is not None:
                                    opponent.close()
                            finally:
                                if engine is not None:
                                    engine.close()
                if manifest["games"][-1]["classification"] != "natural":
                    break
            complete = len(manifest["games"]) == len(decks) and all(game["classification"] == "natural"
                                                                                  for game in manifest["games"])
            manifest["status"] = "completed" if complete else "failed"
            exit_code = 0 if complete else 2
        except Exception as exc:
            manifest.update(status="failed", failure_type=type(exc).__name__,
                            error=exc.code if isinstance(exc, ProviderError) else "pilot_preflight_or_host_failure")
        finally:
            if budget is not None:
                manifest.update(requests=budget.calls, reported_tokens=budget.tokens, unknown_usage_requests=budget.unknown)
            manifest["elapsed_ms"] = round((time.monotonic() - started) * 1000)
            usage.flush()
            manifest["files"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in output.glob("*.jsonl")}
            manifest["log_bytes"] = storage.written
            try:
                active = subprocess.run(["docker", "container", "ls", "--all", "--filter", "label=spellbench.role=llm-child",
                                         "--format", "{{.Names}}"], capture_output=True, text=True, timeout=10)
                owned_remaining = set(active.stdout.splitlines()) & set(manifest["containers"])
                manifest["cleanup_verified"] = active.returncode == 0 and not owned_remaining
            except (OSError, subprocess.TimeoutExpired):
                manifest["cleanup_verified"] = False
                manifest["cleanup_error"] = "docker_unavailable"
            if not manifest["cleanup_verified"]:
                manifest["status"], exit_code = "failed", 2
            save(output / "manifest.json", manifest)
    print(json.dumps(manifest))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
