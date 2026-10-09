"""Independent settled debits constrain the same cumulative admission budget."""

import json
import shutil
import sqlite3

import pytest

from spellbench.llm.budget_transfer import amend_idle_budget, digest
from spellbench.llm.provider import Completion, ProviderError
from spellbench.llm.run_budget import (INHERITED_NAMES, LIMIT_NAMES, IDLE_AMENDMENT_SCHEMA,
                                      RunBudget, debit_ancestry_paths, sealed_debit_imports)
from test_llm_budget_transfer import idle_amend, idle_authority, transfer
from test_llm_run_budget import PROMPT, budget


def setup(tmp_path, **limits):
    source = transfer(tmp_path, budget(tmp_path / "primary", **limits))
    request, _ = source.reserve(PROMPT, output_tokens=20)
    source.finish(request, result=Completion("{}", source.model, 10, 2), elapsed_ms=1)
    donors = []
    for index, unknown in enumerate((False, True)):
        donor = budget(source.path.parent / f"smoke-{index}")
        request, _ = donor.reserve(PROMPT, output_tokens=20)
        donor.finish(request, result=None if unknown else Completion("{}", source.model, 20, 3),
                     elapsed_ms=1, error="http_503" if unknown else None)
        donor.fail("hosted_broker_failed")
        donors.append(donor.path)
    return source, donors


def evidence(source, donors, *, suffix="consolidated", mutate=None):
    imports = sealed_debit_imports(donors, model=source.model,
                                  forbidden_paths=debit_ancestry_paths(source.path, source.paths))
    limits = {name: source.summary()["policy"][name] for name in LIMIT_NAMES}
    record = {"schema": IDLE_AMENDMENT_SCHEMA, "model": source.model,
              "parent": source.paths.key(source.path), "parent_sha256": digest(source.path),
              "parent_limits": limits, "approved_limits": limits, "no_cutoff": True,
              "purpose": "precommit-evaluation", "user_authority": "Approved carry-forward of these debits",
              "debit_imports": imports}
    if mutate:
        mutate(record)
    authority = source.path.parent / f"{suffix}-authority.json"
    authority.write_text(json.dumps(record), encoding="utf-8")
    return dict(approved_limits=limits, authority=authority, authority_sha256=digest(authority),
                no_cutoff=True, debit_ledgers=donors)


def consolidate(source, donors, *, suffix="consolidated", prepared=None):
    manifest = source.path.parent / f"{suffix}-map.json"
    successor = source.path.parent / f"{suffix}.sqlite3"
    amend_idle_budget(source, successor, manifest, **(prepared or evidence(source, donors, suffix=suffix)))
    return RunBudget(successor, model=source.model, path_map=manifest, path_map_sha256=digest(manifest))


def test_consolidation_preserves_bytes_unknown_debits_and_limits_across_relocation(tmp_path):
    source, donors = setup(tmp_path)
    retained = {path: path.read_bytes() for path in (source.path, *donors)}
    before = source.summary()
    child = consolidate(source, donors)
    after = child.summary()
    assert after["requests"] == 3 and after["accounted_tokens"] == 65
    assert after["unknown_usage"] == 1 and after["uncertain_reserved_tokens"] == 30
    assert after["failed"] == 1 and after["host_failures"] == 2 and after["active_failed"] == 0
    assert after["effective_deadline"] is None
    for name in LIMIT_NAMES:
        assert after["policy"][name] == before["policy"][name]
    assert all(path.read_bytes() == data for path, data in retained.items())
    with pytest.raises(ProviderError, match="run_budget_attempt_continued"):
        source.reserve(PROMPT, output_tokens=20)
    request, _ = child.reserve(PROMPT, output_tokens=20)
    child.finish(request, result=Completion("{}", child.model, 5, 2), elapsed_ms=1)
    assert child.summary()["requests"] == 4 and child.summary()["accounted_tokens"] == 72
    child = idle_amend(child, suffix="later-phase", **idle_authority(child, suffix="later-phase"))
    assert child.summary()["requests"] == 4 and child.summary()["accounted_tokens"] == 72
    assert child.summary()["unknown_usage"] == 1
    before_transfer = child.summary()
    again = tmp_path / "again"
    again.mkdir()
    relocated = transfer(again, child)
    assert relocated.summary() == before_transfer
    with pytest.raises(ProviderError, match="run_budget_attempt_continued"):
        child.reserve(PROMPT, output_tokens=20)


@pytest.mark.parametrize("limit", [{"requests": 2}, {"tokens": 64}])
def test_imported_requests_and_unknown_reservations_cannot_exceed_existing_caps(tmp_path, limit):
    source, donors = setup(tmp_path, **limit)
    with pytest.raises(ProviderError, match="run_budget_exhausted"):
        consolidate(source, donors)
    assert not (source.path.parent / "consolidated.sqlite3").exists()
    assert not source.path.with_name(source.path.name + ".continuation.json").exists()


