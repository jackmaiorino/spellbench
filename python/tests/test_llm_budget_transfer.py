"""A relocation retires one writer and carries every settled charge forward."""

import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from spellbench.llm.budget_transfer import digest, export_budget
from spellbench.llm.provider import Completion, ProviderError
from spellbench.llm.run_budget import BudgetedProvider, RunBudget, check_hosted_budgets
from test_llm_run_budget import PROMPT, Provider, budget, failed_run_recovery, hosted_config


def transfer(tmp_path, source):
    destination = tmp_path / "cloud" / "ledger"
    destination.parent.mkdir()
    identity = tmp_path / "cloud" / "host-id"
    identity.write_text("test-pod", encoding="utf-8")
    bundle = tmp_path / "export"
    manifest = export_budget(source, bundle, destination=str(destination / "active.sqlite3"),
                             host_identity_file=str(identity), host_identity="test-pod")
    shutil.copytree(bundle, destination)
    relocated = RunBudget(destination / "active.sqlite3", model=source.model,
                          path_map=destination / "map.json", path_map_sha256=digest(manifest))
    return relocated


def test_failed_history_overlay_no_cutoff_and_new_usage_survive_relocation(tmp_path):
    parent = budget(tmp_path, requests=4, tokens=4000, max_inflight=1)
    parent.extend_deadline(parent.summary()["effective_deadline"] + 120)
    with pytest.raises(ProviderError):
        BudgetedProvider(Provider(ProviderError("inference_failed")), parent).complete(PROMPT, timeout_s=2)
    source, _, _ = failed_run_recovery(parent, tmp_path / "successor.sqlite3", tmp_path, no_cutoff=True)
    BudgetedProvider(Provider(Completion("{}", source.model, 10, 2)), source).complete(PROMPT, timeout_s=2)
    before = source.summary()
    original_bytes = source.path.read_bytes()
    relocated = transfer(tmp_path, source)
    assert source.path.read_bytes() == original_bytes
    with pytest.raises(ProviderError, match="run_budget_attempt_continued"):
        source.reserve(PROMPT, output_tokens=20)
    assert relocated.summary() == before
    assert relocated.paths.key(relocated.qualification_origin()) == str(parent.path.resolve())
    request, _ = relocated.reserve(PROMPT, output_tokens=20)
    with pytest.raises(ProviderError, match="run_budget_concurrency_exhausted"):
        relocated.reserve(PROMPT, output_tokens=20)
    relocated.finish(request, result=Completion("{}", source.model, 20, 3), elapsed_ms=1)
    after = relocated.summary()
    assert after["requests"] == before["requests"] + 1
    assert after["accounted_tokens"] == before["accounted_tokens"] + 23
    assert after["unknown_usage"] == before["unknown_usage"] == 1
    assert after["effective_deadline"] is None
    request, _ = relocated.reserve(PROMPT, output_tokens=20)
    relocated.finish(request, result=Completion("{}", source.model, 20, 3), elapsed_ms=1)
    with pytest.raises(ProviderError, match="run_budget_requests_exhausted"):
        relocated.reserve(PROMPT, output_tokens=20)


@pytest.mark.parametrize("target", ["map", "snapshot", "retirement", "prefix", "policy", "identity", "ancestor", "receipt"])
def test_relocated_admission_refuses_changed_retained_evidence(tmp_path, target):
    parent = budget(tmp_path)
    with pytest.raises(ProviderError):
        BudgetedProvider(Provider(ProviderError("inference_failed")), parent).complete(PROMPT, timeout_s=2)
    source, _, _ = failed_run_recovery(parent, tmp_path / "successor.sqlite3", tmp_path, no_cutoff=True)
    BudgetedProvider(Provider(Completion("{}", source.model, 10, 2)), source).complete(PROMPT, timeout_s=2)
    relocated = transfer(tmp_path, source)
    paths = relocated.paths
    if target in {"prefix", "policy"}:
        with sqlite3.connect(relocated.path) as database:
            if target == "prefix":
                database.execute("DELETE FROM requests")
            else:
                policy = json.loads(database.execute("SELECT json FROM policy").fetchone()[0])
                policy["max_requests"] += 1
                database.execute("UPDATE policy SET json=?", (json.dumps(policy),))
    else:
        filename = {"map": paths.manifest, "snapshot": paths.snapshot,
                    "retirement": paths.manifest.parent / "source-retirement.json",
                    "identity": paths.manifest.parent.parent / "host-id",
                    "ancestor": paths.resolve(str(parent.path.resolve())),
                    "receipt": next(path for path in paths.files.values() if path.name == "recovery.json")}[target]
        with filename.open("ab") as stream:
            stream.write(b"changed")
    with pytest.raises(ProviderError, match="run_budget_transfer_changed"):
        relocated.reserve(PROMPT, output_tokens=20)


