"""Protocol v1 code is gone, no migration skip is left, and v2 text carries no em-dash."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

import spellbench

REPO = Path(__file__).resolve().parents[2]
EM_DASH = "\u2014"
K2_SKIP = "the kernel bot speaks protocol v1; K2 ports it to spellbench.bot"


@pytest.mark.parametrize("module", ["spellbench.models", "spellbench.engine_client", "spellbench.agent_client",
                                    "spellbench.agent_server", "spellbench._client", "spellbench.arena.bots"])
def test_v1_modules_are_gone(module: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


def _module_level_skips(path: Path) -> list[str]:
    """The messages of a test module's module-level pytest.skip calls, found with ast, so this module never matches itself (R3-1)."""
    messages = []
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        call = node.value if isinstance(node, ast.Expr) else None
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "skip"
                and call.args and isinstance(call.args[0], ast.Constant)):
            messages.append(call.args[0].value)
    return messages


def test_the_only_module_level_skips_left_are_the_kernel_bots_for_k2() -> None:
    modules = [path for root in (REPO / "python" / "tests", REPO / "integrations") if root.is_dir()
               for path in sorted(root.rglob("test_*.py"))]
    left = {path.relative_to(REPO).as_posix(): _module_level_skips(path) for path in modules if _module_level_skips(path)}
    expected = {path.relative_to(REPO).as_posix(): [K2_SKIP] for path in modules if path.relative_to(REPO).parts[0] == "integrations"}
    assert left == expected          # no migration skip is left; sub-project C's kernel-bot modules wait for K2 (R3-18)


def test_the_version_and_the_exports() -> None:
    assert spellbench.__version__ == "0.3.0"
    assert spellbench.serve is spellbench.bot.serve and spellbench.EngineProcess.__module__ == "spellbench.host.engine_process"


def test_no_em_dash_in_v2_text() -> None:
    roots = [REPO / "python", REPO / "goldens" / "protocol_v2", REPO / "examples", REPO / "README.md",
             REPO / "benchmarks" / "pauper-kernel" / "benchmark.json"]
    files = [p for root in roots for p in ([root] if root.is_file() else root.rglob("*"))
             if p.is_file() and p.suffix in {".py", ".md", ".json", ".jsonl"} and "__pycache__" not in p.parts]
    assert [str(p.relative_to(REPO)) for p in files if EM_DASH in p.read_text(encoding="utf-8")] == []
