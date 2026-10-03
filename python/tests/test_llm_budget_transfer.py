"""A relocation retires one writer and carries every settled charge forward."""

import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from spellbench.llm.budget_transfer import continue_host_preflight, digest, export_budget, increase_failed_run_limits
from spellbench.llm.provider import Completion, ProviderError
from spellbench.llm.run_budget import BudgetedProvider, RunBudget, check_hosted_budgets, LIMIT_NAMES, LIMIT_INCREASE_SCHEMA
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


def host_failure(tmp_path):
    parent = budget(tmp_path, requests=4, tokens=4000, max_inflight=1)
    with pytest.raises(ProviderError):
        BudgetedProvider(Provider(ProviderError("inference_failed")), parent).complete(PROMPT, timeout_s=2)
    source, _, _ = failed_run_recovery(parent, tmp_path / "successor.sqlite3", tmp_path, no_cutoff=True)
    relocated = transfer(tmp_path, source)
    relocated.fail("profile_renewal_failed")
    return relocated


def recover_host(source):
    leaf = source.path.parent / "host-recovered.sqlite3"
    manifest = continue_host_preflight(source, leaf, source.path.parent / "host-recovered-map.json")
    return RunBudget(leaf, model=source.model, path_map=manifest, path_map_sha256=digest(manifest))


def test_host_preflight_recovery_retains_history_caps_and_exclusive_ancestry(tmp_path):
    source = host_failure(tmp_path)
    before, original = source.summary(), source.path.read_bytes()
    child = recover_host(source)
    after = child.summary()
    assert source.path.read_bytes() == original
    assert after["requests"] == before["requests"] == 1
    assert after["accounted_tokens"] == before["accounted_tokens"]
    assert after["unknown_usage"] == before["unknown_usage"] == 1
    assert after["host_failures"] == before["host_failures"]
    assert after["effective_deadline"] is None
    assert after["policy"]["terminal_error"] is None
    for name in ("max_requests", "max_reported_tokens", "max_inflight", "created_at", "deadline"):
        assert after["policy"][name] == before["policy"][name]
    assert child.paths.key(child.qualification_origin()) == str((tmp_path / "run.sqlite3").resolve())
    with pytest.raises(ProviderError, match="run_budget_attempt_continued"):
        source.check()
    request, _ = child.reserve(PROMPT, output_tokens=20)
    with pytest.raises(ProviderError, match="run_budget_concurrency_exhausted"):
        child.reserve(PROMPT, output_tokens=20)
    child.finish(request, result=Completion("{}", child.model, 10, 2), elapsed_ms=1)
    assert child.summary()["requests"] == 2
    assert child.summary()["accounted_tokens"] == before["accounted_tokens"] + 12


@pytest.mark.parametrize("cause", ["inference_failed", "request_exists"])
def test_host_preflight_recovery_cannot_repeat_inference(tmp_path, cause):
    source = budget(tmp_path)
    relocated = transfer(tmp_path, source)
    if cause == "request_exists":
        BudgetedProvider(Provider(Completion("{}", source.model, 10, 2)), relocated).complete(PROMPT, timeout_s=2)
    relocated.fail("profile_renewal_failed" if cause == "request_exists" else cause)
    with pytest.raises(ProviderError, match="run_budget_parent_not_host_preflight"):
        recover_host(relocated)
    assert not (relocated.path.parent / "host-recovered.sqlite3").exists()


def test_host_recovery_failed_retirement_cannot_publish_activation(tmp_path, monkeypatch):
    from spellbench.llm import run_budget
    source = host_failure(tmp_path)
    original = run_budget._write_marker
    def write(path, value):
        if path == source.path.with_name(source.path.name + ".continuation.json"):
            raise OSError("parent retirement failed")
        original(path, value)
    monkeypatch.setattr(run_budget, "_write_marker", write)
    with pytest.raises(ProviderError, match="run_budget_unavailable"):
        recover_host(source)
    assert not (source.path.parent / "host-recovered-map.json").exists()
    assert source.summary()["policy"]["terminal_error"] == "profile_renewal_failed"


