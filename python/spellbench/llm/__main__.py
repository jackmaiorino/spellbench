"""Run with ``python -m spellbench.llm --model MODEL`` (v2 stdin/stdout)."""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

from ..bot import serve
from .agent import AgentConfig, LlmAgent
from .broker import StdioProvider
from .chatgpt import ChatGptConfig, ChatGptProvider
from .login import default_credentials_path, load_credentials
from .prompt import CardCatalog
from .provider import ChatCompletionsProvider, ProviderConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="A Spellbench v2 text LLM agent")
    parser.add_argument("--model", required=True)
    parser.add_argument("--provider", choices=("chat-completions", "chatgpt-plan"), default="chat-completions")
    parser.add_argument("--credentials", type=Path, help="Spellbench ChatGPT-plan credentials")
    parser.add_argument("--base-url")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY", help="environment variable name, never the key itself")
    parser.add_argument("--allow-no-api-key", action="store_true", help="for local inference servers")
    parser.add_argument("--broker-stdio", action="store_true", help="ask a host broker over the existing stdio pipes")
    parser.add_argument("--max-completion-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--reasoning-effort", choices=("minimal", "low", "medium", "high", "xhigh", "max"))
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
        if args.max_completion_tokens < 1:
            parser.error("--max-completion-tokens must be positive")
        if args.provider == "chatgpt-plan":
            if args.broker_stdio or args.base_url or args.temperature is not None or args.response_format != "json_schema" or args.allow_no_api_key:
                parser.error("chatgpt-plan requires its fixed Responses endpoint and JSON schema; unsupported provider options supplied")
            credentials = load_credentials(args.credentials or default_credentials_path())
            provider_config = ChatGptConfig(args.model, credentials["access_token"], args.reasoning_effort or "low",
                                            credentials["expires_at"])
            provider = ChatGptProvider(provider_config)
            settings = {**provider_config.public_settings(), "max_completion_tokens": args.max_completion_tokens}
            print("ChatGPT plan usage: output limits are checked after completion; no server-side token cap is available.", file=sys.stderr)
        else:
            api_key = None if args.broker_stdio else os.environ.get(args.api_key_env)
            if not args.broker_stdio and not api_key and not args.allow_no_api_key:
                parser.error(f"set the {args.api_key_env} environment variable or use --allow-no-api-key for local inference")
            provider_config = ProviderConfig(model=args.model, base_url=args.base_url or "https://api.openai.com/v1", api_key=api_key,
                                             max_completion_tokens=args.max_completion_tokens, temperature=args.temperature,
                                             reasoning_effort=args.reasoning_effort, response_format=args.response_format)
            provider = StdioProvider() if args.broker_stdio else ChatCompletionsProvider(provider_config)
            settings = ({"transport": "broker-stdio", "model": args.model,
                         "max_completion_tokens": args.max_completion_tokens}
                        if args.broker_stdio else provider_config.public_settings())
        config = AgentConfig(max_calls_per_game=args.max_calls_per_game, max_tokens_per_game=args.max_tokens_per_game,
                             max_prompt_bytes=args.max_prompt_bytes, history_decisions=args.history_decisions,
                             timeout_ms=args.timeout_ms, record_prompts=args.record_prompts)
        catalog = None if args.card_catalog is None else CardCatalog.load(args.card_catalog)
        args.log_dir.mkdir(parents=True, exist_ok=True)
        log_path = args.log_dir / f"llm-{os.getpid()}-{uuid.uuid4().hex}.jsonl"
        with log_path.open("x", encoding="utf-8", newline="\n") as log:
            agent = LlmAgent(provider, settings=settings,
                             max_completion_tokens=args.max_completion_tokens, config=config, catalog=catalog, log=log)
            return serve(agent, name="llm-" + args.model, version="0.1.0")
    except (ValueError, OSError):
        print("LLM configuration or local logging failed; check endpoint, settings, catalog and log directory", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
