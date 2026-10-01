"""Run with ``python -m spellbench.llm --model MODEL`` (v2 stdin/stdout)."""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

from ..bot import serve
from .agent import AgentConfig, LlmAgent
from .prompt import CardCatalog
from .provider import ChatCompletionsProvider, ProviderConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="A Spellbench v2 text LLM agent")
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="https://api.openai.com/v1")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY", help="environment variable name, never the key itself")
    parser.add_argument("--allow-no-api-key", action="store_true", help="for local inference servers")
    parser.add_argument("--max-completion-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--reasoning-effort", choices=("minimal", "low", "medium", "high"))
    parser.add_argument("--response-format", choices=("json_schema", "json_object"), default="json_schema")
    parser.add_argument("--timeout-ms", type=int, default=20_000)
    parser.add_argument("--max-calls-per-game", type=int, default=256)
    parser.add_argument("--max-tokens-per-game", type=int, default=250_000)
    parser.add_argument("--max-prompt-bytes", type=int, default=64_000)
    parser.add_argument("--history-decisions", type=int, default=8)
    parser.add_argument("--card-catalog", type=Path)
    parser.add_argument("--log-dir", type=Path, default=Path("out/llm"))
    parser.add_argument("--record-prompts", action="store_true")
    args = parser.parse_args()
    try:
        api_key = os.environ.get(args.api_key_env)
        if not api_key and not args.allow_no_api_key:
            parser.error(f"set the {args.api_key_env} environment variable or use --allow-no-api-key for local inference")
        provider_config = ProviderConfig(model=args.model, base_url=args.base_url, api_key=api_key,
                                         max_completion_tokens=args.max_completion_tokens, temperature=args.temperature,
                                         reasoning_effort=args.reasoning_effort, response_format=args.response_format)
        config = AgentConfig(max_calls_per_game=args.max_calls_per_game, max_tokens_per_game=args.max_tokens_per_game,
                             max_prompt_bytes=args.max_prompt_bytes, history_decisions=args.history_decisions,
                             timeout_ms=args.timeout_ms, record_prompts=args.record_prompts)
        catalog = None if args.card_catalog is None else CardCatalog.load(args.card_catalog)
        args.log_dir.mkdir(parents=True, exist_ok=True)
        log_path = args.log_dir / f"llm-{os.getpid()}-{uuid.uuid4().hex}.jsonl"
        with log_path.open("x", encoding="utf-8", newline="\n") as log:
            agent = LlmAgent(ChatCompletionsProvider(provider_config), settings=provider_config.public_settings(),
                             max_completion_tokens=provider_config.max_completion_tokens, config=config, catalog=catalog, log=log)
            return serve(agent, name="llm-" + args.model, version="0.1.0")
    except (ValueError, OSError):
        print("LLM configuration or local logging failed; check endpoint, settings, catalog and log directory", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