def test_host_recovery_map_cannot_detach_original_transferred_ancestor(tmp_path):
    source = host_failure(tmp_path)
    child = recover_host(source)
    # An alternate root with matching settings is still outside the retired
    # source's verified ancestry, even with a newly bound map hash.
    with sqlite3.connect(child.path) as database:
        policy = json.loads(database.execute("SELECT json FROM policy").fetchone()[0])
        policy.pop("continuation")
        policy["schema"] = "spellbench-llm-run-budget/v1"
        database.execute("UPDATE policy SET json=?", (json.dumps(policy),))
    from spellbench.llm.run_budget import _origin
    _origin(child.path).unlink()
    shutil.copyfile(child.path, child.paths.snapshot)
    value = json.loads(child.paths.manifest.read_bytes())
    value["immutable"].pop(_origin(child.path).relative_to(child.path.parent).as_posix())
    value["immutable"][child.paths.snapshot.relative_to(child.path.parent).as_posix()] = digest(child.paths.snapshot)
    child.paths.manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ProviderError, match="run_budget_transfer_changed"):
        RunBudget(child.path, model=child.model, path_map=child.paths.manifest,
                  path_map_sha256=digest(child.paths.manifest))


def test_present_transfer_anchor_cannot_erase_inherited_usage_with_new_hashes(tmp_path):
    from spellbench.llm.run_budget import _origin, _successor_claim, INHERITED_NAMES
    source = host_failure(tmp_path)
    child = recover_host(source)
    # Rebind every new map/claim to a replacement zero-request root at the
    # same anchor filename. The original transfer snapshot/proof stay intact.
    with sqlite3.connect(source.path) as database:
        prior = json.loads(database.execute("SELECT json FROM policy").fetchone()[0])
        prior.pop("continuation")
        prior["schema"] = "spellbench-llm-run-budget/v1"
        database.execute("UPDATE policy SET json=?", (json.dumps(prior),))
    with sqlite3.connect(child.path) as database:
        policy = json.loads(database.execute("SELECT json FROM policy").fetchone()[0])
        policy["continuation"].pop("no_cutoff")
        policy["continuation"]["parent_sha256"] = digest(source.path)
        policy["continuation"]["inherited"] = dict.fromkeys(INHERITED_NAMES, 0)
        policy["continuation"]["inherited"]["host_failures"] = 1
        database.execute("UPDATE policy SET json=?", (json.dumps(policy),))
    claim = {"successor": str(child.path.resolve()), "parent_sha256": digest(source.path),
             "policy": {key: item for key, item in policy.items() if key != "terminal_error"}}
    for path in (_origin(child.path), _successor_claim(source.path)):
        path.write_text(json.dumps(claim), encoding="utf-8")
    shutil.copyfile(child.path, child.paths.snapshot)
    value = json.loads(child.paths.manifest.read_bytes())
    for path in (source.path, _origin(child.path), _successor_claim(source.path), child.paths.snapshot):
        value["immutable"][path.relative_to(child.path.parent).as_posix()] = digest(path)
    child.paths.manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ProviderError, match="run_budget_transfer_changed"):
        RunBudget(child.path, model=child.model, path_map=child.paths.manifest,
                  path_map_sha256=digest(child.paths.manifest))


def increase_evidence(source, *, suffix="increase", limits=None, mutation=None):
    root = source.paths.manifest.parent
    before = source.summary()
    old = {name: before["policy"][name] for name in LIMIT_NAMES}
    new = limits or {**old, "max_requests": old["max_requests"] * 2,
                    "max_reported_tokens": old["max_reported_tokens"] * 2}
    retained = root / (suffix + "-aborted.json")
    retained.write_text(json.dumps({"schema": "spellbench-tournament/v2",
        "protocol": {"name": "spellbench/v2"}, "run": {"status": "aborted", "rated": False}}))
    receipt = root / (suffix + "-receipt.json")
    receipt.write_text(json.dumps({"schema": "spellbench-llm-failed-run-recovery/v1",
        "parent": source.paths.key(source.path), "parent_sha256": digest(source.path),
        "effective_deadline": before["effective_deadline"], "purpose": "fixed-panel-rerun",
        "retained_run_manifest": str(retained.resolve()), "retained_run_sha256": digest(retained)}))
    authority = root / (suffix + "-authority.json")
    record = {"schema": LIMIT_INCREASE_SCHEMA, "model": source.model,
        "parent": source.paths.key(source.path), "parent_sha256": digest(source.path),
        "parent_limits": old, "approved_limits": new, "failure_receipt_sha256": digest(receipt),
        "purpose": "fixed-panel-rerun", "user_authority": "Approved unchanged panel and cumulative caps."}
    if mutation:
        mutation(record)
    authority.write_text(json.dumps(record))
    return dict(approved_limits=new, failure_receipt=receipt, failure_receipt_sha256=digest(receipt),
                authority=authority, authority_sha256=digest(authority))