@pytest.mark.parametrize("mutation", ["escape", "duplicate", "missing", "wrong_destination"])
def test_map_structure_cannot_select_another_copy(tmp_path, mutation):
    source = budget(tmp_path)
    relocated = transfer(tmp_path, source)
    manifest = relocated.paths.manifest
    value = json.loads(manifest.read_bytes())
    if mutation == "escape":
        value["files"][0]["file"] = "../outside.sqlite3"
    elif mutation == "duplicate":
        value["files"].append(value["files"][0])
    elif mutation == "missing":
        value["files"] = []
    else:
        proof = manifest.parent / "source-retirement.json"
        receipt = json.loads(proof.read_bytes())
        receipt["destination"] += "-other"
        proof.write_text(json.dumps(receipt), encoding="utf-8")
        value["immutable"]["source-retirement.json"] = digest(proof)
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ProviderError, match="run_budget_transfer_changed"):
        RunBudget(relocated.path, model=source.model, path_map=manifest, path_map_sha256=digest(manifest))


def test_pending_source_is_not_transferred_or_retired(tmp_path):
    source = budget(tmp_path)
    request, _ = source.reserve(PROMPT, output_tokens=20)
    with pytest.raises(ProviderError, match="run_budget_unresolved_request"):
        export_budget(source, tmp_path / "export", destination="/cloud/active.sqlite3",
                      host_identity_file="/cloud/host-id", host_identity="test-pod")
    assert not source.path.with_name(source.path.name + ".continuation.json").exists()
    source.finish(request, result=Completion("{}", source.model, 10, 2), elapsed_ms=1)
    source.check()


def test_concurrent_exports_select_one_destination(tmp_path):
    source = budget(tmp_path)
    def attempt(index):
        try:
            export_budget(source, tmp_path / f"export-{index}", destination=f"/cloud/{index}/active.sqlite3",
                          host_identity_file="/cloud/host-id", host_identity="test-pod")
            return "selected"
        except ProviderError:
            return "refused"
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(attempt, (0, 1))) == ["refused", "selected"]
    with pytest.raises(ProviderError, match="run_budget_attempt_continued"):
        source.check()


def test_interrupted_after_retirement_never_reopens_source(tmp_path, monkeypatch):
    from spellbench.llm import run_budget
    source = budget(tmp_path)
    original = run_budget._write_marker
    def write(path, value):
        original(path, value)
        if path == source.path.with_name(source.path.name + ".continuation.json"):
            raise OSError("interrupted after durable retirement")
    monkeypatch.setattr(run_budget, "_write_marker", write)
    with pytest.raises(ProviderError, match="run_budget_unavailable"):
        export_budget(source, tmp_path / "export", destination="/cloud/active.sqlite3",
                      host_identity_file="/cloud/host-id", host_identity="test-pod")
    with pytest.raises(ProviderError, match="run_budget_attempt_continued"):
        source.check()
    assert not (tmp_path / "export/map.json").exists()


def test_failed_retirement_does_not_publish_a_cloud_activation_map(tmp_path, monkeypatch):
    from spellbench.llm import run_budget
    source = budget(tmp_path)
    original = run_budget._write_marker
    def write(path, value):
        if path == source.path.with_name(source.path.name + ".continuation.json"):
            raise OSError("source marker write failed before creation")
        original(path, value)
    monkeypatch.setattr(run_budget, "_write_marker", write)
    with pytest.raises(ProviderError, match="run_budget_unavailable"):
        export_budget(source, tmp_path / "export", destination="/cloud/active.sqlite3",
                      host_identity_file="/cloud/host-id", host_identity="test-pod")
    assert not (tmp_path / "export/map.json").exists()
    source.check()


def test_launcher_uses_explicit_map_and_shared_token_cap(tmp_path):
    from dataclasses import replace
    source = budget(tmp_path, tokens=50)
    BudgetedProvider(Provider(Completion("{}", source.model, 10, 2)), source, output_tokens=20).complete(PROMPT, timeout_s=2)
    relocated = transfer(tmp_path, source)
    config = hosted_config(relocated, extra=("--run-budget-map", str(relocated.paths.manifest),
                                            "--run-budget-map-sha256", relocated.paths.sha256,
                                            "--trusted-agent-process"))
    check_hosted_budgets(config)
    with pytest.raises(ProviderError, match="run_budget_tokens_exhausted"):
        relocated.reserve(PROMPT, output_tokens=40)
    bot = replace(config.bots[0], command=config.bots[0].command[:-3])
    with pytest.raises(ProviderError):
        check_hosted_budgets(type(config)(bots=(bot,)))
