"""Check LLM prompts and forced-choice bypass against complete v2 transcripts.

Replays recorded choices through the actual adapter without network access or
credentials. Counts prospective requests on those recorded paths; the model's
own choices could lead to different paths and costs.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import subprocess
from pathlib import Path

from spellbench.bot import Decision, GameOver, GameStart
from spellbench.llm.agent import AgentConfig, LlmAgent
from spellbench.llm.provider import Completion


class RecordedProvider:
    def __init__(self) -> None:
        self.candidate_id = 0
        self.prompt_bytes: list[int] = []
        self.prompt_chain = hashlib.sha256()

    def complete(self, prompt, *, timeout_s: float) -> Completion:
        self.prompt_bytes.append(prompt.bytes)
        self.prompt_chain.update(bytes.fromhex(prompt.sha256))
        return Completion(json.dumps({"candidate_id": self.candidate_id}), "recorded-choice", 0, 0)


def check(path: Path, *, history: int, max_bytes: int) -> dict:
    raw = path.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    agents = {}
    providers = {}
    seeds = {}
    game_ids = set()
    decisions = {"p0": 0, "p1": 0}
    terminal = None
    for index, row in enumerate(rows):
        message = row["message"]
        if row["dir"] == "engine_to_host" and message.get("response_type") == "terminal":
            terminal = message
        if row["dir"] != "host_to_agent":
            continue
        kind = message.get("request_type")
        if kind == "game_start":
            game = GameStart.from_request(message)
            if game.seat in agents:
                raise ValueError("one game per transcript is required")
            provider = RecordedProvider()
            agent = LlmAgent(provider, settings={"model": "recorded-choice", "network": False},
                             max_completion_tokens=1024, log=io.StringIO(),
                             config=AgentConfig(history_decisions=history, max_prompt_bytes=max_bytes,
                                                max_calls_per_game=1_000_000, max_tokens_per_game=1_000_000_000))
            agent.on_game_start(game)
            agents[game.seat], providers[game.seat] = agent, provider
            seeds[game.seat] = game.agent_seed
            game_ids.add(game.game_id)
        elif kind == "choose":
            decision = Decision.from_request(message)
            reply = rows[index + 1]
            if (reply["dir"] != "agent_to_host" or reply["message"].get("response_type") != "choice"
                    or reply["message"].get("request_id") != message["request_id"]):
                raise ValueError("choose must be followed by its recorded choice")
            choice = reply["message"]["selection"]["candidate_id"]
            if type(choice) is not int:
                raise ValueError("recorded candidate_id must be an integer")
            providers[decision.acting_seat].candidate_id = choice
            # Historical transcripts use zero clocks. This offline check does
            # no timed inference, so give the adapter a valid local deadline.
            decision.clock.update(remaining_ms=20_000, max_decision_ms=20_000)
            if agents[decision.acting_seat].choose(decision) != choice:
                raise ValueError("adapter choice differs from recorded choice")
            decisions[decision.acting_seat] += 1
    if set(agents) != {"p0", "p1"} or terminal is None:
        raise ValueError("transcript must start both seats and end with an engine terminal")
    if game_ids != {terminal["game_id"]}:
        raise ValueError("seat starts and terminal must name the same game")
    if terminal.get("classification") != "natural":
        raise ValueError("a naturally completed transcript is required")
    for agent in agents.values():
        agent.on_game_over(GameOver.from_request({"game_id": terminal["game_id"], "terminal": terminal}))
    seats = {}
    for seat, provider in providers.items():
        sizes = provider.prompt_bytes
        seats[seat] = {"decisions": decisions[seat], "requests": len(sizes),
                       "forced": decisions[seat] - len(sizes), "prompt_bytes_total": sum(sizes),
                       "prompt_bytes_max": max(sizes, default=0),
                       "prompt_chain_sha256": provider.prompt_chain.hexdigest()}
    return {"transcript": str(path.resolve()), "input_sha256": hashlib.sha256(raw).hexdigest(),
            "game_id": terminal["game_id"], "agent_seeds": seeds, "ending": {key: terminal.get(key) for key in
                                                       ("outcome", "classification", "reason")},
            "seats": seats}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True, help="new output directory")
    parser.add_argument("--history-decisions", type=int, default=1)
    parser.add_argument("--max-prompt-bytes", type=int, default=64_000)
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    report = {"kind": "offline-recorded-Magic-path-preflight", "network_requests": 0,
              "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
              "python": platform.python_version(), "gpu_ordinal": None,
              "linker": "not applicable: Python",
              "tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "history_decisions": args.history_decisions, "max_prompt_bytes": args.max_prompt_bytes,
              "non_claims": ["recorded scripted choices, not Luna gameplay", "no token or allowance estimate",
                             "no live-engine replay or playing-strength evidence", "no sandbox-confinement claim"]}
    status = 0
    report["games"] = []
    try:
        for path in args.transcript:
            report["current_transcript"] = str(path.resolve())
            report["games"].append(check(path, history=args.history_decisions, max_bytes=args.max_prompt_bytes))
        report.pop("current_transcript")
        report["status"] = "pass"
    except Exception as exc:
        report.update(status="fail", failure_type=type(exc).__name__)
        status = 2
    (output / "manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