def increase(source, *, suffix="increase", **evidence):
    leaf = source.path.parent / (suffix + ".sqlite3")
    manifest = source.path.parent / (suffix + "-map.json")
    increase_failed_run_limits(source, leaf, manifest, **evidence)
    return RunBudget(leaf, model=source.model, path_map=manifest, path_map_sha256=digest(manifest),
                     expected_limits=evidence["approved_limits"])


def test_approved_increase_preserves_multihost_history_and_requires_new_qualification(tmp_path):
    source = host_failure(tmp_path)
    before, parent_bytes = source.summary(), source.path.read_bytes()
    child = increase(source, **increase_evidence(source))
    after = child.summary()
    for name in ("requests", "accounted_tokens", "unknown_usage", "pending", "host_failures"):
        assert after[name] == before[name]
    assert after["effective_deadline"] is None
    assert child.qualification_origin() == child.path.resolve()
    assert source.path.read_bytes() == parent_bytes
    with pytest.raises(ProviderError, match="run_budget_attempt_continued"):
        source.check()
    BudgetedProvider(Provider(Completion("{}", child.model, 10, 2)), child).complete(PROMPT, timeout_s=2)
    assert child.summary()["requests"] == before["requests"] + 1
    assert child.summary()["accounted_tokens"] == before["accounted_tokens"] + 12
    assert child.summary()["unknown_usage"] == before["unknown_usage"] == 1
    # A subsequent relocation must retain both sides of the cap boundary.
    nested = tmp_path / "next-host"
    nested.mkdir()
    before_transfer = child.summary()
    relocated = transfer(nested, child)
    assert relocated.summary() == before_transfer
    assert relocated.paths.key(relocated.qualification_origin()) == str(child.path.resolve())
    assert any(path.name == "authority.json" for path in relocated.paths.files.values())
    relocated.check()


def test_host_recovery_after_increase_keeps_new_caps_and_qualification_identity(tmp_path):
    source = host_failure(tmp_path)
    child = increase(source, **increase_evidence(source))
    child.fail("profile_renewal_failed")
    recovered = recover_host(child)
    assert recovered.qualification_origin() == child.path.resolve()
    assert recovered.summary()["policy"]["max_reported_tokens"] == 8000
    assert recovered.summary()["policy"]["max_requests"] == 8
    assert recovered.summary()["requests"] == 1
    recovered.check()


@pytest.mark.parametrize("mutation", [
    lambda record: record["parent_limits"].update(max_requests=3),
    lambda record: record.update(model="another-model"),
    lambda record: record.update(parent_sha256="0" * 64),
    lambda record: record.update(failure_receipt_sha256="0" * 64),
    lambda record: record.update(user_authority=""),
])
def test_increase_refuses_authority_not_bound_to_actual_parent(tmp_path, mutation):
    source = host_failure(tmp_path)
    evidence = increase_evidence(source, mutation=mutation)
    with pytest.raises(ProviderError, match="run_budget_limit_increase_changed"):
        increase(source, **evidence)
    assert not (source.path.parent / "increase-map.json").exists()
    assert not source.path.with_name(source.path.name + ".continuation.json").exists()


@pytest.mark.parametrize("change", [
    {"max_requests": 4, "max_reported_tokens": 4000},
    {"max_requests": 3}, {"max_inflight": 2}, {"max_wall_seconds": 9999},
    {"max_requests": True},
])
def test_increase_cannot_decrease_reset_or_change_other_limits(tmp_path, change):
    source = host_failure(tmp_path)
    old = {name: source.summary()["policy"][name] for name in LIMIT_NAMES}
    evidence = increase_evidence(source, limits={**old, "max_requests": 8, "max_reported_tokens": 8000, **change})
    with pytest.raises((ProviderError, ValueError)):
        increase(source, **evidence)
    assert not (source.path.parent / "increase-map.json").exists()


@pytest.mark.parametrize("target", ["authority", "failure_receipt", "aborted_manifest", "old_parent"])
def test_increase_admission_rechecks_retained_authority_and_failure(tmp_path, target):
    source = host_failure(tmp_path)
    evidence = increase_evidence(source)
    child = increase(source, **evidence)
    path = {"authority": evidence["authority"], "failure_receipt": evidence["failure_receipt"],
            "aborted_manifest": source.path.parent / "increase-aborted.json", "old_parent": source.path}[target]
    with path.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ProviderError, match="run_budget_transfer_changed"):
        child.reserve(PROMPT, output_tokens=20)


