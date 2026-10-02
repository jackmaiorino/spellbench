"""Maintainer-owned stdio entry point for a confined ChatGPT-plan agent.

The arena launches this trusted broker; only the child agent runs inside the
network-less container. Admission and the manifest's isolation labels remain
the arena's responsibility. No model requests happen during hello preflight.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from ..errors import SpellbenchError
from .agent import AgentConfig
from .broker import BrokerLimits, BrokerSession, serve_broker
from .chatgpt import ChatGptConfig, ChatGptProvider
from .docker_peer import DockerPeer
from .login import default_credentials_path, load_credentials
from .renewal import renew_profile
from .provider import ProviderError
from .run_budget import BudgetedProvider, RunBudget


class BoundedLog:
    def __init__(self, stream, *, limit: int = 4 * 2**20):
        self.stream, self.limit, self.written = stream, limit, 0

    def write(self, value: str):
        size = len(value.encode("utf-8"))
        if self.written + size > self.limit:
            raise OSError("broker log limit exhausted")
        self.written += size
        return self.stream.write(value)

    def flush(self):
        self.stream.flush()


class PlanProvider:
    """Load the already renewed app profile only when inference is needed."""
    def __init__(self, model: str, credentials: Path, effort: str, *, budget: RunBudget):
        self.model, self.credentials, self.effort = model, credentials, effort
        self.budget = budget
        self.provider = None
        self._failed = False

    def renew_before_game(self):
        if self._failed:
            raise ProviderError("provider_already_failed")
        try:
            renew_profile(self.credentials, self.budget)
            profile = load_credentials(self.credentials)
            self.provider = ChatGptProvider(ChatGptConfig(
                self.model, profile["access_token"], self.effort, profile["expires_at"],
            ))
        except Exception as exc:
            self._failed = True
            if not isinstance(exc, ProviderError) or exc.code != "profile_renewal_failed":
                self.budget.fail("profile_renewal_failed")
            raise ProviderError("profile_renewal_failed") from None

    def complete(self, prompt, *, timeout_s):
        if self._failed:
            raise ProviderError("provider_already_failed")
        try:
            if self.provider is None:
                profile = load_credentials(self.credentials)
                self.provider = ChatGptProvider(ChatGptConfig(
                    self.model, profile["access_token"], self.effort, profile["expires_at"],
                ))
            return self.provider.complete(prompt, timeout_s=timeout_s)
        except Exception:
            self._failed = True
            raise


def child_command(model: str, config: AgentConfig, output_tokens: int) -> list[str]:
    return ["python", "-m", "spellbench.llm", "--model", model, "--broker-stdio",
            "--log-dir", "/tmp/logs", "--max-completion-tokens", str(output_tokens),
            "--max-calls-per-game", str(config.max_calls_per_game),
            "--max-tokens-per-game", str(config.max_tokens_per_game),
            "--max-prompt-bytes", str(config.max_prompt_bytes),
            "--history-decisions", str(config.history_decisions), "--timeout-ms", str(config.timeout_ms)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--run-budget", type=Path, required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--credentials", type=Path)
    parser.add_argument("--renew-profile-before-game", action="store_true",
                        help="explicitly renew the app-owned grant before game_start, with no model call")
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high", "xhigh", "max"), default="low")
    parser.add_argument("--max-completion-tokens", type=int, default=1024)
    parser.add_argument("--max-calls-per-game", type=int, default=256)
    parser.add_argument("--max-tokens-per-game", type=int, default=750_000)
    parser.add_argument("--history-decisions", type=int, default=1)
    parser.add_argument("--timeout-ms", type=int, default=20_000)
    parser.add_argument("--max-run-requests", type=int, default=4096)
    parser.add_argument("--max-run-tokens", type=int, default=10_000_000)
    parser.add_argument("--max-run-wall-seconds", type=int, default=7200)
    parser.add_argument("--max-inflight", type=int, default=4)
    parser.add_argument("--allow-timeout-forfeits", action="store_true",
                        help="require the matching budget policy; settled timeouts forfeit only their game")
    args = parser.parse_args()
    child = None
    budget = None
    try:
        config = AgentConfig(max_calls_per_game=args.max_calls_per_game,
                             max_tokens_per_game=args.max_tokens_per_game,
                             history_decisions=args.history_decisions, timeout_ms=args.timeout_ms)
        if args.max_completion_tokens < 1:
            raise ValueError("output limit must be positive")
        budget = RunBudget(args.run_budget, model=args.model,
                           expected_limits={"max_requests": args.max_run_requests,
                                            "max_reported_tokens": args.max_run_tokens,
                                            "max_wall_seconds": args.max_run_wall_seconds,
                                            "max_inflight": args.max_inflight,
                                            "allow_timeout_forfeits": args.allow_timeout_forfeits})
        plan = PlanProvider(args.model, args.credentials or default_credentials_path(), args.reasoning_effort,
                            budget=budget)
        provider = BudgetedProvider(plan, budget,
                                    output_tokens=args.max_completion_tokens)
        args.log_dir.mkdir(parents=True, exist_ok=True)
        with (args.log_dir / f"broker-{uuid.uuid4().hex}.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
            child = DockerPeer(args.image, child_command(args.model, config, args.max_completion_tokens))
            session = BrokerSession(child, provider,
                                    settings={"transport": "confined-chatgpt-plan", "model": args.model,
                                              "reasoning_effort": args.reasoning_effort,
                                              "image_id": args.image, "container_name": child.name,
                                              "renew_before_game": args.renew_profile_before_game,
                                              "allow_timeout_forfeits": args.allow_timeout_forfeits,
                                              "aggregate_budget": True, "provider_output_cap": False},
                                    max_completion_tokens=args.max_completion_tokens, log=BoundedLog(stream),
                                    config=config, limits=BrokerLimits(max_calls_total=config.max_calls_per_game,
                                                                      max_tokens_total=config.max_tokens_per_game))
            status = serve_broker(session, before_game_start=plan.renew_before_game
                                  if args.renew_profile_before_game else None)
            if status != 0 and not (args.allow_timeout_forfeits and session._failed
                                    and provider.settled_error == "timeout"):
                # Choice validation and child transport happen after provider
                # accounting. Their failure cannot masquerade as a completed call.
                budget.fail("hosted_broker_failed")
            return status
    except (ValueError, OSError, ProviderError, SpellbenchError):
        if budget is not None:
            # An exception in logging, transport or renewal also stops admission,
            # even if a previous request in this broker happened to time out.
            budget.fail("hosted_broker_failed")
        print("hosted LLM broker failed; check its protected profile, run budget, image and logs", file=sys.stderr)
        return 2
    finally:
        if child is not None:
            try:
                child.close()
            except Exception:
                if budget is not None:
                    budget.fail("hosted_broker_failed")
                raise


if __name__ == "__main__":
    raise SystemExit(main())
