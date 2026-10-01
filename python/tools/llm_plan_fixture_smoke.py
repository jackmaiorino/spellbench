"""One small v2 fixture game with at most two subscription inference requests.

Uses the existing scoring test engine, not a Magic rules engine. Requires the
test and chatgpt extras and previously approved Spellbench credentials.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import importlib.metadata
import platform
import ssl
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", type=Path, required=True, help="new output directory; existing attempts are preserved")
    parser.add_argument("--credentials", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "python" / "tests"))
    from test_host_game import real_engine, setup, Seat
    from spellbench.arena.config import BotSpec
    from spellbench.arena.drivers import SubprocessDriver
    from spellbench.host.game import play_game
    from spellbench.llm.login import default_credentials_path, load_credentials
    from spellbench.llm.tls import native_opener

    # Validate local access before spawning any process. No model request occurs.
    load_credentials(args.credentials or default_credentials_path())
    native_opener()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, "-m", "spellbench.llm", "--provider", "chatgpt-plan", "--model", args.model,
               "--reasoning-effort", "low", "--max-completion-tokens", "1024", "--max-calls-per-game", "2",
               "--max-tokens-per-game", "50000", "--history-decisions", "1", "--timeout-ms", "20000",
               "--log-dir", str(output)]
    if args.credentials:
        command += ["--credentials", str(args.credentials)]
    configuration = setup()
    manifest = {"kind": "single-end-to-end-v2-fixture-game", "model": args.model,
                "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                "python": platform.python_version(), "gpu_ordinal": None, "agent_seeds": configuration.agent_seeds,
                "toolchain": {"openssl": ssl.OPENSSL_VERSION, "truststore": importlib.metadata.version("truststore"),
                              "pyjwt": importlib.metadata.version("PyJWT"), "linker": "not applicable: Python"},
                "uv_lock_sha256": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
                "engine": "fake-v2-engine/scoring-fixture", "maximum_requests": 2, "timeout_ms": 20000,
                "reasoning_effort": "low", "hard_output_cap_available": False,
                "engine_input_sha256": hashlib.sha256((root / "python/tests/fake_v2_engine.py").read_bytes()).hexdigest(),
                "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "non_claims": ["not a complete Magic rules game", "no playing-strength estimate",
                               "no sandbox-confinement claim", "no hard allowance or dollar cap"]}
    path = output / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    engine = seat = None
    started = time.monotonic()
    try:
        engine = real_engine()
        seat = SubprocessDriver(BotSpec(name="llm-" + args.model, version="0.1.0", type="subprocess", command=tuple(command)),
                                startup_ms=5000)
        result = play_game(configuration, engine=engine, seats={"p0": seat, "p1": Seat()})
        manifest.update(classification=result.classification, outcome=result.outcome, reason=result.reason,
                        game_digest=result.game_digest, decisions_checked=result.decisions_checked, steps=result.step_count)
    except Exception as exc:
        # The agent log contains stable provider codes; exception strings can
        # carry unrelated caller or subprocess context.
        manifest.update(classification="exception", failure_type=type(exc).__name__)
    finally:
        if seat is not None:
            seat.close()
        if engine is not None:
            engine.close()
        manifest["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        logs = list(output.glob("*.jsonl"))
        if logs:
            raw = logs[0].read_bytes()
            manifest["log_sha256"] = hashlib.sha256(raw).hexdigest()
            fields = ("status", "error", "calls", "tokens", "prompt_tokens", "completion_tokens",
                      "returned_model", "elapsed_ms", "unknown_usage", "prompt_sha256")
            manifest["decision_logs"] = [{key: event.get(key) for key in fields}
                                         for line in raw.splitlines() if (event := json.loads(line)).get("event") == "decision"]
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest))
    return 0 if manifest.get("classification") == "natural" and manifest.get("decisions_checked") == 4 else 2


if __name__ == "__main__":
    raise SystemExit(main())