def test_concurrent_increases_select_only_one_successor(tmp_path):
    source = host_failure(tmp_path)
    evidence = [increase_evidence(source, suffix=f"increase-{index}") for index in range(2)]
    def attempt(index):
        try:
            increase(source, suffix=f"increase-{index}", **evidence[index])
            return "selected"
        except ProviderError:
            return "refused"
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(attempt, (0, 1))) == ["refused", "selected"]


@pytest.mark.parametrize("after_write", [False, True])
def test_interrupted_increase_never_publishes_an_admitting_map(tmp_path, monkeypatch, after_write):
    from spellbench.llm import run_budget
    source = host_failure(tmp_path)
    evidence = increase_evidence(source)
    original = run_budget._write_marker
    def write(path, value):
        if path == source.path.with_name(source.path.name + ".continuation.json"):
            if after_write:
                original(path, value)
            raise OSError("interrupted retirement")
        original(path, value)
    monkeypatch.setattr(run_budget, "_write_marker", write)
    with pytest.raises(ProviderError, match="run_budget_unavailable"):
        increase(source, **evidence)
    assert not (source.path.parent / "increase-map.json").exists()
    if after_write:
        with pytest.raises(ProviderError, match="run_budget_attempt_continued"):
            source.check()
    else:
        assert source.summary()["policy"]["terminal_error"] == "profile_renewal_failed"


@pytest.mark.parametrize("pending", [False, True])
def test_healthy_or_unsettled_parent_cannot_start_an_increased_panel(tmp_path, pending):
    source = host_failure(tmp_path)
    healthy = increase(source, **increase_evidence(source))
    if pending:
        healthy.reserve(PROMPT, output_tokens=20)
        healthy.fail("hosted_broker_failed")
    evidence = increase_evidence(healthy, suffix="second")
    with pytest.raises(ProviderError, match="run_budget_unresolved_request" if pending else "run_budget_parent_not_failed"):
        increase(healthy, suffix="second", **evidence)
    assert not (source.path.parent / "second-map.json").exists()


def test_rebound_increase_cannot_remove_a_finite_parent_cutoff(tmp_path, monkeypatch):
    from spellbench.llm.run_budget import _origin, _successor_claim
    source = transfer(tmp_path, budget(tmp_path))
    source.fail("hosted_broker_failed")
    original_cutoff = source.summary()["effective_deadline"]
    # Construct the formerly accepted boundary, bypassing only the creation
    # check. Then bind all records to the actual finite parent cutoff.
    monkeypatch.setattr(source, "_effective_deadline", lambda policy: None)
    evidence = increase_evidence(source)
    leaf, manifest = source.path.parent / "increase.sqlite3", source.path.parent / "increase-map.json"
    increase_failed_run_limits(source, leaf, manifest, **evidence)
    receipt = evidence["failure_receipt"]
    value = json.loads(receipt.read_bytes())
    value["effective_deadline"] = original_cutoff
    receipt.write_text(json.dumps(value))
    authority = evidence["authority"]
    value = json.loads(authority.read_bytes())
    value["failure_receipt_sha256"] = digest(receipt)
    authority.write_text(json.dumps(value))
    with sqlite3.connect(leaf) as database:
        policy = json.loads(database.execute("SELECT json FROM policy").fetchone()[0])
        policy["continuation"]["recovery"]["receipt_sha256"] = digest(receipt)
        policy["continuation"]["limit_increase"]["authority_sha256"] = digest(authority)
        database.execute("UPDATE policy SET json=?", (json.dumps(policy),))
    claim = {"successor": str(leaf.resolve()), "parent_sha256": digest(source.path),
             "policy": {key: item for key, item in policy.items() if key != "terminal_error"}}
    for marker in (_origin(leaf), _successor_claim(source.path)):
        marker.write_text(json.dumps(claim))
    snapshot = leaf.with_name(leaf.name + ".initial.sqlite3")
    shutil.copyfile(leaf, snapshot)
    value = json.loads(manifest.read_bytes())
    for path in (receipt, authority, _origin(leaf), _successor_claim(source.path), snapshot):
        value["immutable"][path.relative_to(manifest.parent).as_posix()] = digest(path)
    manifest.write_text(json.dumps(value))
    with pytest.raises(ProviderError, match="run_budget_limit_increase_changed"):
        RunBudget(leaf, model=source.model, path_map=manifest, path_map_sha256=digest(manifest))