@pytest.mark.parametrize("target", ["donor", "authority", "snapshot"])
def test_every_admission_rechecks_imported_sources_and_authority(tmp_path, target):
    source, donors = setup(tmp_path)
    prepared = evidence(source, donors)
    child = consolidate(source, donors, prepared=prepared)
    path = {"donor": donors[0], "authority": prepared["authority"], "snapshot": child.paths.snapshot}[target]
    with path.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ProviderError, match="run_budget_transfer_changed"):
        child.reserve(PROMPT, output_tokens=20)


@pytest.mark.parametrize("mutation", [
    lambda record: record.pop("debit_imports"),
    lambda record: record["debit_imports"][0]["totals"].update(requests=0),
    lambda record: record.update(user_authority=""),
])
def test_authority_must_approve_exact_imported_debit_scope(tmp_path, mutation):
    source, donors = setup(tmp_path)
    prepared = evidence(source, donors, mutate=mutation)
    with pytest.raises(ProviderError, match="run_budget_idle_amendment_changed"):
        consolidate(source, donors, prepared=prepared)
    assert not source.path.with_name(source.path.name + ".continuation.json").exists()
    assert not (source.path.parent / "consolidated.sqlite3").exists()


@pytest.mark.parametrize("overlap", ["same_path", "same_bytes", "changed_policy", "ancestor_rows", "previous_import"])
def test_duplicate_copied_and_inherited_debits_are_not_counted_twice(tmp_path, overlap):
    source, donors = setup(tmp_path)
    if overlap == "previous_import":
        source = consolidate(source, donors)
        selected = [donors[0]]
    elif overlap == "same_path":
        selected = [donors[0], donors[0]]
    else:
        copied = source.path.parent / "duplicate.sqlite3"
        origin = source.path if overlap == "ancestor_rows" else donors[0]
        shutil.copyfile(origin, copied)
        if overlap in {"changed_policy", "ancestor_rows"}:
            with sqlite3.connect(copied) as database:
                policy = json.loads(database.execute("SELECT json FROM policy").fetchone()[0])
                policy.pop("continuation", None)
                policy.update(schema="spellbench-llm-run-budget/v1", terminal_error="hosted_broker_failed")
                database.execute("UPDATE policy SET json=?", (json.dumps(policy),))
        selected = [copied] if overlap == "ancestor_rows" else [donors[0], copied]
    with pytest.raises(ProviderError, match="run_budget_(duplicate|overlapping)_debit_import"):
        evidence(source, selected)
    source.check()


@pytest.mark.parametrize("state", ["pending", "active", "wrong_model", "inherited"])
def test_unsettled_live_foreign_model_and_inherited_sources_are_refused(tmp_path, state):
    source, donors = setup(tmp_path)
    path = donors[0]
    with sqlite3.connect(path) as database:
        policy = json.loads(database.execute("SELECT json FROM policy").fetchone()[0])
        if state == "pending":
            database.execute("UPDATE requests SET status='pending'")
        elif state == "active":
            policy["terminal_error"] = None
        elif state == "wrong_model":
            policy["model"] = "another-model"
        else:
            policy.update(schema="spellbench-llm-run-budget/v2", continuation={"inherited": dict.fromkeys(INHERITED_NAMES, 0)})
        database.execute("UPDATE policy SET json=?", (json.dumps(policy),))
    with pytest.raises(ProviderError):
        evidence(source, donors)
    assert not source.path.with_name(source.path.name + ".continuation.json").exists()


def test_raw_expiry_cannot_hide_live_extended_donor(tmp_path, monkeypatch):
    import spellbench.llm.run_budget as module
    source, donors = setup(tmp_path)
    donor = budget(source.path.parent / "extended-smoke")
    baseline = donor.summary()["policy"]["deadline"]
    donor.extend_deadline(baseline + 40)
    monkeypatch.setattr(module.time, "time", lambda: baseline + 10)
    donor.check()
    assert donor.summary()["effective_deadline"] > module.time.time()
    with pytest.raises(ProviderError, match="run_budget_debit_import_not_independent"):
        evidence(source, [donor.path])


@pytest.mark.parametrize("suffix", [".continuation.json", ".continuation-origin.json"])
def test_retired_donor_or_transfer_origin_is_not_an_independent_debit(tmp_path, suffix):
    source, donors = setup(tmp_path)
    donors[0].with_name(donors[0].name + suffix).write_text("{}", encoding="utf-8")
    with pytest.raises(ProviderError, match="run_budget_debit_import_not_independent"):
        evidence(source, donors)
