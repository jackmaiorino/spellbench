"""One-shot service forfeits and preserved mapped precommit recovery."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from spellbench.llm.budget_transfer import continue_stopped_qualification, digest
from spellbench.llm.provider import Completion, ProviderError
from spellbench.llm.run_budget import BudgetedProvider, INHERITED_NAMES, LIMIT_NAMES, RunBudget
from test_llm_budget_transfer import transfer
from test_llm_run_budget import PROMPT, Provider, budget, failed_run_recovery


def stopped(tmp_path, *, suffix="recovery", mutate=None, no_cutoff=True):
    original = budget(tmp_path, requests=12, tokens=100_000)
    with pytest.raises(ProviderError):
        BudgetedProvider(Provider(ProviderError("inference_failed")), original).complete(PROMPT, timeout_s=2)
    continued, _, _ = failed_run_recovery(original, tmp_path / "prior.sqlite3", tmp_path, no_cutoff=no_cutoff)
    BudgetedProvider(Provider(Completion("{}", "luna", 100, 20)), continued).complete(PROMPT, timeout_s=2)
    source = transfer(tmp_path, continued)
    with pytest.raises(ProviderError, match="http_503"):
        BudgetedProvider(Provider(ProviderError("http_503")), source).complete(PROMPT, timeout_s=2)
    source.fail("hosted_broker_failed")
    return source, evidence(source, suffix=suffix, mutate=mutate)


def evidence(source, *, suffix="recovery", mutate=None):
    root = source.path.parent
    summary = source.summary()
    completion = root / (suffix + "-completion.json")
    completion.write_text(json.dumps(dict(exit_code=1, formal_dispatches=0, budget_after=summary)))
    row = dict(id=2, status="failed", error="http_503", reserved_tokens=PROMPT.bytes + 1024,
               input_tokens=None, output_tokens=None)
    record = dict(schema="spellbench-llm-stopped-qualification/v1", phase="precommit-qualification",
                  source="a" * 40, model="luna", parent=source.paths.key(source.path), parent_sha256=digest(source.path),
                  parent_map=str(source.paths.manifest), parent_map_sha256=source.paths.sha256,
                  completion=str(completion), completion_sha256=digest(completion), failed_row=row,
                  limits={name: summary["policy"][name] for name in LIMIT_NAMES},
                  effective_deadline=summary["effective_deadline"], owned_processes_absent=True,
                  formal_started=False, public_commitment=None, allow_http503_forfeits=True,
                  user_authority="Existing bounded assignment permits repaired precommit qualification; no request retry")
    if mutate:
        mutate(record)
    receipt = root / (suffix + "-receipt.json")
    receipt.write_text(json.dumps(record))
    return dict(receipt=receipt, receipt_sha256=digest(receipt))


def recover(source, proof, *, suffix="recovery"):
    leaf, manifest = source.path.parent / (suffix + ".sqlite3"), source.path.parent / (suffix + "-map.json")
    continue_stopped_qualification(source, leaf, manifest, **proof)
    return RunBudget(leaf, model="luna", path_map=manifest, path_map_sha256=digest(manifest),
                     expected_limits={"allow_http503_forfeits": True})


def test_stopped_precommit_carries_all_charges_and_retires_one_writer(tmp_path):
    source, proof = stopped(tmp_path)
    before, retained, mapping = source.summary(), source.path.read_bytes(), source.paths.manifest.read_bytes()
    child = recover(source, proof)
    child.check()
    after = child.summary()
    assert child.qualification_origin() == child.path.resolve()
    assert all(after[name] == before[name] for name in (*INHERITED_NAMES, "accounted_tokens"))
    assert all(after["policy"][name] == before["policy"][name] for name in (*LIMIT_NAMES, "created_at", "deadline"))
    assert after["effective_deadline"] is None and after["policy"]["allow_http503_forfeits"] is True
    assert after["active_terminal_failures"] == after["active_http503_forfeits"] == 0
    assert source.path.read_bytes() == retained and source.paths.manifest.read_bytes() == mapping
    with pytest.raises(ProviderError, match="run_budget_attempt_continued"):
        source.reserve(PROMPT, output_tokens=20)
    BudgetedProvider(Provider(Completion("{}", "luna", 5, 2)), child).complete(PROMPT, timeout_s=2)
    assert child.summary()["requests"] == before["requests"] + 1
    assert child.summary()["accounted_tokens"] == before["accounted_tokens"] + 7


def test_recovery_preserves_finite_cutoff_and_can_relocate_with_all_proofs(tmp_path):
    source, proof = stopped(tmp_path, no_cutoff=False)
    before = source.summary()
    child = recover(source, proof)
    assert child.summary()["effective_deadline"] == before["effective_deadline"]
    child_summary = child.summary()
    location = tmp_path / "second-host"
    location.mkdir()
    relocated = transfer(location, child)
    relocated.check()
    assert relocated.summary() == child_summary
    with pytest.raises(ProviderError, match="http_503"):
        BudgetedProvider(Provider(ProviderError("http_503")), relocated).complete(PROMPT, timeout_s=2)
    relocated.check()
    assert relocated.summary()["active_http503_forfeits"] == 1


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(formal_started=True), lambda r: r.update(public_commitment="already-committed"),
    lambda r: r.update(owned_processes_absent=False), lambda r: r.update(effective_deadline=123),
    lambda r: r["limits"].update(max_requests=100), lambda r: r.update(parent_sha256="0" * 64),
    lambda r: r.update(parent_map_sha256="0" * 64), lambda r: r.update(completion_sha256="0" * 64),
    lambda r: r["failed_row"].update(reserved_tokens=1), lambda r: r["failed_row"].update(error="http_429"),
    lambda r: r.update(allow_http503_forfeits=False), lambda r: r.update(user_authority=""),
])
def test_invalid_stopped_receipt_cannot_activate_or_retire_parent(tmp_path, mutation):
    source, proof = stopped(tmp_path, mutate=mutation)
    before = source.path.read_bytes()
    with pytest.raises(ProviderError, match="run_budget_qualification_recovery_changed"):
        recover(source, proof)
    assert source.path.read_bytes() == before
    assert not source.path.with_name(source.path.name + ".continuation.json").exists()


@pytest.mark.parametrize("target", ["receipt", "completion", "map", "parent"])
def test_admission_rechecks_every_retained_failure_binding(tmp_path, target):
    source, proof = stopped(tmp_path)
    child = recover(source, proof)
    path = {"receipt": proof["receipt"], "completion": source.path.parent / "recovery-completion.json",
            "map": source.paths.manifest, "parent": source.path}[target]
    with path.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ProviderError, match="run_budget_transfer_changed"):
        child.reserve(PROMPT, output_tokens=20)


@pytest.mark.parametrize("collision", ["leaf", "origin", "snapshot", "map", "overlap"])
def test_recovery_outputs_cannot_overwrite_prior_evidence(tmp_path, collision):
    source, proof = stopped(tmp_path)
    leaf, manifest = source.path.parent / "recovery.sqlite3", source.path.parent / "recovery-map.json"
    path = {"leaf": leaf, "origin": leaf.with_name(leaf.name + ".continuation-origin.json"),
            "snapshot": leaf.with_name(leaf.name + ".initial.sqlite3"), "map": manifest, "overlap": leaf}[collision]
    if collision == "overlap":
        manifest = path
    else:
        path.write_bytes(b"retained")
    with pytest.raises(ValueError):
        continue_stopped_qualification(source, leaf, manifest, **proof)
    if collision != "overlap":
        assert path.read_bytes() == b"retained"
    assert not source.path.with_name(source.path.name + ".continuation.json").exists()


def test_concurrent_recoveries_select_exactly_one_successor(tmp_path):
    source, first = stopped(tmp_path, suffix="one")
    second = evidence(source, suffix="two")
    def attempt(item):
        suffix, proof = item
        try:
            recover(source, proof, suffix=suffix)
            return "selected"
        except ProviderError:
            return "refused"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, (("one", first), ("two", second)))) == ["refused", "selected"]


@pytest.mark.parametrize("after_write", [False, True])
def test_interrupted_retirement_never_publishes_admission_map(tmp_path, monkeypatch, after_write):
    from spellbench.llm import run_budget
    source, proof = stopped(tmp_path)
    original = run_budget._write_marker
    def write(path, value):
        if path == source.path.with_name(source.path.name + ".continuation.json"):
            if after_write:
                original(path, value)
            raise OSError("interrupted")
        original(path, value)
    monkeypatch.setattr(run_budget, "_write_marker", write)
    with pytest.raises(ProviderError, match="run_budget_unavailable"):
        recover(source, proof)
    assert not (source.path.parent / "recovery-map.json").exists()
    with pytest.raises(ProviderError):
        source.check()


def test_http503_is_charged_once_and_failed_broker_cannot_retry(tmp_path):
    state = budget(tmp_path, allow_http503_forfeits=True)
    provider = Provider(ProviderError("http_503"))
    one_game = BudgetedProvider(provider, state)
    with pytest.raises(ProviderError, match="http_503"):
        one_game.complete(PROMPT, timeout_s=2)
    with pytest.raises(ProviderError, match="provider_already_failed"):
        one_game.complete(PROMPT, timeout_s=2)
    state.check()
    summary = state.summary()
    assert provider.calls == 1 and summary["requests"] == summary["failed"] == summary["active_http503_forfeits"] == 1
    assert summary["uncertain_reserved_tokens"] == PROMPT.bytes + 1024
    assert summary["accounted_tokens"] == summary["uncertain_reserved_tokens"] and summary["pending"] == 0
    BudgetedProvider(Provider(Completion("{}", "luna", 10, 2)), state).complete(PROMPT, timeout_s=2)
    assert state.summary()["requests"] == 2


@pytest.mark.parametrize("code", ["timeout", "http_429", "http_500", "http_502", "http_504",
                                  "profile_renewal_failed", "invalid_provider_result", "provider_internal_error"])
def test_service_policy_does_not_relax_other_failures(tmp_path, code):
    state = budget(tmp_path, allow_http503_forfeits=True)
    provider = Provider(ProviderError(code))
    with pytest.raises(ProviderError, match=code):
        BudgetedProvider(provider, state).complete(PROMPT, timeout_s=2)
    with pytest.raises(ProviderError, match="run_budget_already_failed"):
        state.check()
    assert state.summary()["active_http503_forfeits"] == 0 and provider.calls == 1
