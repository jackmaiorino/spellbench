"""Validate v2 runs from their files alone, including invalid and aborted runs (spec 11.3, 11.6, 11.8, 12.2)."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Callable

import pytest

import spellbench
from spellbench.arena import cli, runner, store
from spellbench.arena.allocation import Allocation
from spellbench.arena.manifest import MANIFEST_KEYS
from spellbench.arena import validate
from spellbench.arena.validate import validate_tournament_dir, validate_v2_run
from spellbench.digests import deck_id
from spellbench.run_secret import RunSecret

from arena_helpers import (
    HOSTILE_ENGINE, TEST_RUN_SECRET, builtin, cli_bot, hostile_bot, ledger_rows, make_config, manifest, run,
    subprocess_bot,
)

BOTS = [builtin("uniform", seed=11), builtin("heuristic")]
HASHED = ("COMMITMENT.json", "config.json", "registry.json", "matches.jsonl", "leaderboard.json", "LEADERBOARD.md")
BOARD_JSON = "leaderboard.json does not match a recomputation from matches.jsonl"
BOARD_MD = "LEADERBOARD.md does not match a recomputation from matches.jsonl"
SECRET_FAILURE = "the revealed run secret does not hash to the commitment in secrets.commitment (spec 11.6)"
COMMITTED_FAILURE = "the commitment in COMMITMENT.json is not the SHA-256 of the revealed run secret (spec 11.6)"
FILES_FAILURE = f"manifest files must list exactly {list(HASHED)}, in that order"


def _interrupt_at(index: int) -> Callable[[Any], None]:
    def stop(row) -> None:
        if row.game_index == index:
            raise KeyboardInterrupt

    return stop


@pytest.fixture(scope="module")
def published(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """One run of each kind, made once; every test changes its own copy."""
    root = tmp_path_factory.mktemp("published")
    runs = {name: root / name for name in ("unrated", "rated", "invalid", "aborted")}
    run(make_config(runs["unrated"], BOTS, pairs=2, include_self_play=False))
    run(make_config(runs["rated"], BOTS, pairs=2, include_self_play=False), rated=True)
    run(make_config(runs["invalid"], [builtin("first"), builtin("heuristic")], engine=HOSTILE_ENGINE,
                    engine_args=("stale-reference",), pairs=2))
    with pytest.raises(KeyboardInterrupt):
        run(make_config(runs["aborted"], BOTS, pairs=2, include_self_play=False), on_game=_interrupt_at(1))
    return runs


def _copy(published: dict[str, Path], kind: str, tmp_path: Path) -> Path:
    directory = tmp_path / kind
    shutil.copytree(published[kind], directory)
    return directory


def _rewrite(directory: Path, *, rows=None, edit=None) -> None:
    """Tamper with the run, then refresh the file digests so only the tampering can fail."""
    if rows is not None:
        (directory / "matches.jsonl").write_bytes(b"".join(store.canonical_bytes(row) + b"\n" for row in rows))
    document = manifest(directory)
    if edit is not None:
        edit(document)
    names = [entry["path"] for entry in document["files"]]
    document["files"] = [store.file_entry(directory / name, name) for name in names]
    store.write_json_atomic(directory / "manifest.json", document)


def _write_manifest(directory: Path, edit: Callable[[dict], Any]) -> None:
    """Edit the manifest alone, its file digests untouched."""
    document = manifest(directory)
    edit(document)
    store.write_json_atomic(directory / "manifest.json", document)


def _edit_json(directory: Path, name: str, edit: Callable[[dict], Any]) -> None:
    """Edit one canonical JSON data file, then refresh the digests."""
    document = json.loads((directory / name).read_text(encoding="utf-8"))
    edit(document)
    store.write_json_atomic(directory / name, document)
    _rewrite(directory)


def _relabel_commitment(directory: Path) -> None:
    path = directory / "COMMITMENT.json"
    store.write_json_atomic(path, {**json.loads(path.read_text(encoding="utf-8")), "run_label": "some-other-run"})
    _rewrite(directory)


def _flip_first(rows: list[dict]) -> list[dict]:
    """Change game 0's result to another valid natural result."""
    first = rows[0]
    if first["outcome"] == "draw":
        flipped = {**first, "outcome": "p0_win", "winner": "p0", "winner_bot_id": first["seats"][0]["bot_id"]}
    else:
        flipped = {**first, "outcome": "draw", "winner": None, "winner_bot_id": None}
    return [flipped, *rows[1:]]


def _replace_bytes(path: Path, old: bytes, new: bytes) -> None:
    data = path.read_bytes()
    assert data.count(old) >= 1, old
    path.write_bytes(data.replace(old, new, 1))


# ---------------------------------------------------------------------------
# Published runs validate, whatever their status
# ---------------------------------------------------------------------------


def test_complete_and_rated_runs_validate(published: dict[str, Path]) -> None:
    assert manifest(published["unrated"])["run"] == {"benchmark_id": None, "label": None, "status": "complete",
                                                     "rated": False}
    assert validate_tournament_dir(published["unrated"]) == []
    assert manifest(published["rated"])["run"]["rated"] is True
    assert validate_tournament_dir(published["rated"]) == []


def test_an_invalid_run_validates_as_invalid(published: dict[str, Path]) -> None:
    document = manifest(published["invalid"])
    assert document["run"]["status"] == "invalid" and document["validator"]["verdict"] == "fail"
    assert validate_tournament_dir(published["invalid"]) == []


def test_an_aborted_run_validates_as_aborted(published: dict[str, Path]) -> None:
    document = manifest(published["aborted"])
    assert document["run"]["status"] == "aborted" and document["games"]["total"] == 2   # Review Focus 2
    assert document["secrets"]["run_secret"] == TEST_RUN_SECRET.hex()
    assert validate_tournament_dir(published["aborted"]) == []


def test_a_run_aborted_before_its_first_game_validates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "play_games", interrupted)
    directory = tmp_path / "t"
    with pytest.raises(KeyboardInterrupt):
        run(make_config(directory, BOTS, pairs=1, include_self_play=False))
    assert (directory / "matches.jsonl").read_bytes() == b"" and manifest(directory)["run"]["status"] == "aborted"
    assert validate_tournament_dir(directory) == []


def test_halts_loop_draws_decklists_and_local_files_validate(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    relics = {"name": "Relics", "decklist": [{"name": "Mountain", "count": 18}, {"name": "Relic of Progenitus",
                                                                                   "count": 4}]}
    bots = [builtin("heuristic"), subprocess_bot("first", cli_bot("first"), version="2.0.0")]
    config = make_config(directory, bots, engine_args=("--decklists",), include_self_play=False, pairs=4,
                         deck_pool=("Halt", "Loop", "Crash", "Burn"))
    config["deck_pool"][3] = relics                                   # a decklist deck beside the catalog decks
    config["limits"] = {"max_decisions": 10000, "max_steps": 100000, "max_seat_decisions_per_turn": 20,
                        "max_seat_decisions_per_game": 4999, "max_seat_steps_per_game": 49999}
    run(config)
    reasons = {row["reason"] for row in ledger_rows(directory)}
    assert reasons == {"engine_contract_failure:test_hook", "mandatory_loop", "host_engine_fault:transport", "score"}
    assert (directory / "diagnostics.jsonl").is_file()                                   # the crashed engine's
    (directory / "throughput.jsonl").write_text('{"warning":"idle capacity"}\n', encoding="utf-8", newline="\n")   # Task 43's
    assert validate_tournament_dir(directory) == []
    names = ["Lightning Bolt", "Mountain"]                        # the catalog decks' names, not the Relics deck's
    domain = {"domain_id": "sha256:" + hashlib.sha256(store.canonical_bytes(names)).hexdigest(), "names": names}
    _write_manifest(directory, _set("information_rules.rules.card_name_domain", domain))
    assert validate_tournament_dir(directory) == [
        "manifest information_rules.rules.card_name_domain lacks names of the decklist decks (spec 12.2)",
    ]


def test_a_forfeit_validates(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    run(make_config(directory, [builtin("first"), hostile_bot("out-of-range")], pairs=1, include_self_play=False))
    assert {row["classification"] for row in ledger_rows(directory)} == {"forfeit"}
    assert validate_tournament_dir(directory) == []


def test_validate_needs_nothing_outside_the_run_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    checkpoint = tmp_path / "weights.bin"
    checkpoint.write_bytes(b"weights")
    bots = [subprocess_bot("heuristic", cli_bot("heuristic"), version="2.0.0", checkpoint=str(checkpoint)),
            builtin("first")]
    directory = tmp_path / "runs" / "t"
    run(make_config(directory, bots, pairs=1), run_label="t", benchmark_id="fake-pool")
    checkpoint.unlink()                                  # a checkpoint's bytes are in its bot id, never published
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"{}\n")
    _rewrite(directory, edit=lambda m: m["files"].append({"path": "../../outside.json"}))
    read: list[Path] = []
    read_bytes = Path.read_bytes

    def recording(path: Path) -> bytes:
        read.append(path.resolve())
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", recording)
    assert validate_tournament_dir(directory) == [FILES_FAILURE]
    assert read and all(directory.resolve() in path.parents for path in read)          # never a listed path outside


def test_a_run_published_after_bench_commit_validates(tmp_path: Path) -> None:
    directory = tmp_path / "2026-10-01"
    secret = RunSecret(bytes(range(1, 33)))
    record = {"schema": "spellbench-run-commitment/v1", "protocol": "spellbench/v2", "benchmark_id": "fake-pool",
              "run_label": "2026-10-01", "commitment": secret.commitment()}
    directory.mkdir()
    store.write_json_atomic(directory / "COMMITMENT.json", record)            # published before the run (spec 11.6)
    run(make_config(directory, BOTS, pairs=1, include_self_play=False), secret=secret, rated=True,
        run_label="2026-10-01", benchmark_id="fake-pool")
    assert validate_tournament_dir(directory) == []
    _rewrite(directory, edit=lambda m: m["run"].update(benchmark_id="other-pool"))
    assert validate_tournament_dir(directory) == [
        'the commitment in COMMITMENT.json was made for another run: its benchmark_id is "fake-pool", this run\'s '
        'benchmark_id is "other-pool" (spec 11.6, R3-30)',
    ]


def test_a_parallel_run_validates(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    run(make_config(directory, BOTS, pairs=2, workers=2))
    assert validate_tournament_dir(directory) == []


def test_parallel_invalid_and_aborted_runs_validate(tmp_path: Path) -> None:
    """Decision 6 with workers > 1: the ledger stops at the violating game, and an aborted run keeps its prefix."""
    invalid = tmp_path / "invalid"
    run(make_config(invalid, [builtin("first"), builtin("heuristic")], engine=HOSTILE_ENGINE,
                    engine_args=("stale-reference",), pairs=2, workers=2))
    assert manifest(invalid)["run"]["status"] == "invalid"
    assert validate_tournament_dir(invalid) == []
    aborted = tmp_path / "aborted"
    with pytest.raises(KeyboardInterrupt):
        run(make_config(aborted, BOTS, pairs=2, include_self_play=False, workers=2), on_game=_interrupt_at(1))
    assert manifest(aborted)["run"]["status"] == "aborted"
    assert validate_tournament_dir(aborted) == []


def test_files_a_desktop_leaves_in_a_browsed_run_are_ignored(published: dict[str, Path], tmp_path: Path) -> None:
    """Finder, Dolphin and Explorer write these into any folder they show; a browsed honest run still validates."""
    directory = _copy(published, "aborted", tmp_path)
    for name in (".DS_Store", ".directory", "Thumbs.db", "desktop.ini"):
        (directory / name).write_bytes(b"\x00metadata")
    assert validate_tournament_dir(directory) == []
    (directory / "notes.txt").write_text("x", encoding="utf-8")                 # anything else still fails
    assert validate_tournament_dir(directory) == ["unexpected file in the run directory: notes.txt"]


def test_a_file_converted_to_crlf_says_so(published: dict[str, Path], tmp_path: Path) -> None:
    directory = _copy(published, "unrated", tmp_path)
    path = directory / "config.json"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert ("config.json has CR LF line endings: published files use LF, so a copy or an edit outside git changed its "
            "bytes") in validate_tournament_dir(directory)


def test_the_arena_version_is_checked_before_the_manifest_fields(published: dict[str, Path], tmp_path: Path) -> None:
    """A newer arena may add a manifest field; its run gets the one message naming the arena, not a field list."""
    directory = _copy(published, "unrated", tmp_path)

    def newer(document: dict) -> None:
        document["tournament"]["arena_version"] = "9.9.9"
        document["quarantine"] = []

    _write_manifest(directory, newer)
    assert validate_tournament_dir(directory) == [validate._version_gate({"arena_version": "9.9.9"})]


# ---------------------------------------------------------------------------
# The plan's tampering cases (a forger who refreshes the digests)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tamper", "expected"),
    [
        (lambda d: _rewrite(d, rows=_flip_first(ledger_rows(d))), "leaderboard.json"),
        (lambda d: _rewrite(d, rows=[{**r, "game_id": "g-0000000000000000"} if r["game_index"] == 0 else r
                                     for r in ledger_rows(d)]), "schedule"),
        (lambda d: _rewrite(d, edit=lambda m: m["secrets"].update(run_secret="11" * 32)), "commitment"),
        (lambda d: _rewrite(d, edit=lambda m: m["run"].update(rated=True)), "rated"),
        (lambda d: _rewrite(d, edit=lambda m: m["validator"].update(decisions_checked=1)), "validator"),
        (lambda d: _rewrite(d, edit=lambda m: m["information_rules"].update(fairness_label="validator and probe")),
         "fairness"),
        (lambda d: _rewrite(d, edit=lambda m: m["games"].update(natural=0)), "games"),
        (lambda d: (d / "LEADERBOARD.md").write_text("x", encoding="utf-8"), "digest mismatch: LEADERBOARD.md"),
        (_relabel_commitment, "commitment"),                                               # another run's label (R3-30)
        (lambda d: _rewrite(d, edit=lambda m: m["isolation"].update(self_reported=True)), "isolation"),       # R3-9
    ],
    ids=["result", "game-id", "run-secret", "rated", "validator", "fairness", "games", "markdown", "relabeled",
         "isolation"],
)
def test_tampering_is_caught(published: dict[str, Path], tmp_path: Path, tamper, expected: str) -> None:
    directory = _copy(published, "unrated", tmp_path)
    tamper(directory)
    failures = validate_tournament_dir(directory)
    assert any(expected in failure for failure in failures), failures


def test_a_rated_run_without_pinned_engine_files_is_caught(published: dict[str, Path], tmp_path: Path) -> None:
    directory = _copy(published, "rated", tmp_path)
    _rewrite(directory, edit=lambda m: m.update(engine_files=[]))
    assert validate_tournament_dir(directory) == [
        "manifest run.rated is true; recomputed: false (Decision 3: no pinned engine files)",           # R3-7
    ]


def test_another_arena_version_gets_one_message(published: dict[str, Path], tmp_path: Path) -> None:
    directory = _copy(published, "unrated", tmp_path)
    _rewrite(directory, edit=lambda m: m["tournament"].update(arena_version="0.9.0"))
    assert validate_tournament_dir(directory) == [
        f"this run was made by spellbench arena 0.9.0; this is {spellbench.__version__}: rerun the benchmark, or "
        "validate with arena 0.9.0"
    ]


def test_an_unprintable_arena_version_is_quoted_on_one_line(published: dict[str, Path], tmp_path: Path) -> None:
    directory = _copy(published, "unrated", tmp_path)
    forged = "0.1.0\n::error::forged"                      # a CI log reads a line starting "::" as a command
    _rewrite(directory, edit=lambda m: m["tournament"].update(arena_version=forged))
    assert validate_tournament_dir(directory) == [
        f"this run was made by spellbench arena '0.1.0\\n::error::forged'; this is {spellbench.__version__}: "
        "rerun the benchmark, or validate with arena '0.1.0\\n::error::forged'"
    ]


def test_an_unknown_schema_goes_to_the_legacy_path_and_fails_there(published: dict[str, Path], tmp_path: Path) -> None:
    directory = _copy(published, "unrated", tmp_path)
    _rewrite(directory, edit=lambda m: m.update(schema="spellbench-tournament/v9"))
    assert any("spellbench-tournament/v1" in failure for failure in validate_tournament_dir(directory))
    assert validate_v2_run(directory) == ["manifest.json schema must be 'spellbench-tournament/v2'"]


# ---------------------------------------------------------------------------
# Every corruption fails, with a message naming it
# ---------------------------------------------------------------------------


def _swap_first_two(rows: list[dict]) -> list[dict]:
    return [rows[1], rows[0], *rows[2:]]


def _set(path: str, value: Any) -> Callable[[dict], None]:
    """An edit setting the value at a dotted path of the manifest."""
    def edit(document: dict) -> None:
        *parents, last = path.split(".")
        for key in parents:
            document = document[key]
        document[last] = value

    return edit


def _change_first_digest(directory: Path) -> None:
    """Give game 0 another well-formed game_digest, the manifest's digests untouched."""
    digest = ledger_rows(directory)[0]["game_digest"]
    _replace_bytes(directory / "matches.jsonl", digest.encode(), (digest[:-1] + "01"[digest[-1] == "0"]).encode())


def _cut(text: str) -> str:
    """A string as a failure line quotes it: in JSON, cut to 64 characters."""
    quoted = json.dumps(text)
    return quoted if len(quoted) <= 64 else quoted[:61] + "..."


def _decisions(directory: Path) -> int:
    return manifest(directory)["validator"]["decisions_checked"]


# Each case: (template run, corruption, the exact failures). A careful forger refreshes the manifest's digests
# (``_rewrite``), so most corruptions are refreshed; the plain ones fail their digest first.
CORRUPTIONS = {
    "ledger-byte": ("unrated", lambda d: _replace_bytes(d / "matches.jsonl", b'"reason":"score"', b'"reason":"scorf"'),
                    ["digest mismatch: matches.jsonl"]),
    "ledger-byte-breaking-json": ("unrated", lambda d: _replace_bytes(d / "matches.jsonl", b"{", b"["),
                                  ["digest mismatch: matches.jsonl",
                                   "matches.jsonl: line 1 is not a strict JSON object: line is not strict JSON: "
                                   "Expecting ',' delimiter: line 1 column 16 (char 15)"]),
    "ledger-byte-refreshed": ("unrated", lambda d: (_replace_bytes(d / "matches.jsonl", b'"outcome":"draw"',
                                                                   b'"outcome":"drax"'), _rewrite(d)),
                              ["matches.jsonl: ledger[0].outcome: 'drax' is not one of draw, halted, p0_win, p1_win, "
                               "truncated"]),
    "game-digest": ("unrated", lambda d: _replace_bytes(d / "matches.jsonl", b'"game_digest":"sha256:',
                                                        b'"game_digest":"sha256:0'),
                    ["digest mismatch: matches.jsonl",
                     "matches.jsonl: ledger[0].game_digest: must be sha256: followed by 64 lowercase hex digits"]),
    "game-digest-changed": ("unrated", lambda d: _change_first_digest(d), ["digest mismatch: matches.jsonl"]),
    "game-digest-copied": ("unrated", lambda d: _rewrite(d, rows=[
        {**row, "game_digest": ledger_rows(d)[0]["game_digest"]} if row["game_index"] == 1 else row
        for row in ledger_rows(d)]),
                           ["ledger rows 0 and 1 have the same game_digest; each game's digest chains its own reset "
                            "(spec 11.8)"]),
    "deck-id": ("unrated", lambda d: _rewrite(d, rows=[
        {**row, "decks": [{**row["decks"][0], "deck_id": "sha256:" + "1" * 64}, row["decks"][1]]}
        if row["game_index"] == 0 else row for row in ledger_rows(d)]),
                ["the ledger gives catalog deck 'Burn' 2 deck_id and name pairs; one deck has one deck_id "
                 "(spec 4.3, 12.1)", BOARD_JSON, BOARD_MD]),
    "domain-id": ("unrated", lambda d: _write_manifest(d, _set("information_rules.rules.card_name_domain.domain_id",
                                                               "sha256:" + "2" * 64)),
                  ["manifest: information_rules.rules.card_name_domain.domain_id: does not match the names, whose "
                   "domain_id is sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697"]),
    "revealed-secret": ("unrated", lambda d: _rewrite(d, edit=_set("secrets.run_secret", "11" * 32)),
                        [SECRET_FAILURE, COMMITTED_FAILURE]),
    "revealed-secret-malformed": ("unrated", lambda d: _rewrite(d, edit=_set("secrets.run_secret", "11" * 31)),
                                  ["manifest secrets.run_secret is not a revealed run secret: 64 lowercase hex "
                                   "characters (spec 11.6)"]),
    "commitment": ("unrated", lambda d: _write_manifest(d, _set("secrets.commitment", "22" * 32)), [SECRET_FAILURE]),
    "commitment-file": ("unrated", lambda d: _edit_json(d, "COMMITMENT.json",
                                                        lambda c: c.update(commitment="22" * 32)),
                        [COMMITTED_FAILURE]),
    "commitment-file-plain": ("unrated", lambda d: _replace_bytes(d / "COMMITMENT.json", b'"commitment":"6',
                                                                  b'"commitment":"7'),
                              ["digest mismatch: COMMITMENT.json", COMMITTED_FAILURE]),
    "commitment-file-extra-field": ("unrated", lambda d: _edit_json(d, "COMMITMENT.json",
                                                                    lambda c: c.update(note="x")),
                                    ["the commitment file COMMITMENT.json has fields ['benchmark_id', 'commitment', "
                                     "'note', 'protocol', 'run_label', 'schema']; a commitment record has "
                                     "['benchmark_id', 'commitment', 'protocol', 'run_label', 'schema']"]),
    "commitment-file-not-canonical": ("unrated", lambda d: ((d / "COMMITMENT.json").write_text(
        json.dumps(json.loads((d / "COMMITMENT.json").read_text(encoding="utf-8"))) + "\n", encoding="utf-8", newline="\n"),
        _rewrite(d)), ["COMMITMENT.json is not canonical JSON (spec 4.3)"]),
    "commitment-malformed": ("unrated", lambda d: _write_manifest(d, _set("secrets.commitment", "X" * 64)),
                             ["manifest secrets.commitment is not 64 lowercase hex characters (spec 11.6)",
                              SECRET_FAILURE]),
    "proof-malformed": ("rated", lambda d: _write_manifest(d, _set("secrets.commitment_proof",
                                                                    {"commit": "x", "timestamp": "t"})),
                        ["manifest: secrets.commitment_proof: a commitment proof's commit must be 40 lowercase hex "
                         "characters"]),
    "run-label-not-text": ("unrated", lambda d: _write_manifest(d, _set("run.label", 5)),
                           ["manifest: run.label: must be a string, got int"]),
    "protocol-minor": ("unrated", lambda d: _write_manifest(d, _set("protocol.minor", -1)),
                       ["manifest: protocol.minor: must be an integer in [0, 4294967295]"]),
    "protocol-name": ("unrated", lambda d: _write_manifest(d, _set("protocol.name", "spellbench/v1")),
                      ['manifest protocol.name is "spellbench/v1"; recomputed: "spellbench/v2"']),
    "commitment-relabeled": ("unrated", _relabel_commitment,
                             ['the commitment in COMMITMENT.json was made for another run: its run_label is '
                              '"some-other-run", this run\'s label is null (spec 11.6, R3-30)']),
    "commitment-deleted": ("unrated", lambda d: (d / "COMMITMENT.json").unlink(), ["missing file: COMMITMENT.json"]),
    "extra-row": ("unrated", lambda d: _rewrite(d, rows=[*ledger_rows(d), {
        **ledger_rows(d)[3], "game_index": 4, "game_id": TEST_RUN_SECRET.game_id(4), "game_digest": "sha256:" + "6" * 64}]),
                  ["the ledger has 5 games but the schedule has 4", BOARD_JSON, BOARD_MD, "manifest validator.decisions_checked is 16; recomputed: 20 (spec 11.3)",
                   "manifest games.natural is 4; recomputed: 5", "manifest games.total is 4; recomputed: 5"]),
    "ledger-not-canonical": ("unrated", lambda d: ((d / "matches.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in ledger_rows(d)), encoding="utf-8", newline="\n"), _rewrite(d)),
                             ["matches.jsonl line 1 is not its row in canonical form (spec 4.3)"]),
    "config-not-canonical": ("unrated", lambda d: ((d / "config.json").write_text(
        json.dumps(json.loads((d / "config.json").read_text(encoding="utf-8"))) + "\n", encoding="utf-8", newline="\n"), _rewrite(d)),
                             ["config.json is not its config in the normalized canonical form the arena writes"]),
    "config-not-normalized": ("unrated", lambda d: _edit_json(d, "config.json", lambda c: c.pop("workers")),
                              ["config.json is not its config in the normalized canonical form the arena writes"]),
    "reordered-rows": ("unrated", lambda d: _rewrite(d, rows=_swap_first_two(ledger_rows(d))),
                       ["ledger row 0 does not match the schedule: game_index, game_id, pair_slot, seats differ",
                        "ledger row 1 does not match the schedule: game_index, game_id, pair_slot, seats differ"]),
    "extra-file": ("unrated", lambda d: (d / "notes.txt").write_text("x", encoding="utf-8"),
                   ["unexpected file in the run directory: notes.txt"]),
    "extra-directory": ("unrated", lambda d: (d / "extra").mkdir(), ["unexpected file in the run directory: extra"]),
    "extra-reveal": ("unrated", lambda d: (d / "REVEAL.json").write_text("{}\n", encoding="utf-8", newline="\n"),
                     ["unexpected file in the run directory: REVEAL.json"]),
    "extra-listed-file": ("unrated", lambda d: ((d / "notes.txt").write_text("x", encoding="utf-8"),
                                                _rewrite(d, edit=lambda m: m["files"].append({"path": "notes.txt"}))),
                          ["unexpected file in the run directory: notes.txt", FILES_FAILURE]),
    "local-file-not-a-file": ("unrated", lambda d: (d / "diagnostics.jsonl").mkdir(),
                              ["diagnostics.jsonl is not a regular file"]),
    "leaderboard-number": ("unrated", lambda d: _edit_json(d, "leaderboard.json", lambda b: b["rows"][0].update(
        games=b["rows"][0]["games"] + 1)),
                           [BOARD_JSON]),
    "leaderboard-number-plain": ("unrated", lambda d: _replace_bytes(d / "leaderboard.json", b'"games":4',
                                                                     b'"games":5'),
                                 ["digest mismatch: leaderboard.json", BOARD_JSON]),
    "leaderboard-markdown": ("unrated", lambda d: (_replace_bytes(d / "LEADERBOARD.md", b"| 1 |", b"| 2 |"),
                                                   _rewrite(d)),
                             [BOARD_MD]),
    "leaderboard-status": ("unrated", lambda d: _write_manifest(d, _set("leaderboard_status", "insufficient_data")),
                           ['manifest leaderboard_status is "insufficient_data"; recomputed: "ok"']),
    "rated-flipped-on": ("unrated", lambda d: _write_manifest(d, _set("run.rated", True)),
                         ["manifest run.rated is true; recomputed: false (Decision 3: no commitment proof, no pinned "
                          "engine files)"]),
    "rated-aborted-run": ("aborted", lambda d: _write_manifest(d, _set("run.rated", True)),
                          ["manifest run.rated is true; recomputed: false (Decision 3: the run is aborted, no commitment "
                           "proof, no pinned engine files)"]),
    "rated-invalid-run": ("invalid", lambda d: _write_manifest(d, _set("run.rated", True)),
                          ["manifest run.rated is true; recomputed: false (Decision 3: the run is invalid, the verdict "
                           "is fail, no commitment proof, no pinned engine files)"]),
    "rated-flipped-off": ("rated", lambda d: _write_manifest(d, _set("run.rated", False)),
                          ["manifest run.rated is false; recomputed: true (Decision 3)"]),
    "rated-as-one": ("unrated", lambda d: _write_manifest(d, _set("run.rated", 0)),
                     ["manifest run.rated is 0; recomputed: false (Decision 3: no commitment proof, no pinned engine "
                      "files)"]),
    "rated-without-proof": ("rated", lambda d: _write_manifest(d, _set("secrets.commitment_proof", None)),
                            ["manifest run.rated is true; recomputed: false (Decision 3: no commitment proof)"]),
    "rated-unmeasured": ("rated", lambda d: _write_manifest(
        d, _set("allocation", Allocation.unmeasured(1, cpu_count=1, host="test-host").to_json())),
                         ["manifest run.rated is true; recomputed: false (Decision 3: the allocation is unmeasured)"]),
    "status-aborted": ("unrated", lambda d: _write_manifest(d, _set("run.status", "aborted")),
                       ['manifest run.status is "aborted"; recomputed: "complete" (R3-13)']),
    "status-of-an-aborted-run": ("aborted", lambda d: _write_manifest(d, _set("run.status", "complete")),
                                 ['manifest run.status is "complete"; recomputed: "aborted" (R3-13)']),
    "status-of-an-invalid-run": ("invalid", lambda d: _write_manifest(d, _set("run.status", "aborted")),
                                 ['manifest run.status is "aborted"; recomputed: "invalid" (R3-13)']),
    "status-of-a-rated-run": ("rated", lambda d: _write_manifest(d, _set("run.status", "aborted")),
                              ['manifest run.status is "aborted"; recomputed: "complete" (R3-13)']),
    "verdict": ("invalid", lambda d: _write_manifest(d, _set("validator.verdict", "pass")),
                ['manifest validator.verdict is "pass"; recomputed: "fail" (spec 11.3)']),
    "violation-dropped": ("invalid", lambda d: _write_manifest(d, lambda m: m["validator"].update(violations=[],
                                                                                                 verdict="pass")),
                          ['manifest validator.verdict is "pass"; recomputed: "fail" (spec 11.3)',
                           "manifest validator.violations is a list of 0 items; recomputed: a list of 1 items "
                           "(spec 11.3)"]),
    "violation-detail": ("invalid", lambda d: _write_manifest(d, lambda m: m["validator"]["violations"][0].update(
        detail="another detail")),
                         ['manifest validator.violations[0].detail is "another detail"; recomputed: '
                          '"candidates[1].semantic.source differs from the observation r... (spec 11.3)']),
    "fairness-label": ("unrated", lambda d: _write_manifest(d, _set("information_rules.fairness_label",
                                                                    "validator and probe")),
                       ['manifest information_rules.fairness_label is "validator and probe"; recomputed: '
                        '"validator only" (spec 12.2)']),
    "isolation": ("unrated", lambda d: _write_manifest(d, _set("isolation.self_reported", True)),
                  ["manifest isolation.self_reported is true; recomputed: false (spec 11.7)"]),
    "games": ("unrated", lambda d: _write_manifest(d, _set("games.natural", 0)),
              ["manifest games.natural is 0; recomputed: 4"]),
    "scheduled": ("aborted", lambda d: _write_manifest(d, _set("games.scheduled", 2)),
                  ["manifest games.scheduled is 2; recomputed: 4"]),
    "many-differences": ("unrated", lambda d: _write_manifest(d, _set("tournament.time_control", dict.fromkeys(
        ("bank_ms", "engine_step_ms", "game_start_ms", "increment_ms", "max_decision_ms", "startup_ms"), 1))),
                         ["manifest tournament.time_control.bank_ms is 1; recomputed: 600000",
                          "manifest tournament.time_control.engine_step_ms is 1; recomputed: 120000",
                          "manifest tournament.time_control.game_start_ms is 1; recomputed: 60000",
                          "manifest tournament.time_control.increment_ms is 1; recomputed: 2000",
                          "manifest tournament.time_control.max_decision_ms is 1; recomputed: 60000",
                          "manifest tournament: 1 more differences"]),
}


@pytest.mark.parametrize(("kind", "corrupt", "expected"), CORRUPTIONS.values(), ids=list(CORRUPTIONS))
def test_every_corruption_fails_with_a_message_naming_it(published: dict[str, Path], tmp_path: Path, kind: str,
                                                          corrupt, expected: list[str]) -> None:
    directory = _copy(published, kind, tmp_path)
    corrupt(directory)
    assert validate_tournament_dir(directory) == expected


def test_a_changed_bot_id_is_caught_in_the_registry_the_ledger_and_the_manifest(
    published: dict[str, Path], tmp_path: Path
) -> None:
    directory = _copy(published, "unrated", tmp_path)
    _edit_json(directory, "registry.json", lambda registry: registry["bots"][0].update(bot_id="f" * 64))
    failures = validate_tournament_dir(directory)
    changed = next(bot for bot in json.loads((directory / "registry.json").read_text(encoding="utf-8"))["bots"]
                   if bot["bot_id"] == "f" * 64)["name"]
    assert failures[0] == f"registry.json entry {changed!r} does not match its bot in config.json"
    assert "registry.json is not its entries in canonical form, sorted by bot id (spec 4.3)" in failures
    assert "ledger row 0 does not match the schedule: seats differs" in failures
    assert BOARD_JSON in failures and any(failure.startswith("manifest tournament.") for failure in failures)


@pytest.mark.parametrize("position", [0, 1, 2, 3])
def test_a_deleted_game_is_caught(published: dict[str, Path], tmp_path: Path, position: int) -> None:
    directory = _copy(published, "unrated", tmp_path)
    rows = ledger_rows(directory)
    lost = rows.pop(position)
    _rewrite(directory, rows=rows)
    failures = validate_tournament_dir(directory)
    shifted = [failure for failure in failures if "does not match the schedule" in failure]
    assert len(shifted) == 3 - position                                   # every later row is off its scheduled game
    assert failures[len(shifted):] == [
        BOARD_JSON,
        BOARD_MD,
        f"manifest validator.decisions_checked is {_decisions(published['unrated'])}; recomputed: "
        f"{_decisions(published['unrated']) - lost['decisions_checked']} (spec 11.3)",
        'manifest run.status is "complete"; recomputed: "aborted" (R3-13)',
        "manifest games.natural is 4; recomputed: 3",
        "manifest games.total is 4; recomputed: 3",
    ]


@pytest.mark.parametrize("name", HASHED)
@pytest.mark.parametrize("field", ["sha256", "bytes"])
def test_a_manifest_files_hash_is_checked_for_every_file(published: dict[str, Path], tmp_path: Path, name: str,
                                                         field: str) -> None:
    directory = _copy(published, "unrated", tmp_path)

    def edit(document: dict) -> None:
        entry = next(entry for entry in document["files"] if entry["path"] == name)
        entry[field] = "0" * 64 if field == "sha256" else entry["bytes"] + 1

    _write_manifest(directory, edit)
    assert validate_tournament_dir(directory) == [f"digest mismatch: {name}"]


@pytest.mark.parametrize("name", HASHED)
def test_one_changed_byte_in_any_file_fails_its_digest(published: dict[str, Path], tmp_path: Path,
                                                       name: str) -> None:
    source = published["unrated"] / name
    size = len(source.read_bytes())
    for position in sorted({0, size // 3, size // 2, size - 2, size - 1}):
        directory = tmp_path / f"{name}-{position}"
        shutil.copytree(published["unrated"], directory)
        data = bytearray((directory / name).read_bytes())
        data[position] ^= 0x01
        (directory / name).write_bytes(bytes(data))
        failures = validate_tournament_dir(directory)
        assert failures[0] == f"digest mismatch: {name}", (position, failures)


@pytest.mark.parametrize("edit", [
    lambda m: m["files"].reverse(),
    lambda m: m["files"].pop(),
    lambda m: m.update(files={}),
    lambda m: m["files"].append(m["files"][0]),
], ids=["reordered", "short", "not-a-list", "repeated"])
def test_the_files_list_is_exact(published: dict[str, Path], tmp_path: Path, edit) -> None:
    directory = _copy(published, "unrated", tmp_path)
    _write_manifest(directory, edit)
    assert validate_tournament_dir(directory) == [FILES_FAILURE]


def test_an_invalid_run_that_goes_on_after_its_violation_is_caught(published: dict[str, Path], tmp_path: Path) -> None:
    directory = _copy(published, "invalid", tmp_path)
    halted = ledger_rows(directory)[0]
    later = {**halted, "game_index": 1, "game_id": TEST_RUN_SECRET.game_id(1), "pair_slot": 1,
             "game_digest": "sha256:" + "4" * 64}
    _rewrite(directory, rows=[halted, later], edit=lambda m: m["validator"]["violations"].append(
        {"game_index": 1, "game_id": TEST_RUN_SECRET.game_id(1), "rule": "V4",
         "detail": halted["adjudication"]["detail"]}))
    failures = validate_tournament_dir(directory)
    assert failures[0] == ("the ledger goes on after the violation in row 0; an invalid run stops at its violating "
                           "game (spec 11.3, Decision 6)")


def test_a_violation_hidden_as_an_engine_terminal_is_caught(published: dict[str, Path], tmp_path: Path) -> None:
    directory = _copy(published, "invalid", tmp_path)
    rows = [{**row, "adjudication": None} for row in ledger_rows(directory)]
    _rewrite(directory, rows=rows, edit=lambda m: m["validator"].update(violations=[], verdict="pass"))
    assert validate_tournament_dir(directory) == [
        "ledger row 0 is an engine terminal with the host's reason 'host_validator:V4' (spec 11.5)",
        'manifest run.status is "invalid"; recomputed: "aborted" (R3-13)',
    ]


def test_another_engine_in_the_manifest_is_caught(published: dict[str, Path], tmp_path: Path) -> None:
    directory = _copy(published, "unrated", tmp_path)
    _write_manifest(directory, _set("engine.version", "0.0.9"))
    assert validate_tournament_dir(directory) == [
        "4 ledger rows (the first is row 0) do not carry the provenance of the manifest's engine (spec 9.3)",
    ]


def test_the_information_rules_follow_the_config_and_the_engine_profile(published: dict[str, Path],
                                                                        tmp_path: Path) -> None:
    directory = _copy(published, "unrated", tmp_path)
    _write_manifest(directory, lambda m: (m["information_rules"]["rules"].update(mulligan="london"),
                                          m["information_rules"]["observation"].update(poison=True)))
    assert validate_tournament_dir(directory) == [
        'manifest information_rules.observation.poison is true; recomputed: false (spec 12.2)',
        'manifest information_rules.rules.mulligan is "london"; recomputed: "none" (spec 12.2)',
    ]
    _write_manifest(directory, lambda m: m["engine_profile"]["rules_supported"].update(mulligan=["london"]))
    assert validate_tournament_dir(directory) == [
        'manifest information_rules.observation.poison is true; recomputed: false (spec 12.2)',
    ]


# ---------------------------------------------------------------------------
# Fail closed: a report naming the file, never an exception
# ---------------------------------------------------------------------------


SHAPES = {"null": None, "list": [], "string": "x", "number": 7, "object": {}}


@pytest.mark.parametrize(("key", "value"), [
    (key, value) for key in MANIFEST_KEYS if key != "schema" for name, value in SHAPES.items()
    if (key, name) != ("engine_files", "list")                         # an unrated run's engine_files is [] already
], ids=[f"{key}-{name}" for key in MANIFEST_KEYS if key != "schema" for name in SHAPES
        if (key, name) != ("engine_files", "list")])
def test_a_manifest_value_of_any_shape_is_a_failure_not_a_crash(published: dict[str, Path], tmp_path: Path,
                                                                key: str, value: Any) -> None:
    directory = _copy(published, "unrated", tmp_path)
    _write_manifest(directory, _set(key, value))
    failures = validate_tournament_dir(directory)
    assert failures and all(isinstance(failure, str) for failure in failures)
    assert not any(failure.startswith("validation stopped") for failure in failures), failures


@pytest.mark.parametrize("name", HASHED)
@pytest.mark.parametrize("content", [b"", b"{}\n", b"[]\n", b"\xff\n", b'{"a":1}\n{"a":1}\n'],
                         ids=["empty", "object", "array", "not-utf8", "two-lines"])
def test_a_data_file_of_any_content_is_a_failure_not_a_crash(published: dict[str, Path], tmp_path: Path,
                                                             name: str, content: bytes) -> None:
    directory = _copy(published, "unrated", tmp_path)
    (directory / name).write_bytes(content)
    _rewrite(directory)
    failures = validate_tournament_dir(directory)
    assert failures and not any(failure.startswith("validation stopped") for failure in failures), failures


def _paths(value: Any, prefix: tuple = (), depth: int = 0):
    """Every path of a JSON document down to three levels, list items by index."""
    if prefix:
        yield prefix
    if depth < 3:
        items = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
        for key, item in items:
            yield from _paths(item, (*prefix, key), depth + 1)


# Recorded inputs a measurement may leave null (the allocation's own rules accept it).
NULLABLE = {("allocation", "machine", "memory_bytes"), ("allocation", "qualification_seconds_milli")}


def test_no_manifest_value_of_any_shape_stops_the_validator(published: dict[str, Path], tmp_path: Path) -> None:
    directory = _copy(published, "rated", tmp_path)
    original = manifest(directory)
    for path in _paths(original):
        for shape in (None, [["x"]]):                  # a wrong type, and one no dict or set can hold
            document = copy.deepcopy(original)
            target = document
            for key in path[:-1]:
                target = target[key]
            if store.canonical_bytes(target[path[-1]]) == store.canonical_bytes(shape):
                continue
            target[path[-1]] = shape
            store.write_json_atomic(directory / "manifest.json", document)
            failures = validate_v2_run(directory)
            assert failures or (shape is None and path in NULLABLE), path
            assert all(failure.isascii() and failure.isprintable() for failure in failures), path
            assert not any(failure.startswith("validation stopped") for failure in failures), (path, failures)


@pytest.mark.parametrize("key", ["schema", "protocol", "benchmark_id", "run_label", "commitment"])
def test_a_commitment_file_field_of_any_shape_is_named(published: dict[str, Path], tmp_path: Path, key: str) -> None:
    directory = _copy(published, "unrated", tmp_path)
    _edit_json(directory, "COMMITMENT.json", lambda record: record.update({key: [["x"]]}))
    (failure,) = validate_tournament_dir(directory)
    assert failure.startswith("the commitment") and key in failure


def test_a_symbolic_link_is_not_a_published_file(published: dict[str, Path], tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    directory = _copy(published, "unrated", tmp_path)
    is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path.name == "registry.json" or is_symlink(path))
    assert validate_tournament_dir(directory) == ["registry.json is not a regular file"]


def _enable_native_extension(directory: Path, *, audits: dict, native_ids: bool = True) -> None:
    """Make the run one that enabled a native-id extension, as a run on such an engine records it (spec 14)."""
    _edit_json(directory, "config.json", lambda config: config.update(extensions=["x_native"],
                                                                       native_id_audits=audits))
    _write_manifest(directory, lambda m: (
        m["engine_profile"].update(extensions=[{"name": "x_native", "native_ids": native_ids}]),
        m["information_rules"]["rules"].update(extensions=["x_native"]),
        m["information_rules"].update(native_id_extensions=[{"name": "x_native", "audit": "audits/x_native"}]),
    ))


def test_a_native_id_extension_is_enabled_and_audited(published: dict[str, Path], tmp_path: Path) -> None:
    directory = _copy(published, "unrated", tmp_path)
    _enable_native_extension(directory, audits={"x_native": "audits/x_native"})
    assert validate_tournament_dir(directory) == []
    _write_manifest(directory, _set("information_rules.native_id_extensions", []))
    assert validate_tournament_dir(directory) == [
        "manifest information_rules.native_id_extensions is a list of 0 items; recomputed: a list of 1 items "
        "(spec 12.2)",
    ]
    unaudited = _copy(published, "unrated", tmp_path / "unaudited")
    _enable_native_extension(unaudited, audits={})
    assert validate_tournament_dir(unaudited) == [
        "preflight refuses config.json under the manifest's engine_profile: extension 'x_native' without an audit "
        "(spec 11.1, 14)",
    ]
    plain = _copy(published, "unrated", tmp_path / "plain")
    _enable_native_extension(plain, audits={}, native_ids=False)
    assert validate_tournament_dir(plain) == [
        "manifest information_rules.native_id_extensions is a list of 1 items; recomputed: a list of 0 items "
        "(spec 12.2)",
    ]
    _write_manifest(plain, _set("engine_profile.extensions", []))
    assert validate_tournament_dir(plain) == [
        "preflight refuses config.json under the manifest's engine_profile: extension 'x_native' (spec 11.1, 14)",
    ]


def test_a_decklist_run_recomputes_its_card_name_domain(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    pile = {"name": "Pile", "decklist": [{"name": "Mountain", "count": 22}]}
    config = make_config(directory, BOTS, engine_args=("--decklists",), include_self_play=False, pairs=1,
                         deck_pool=("Burn",))
    config["deck_pool"] = [pile]
    run(config)
    assert validate_tournament_dir(directory) == []
    domain = {"domain_id": "sha256:" + hashlib.sha256(b'["Lightning Bolt","Mountain"]').hexdigest(),
              "names": ["Lightning Bolt", "Mountain"]}                       # a consistent domain, one name too many
    mountains = "sha256:" + hashlib.sha256(b'["Mountain"]').hexdigest()      # the domain of the decks played
    rows = ledger_rows(directory)
    assert rows[0]["decks"][0] == {"deck_id": deck_id(pile["decklist"]), "name": "Pile", "catalog_id": None}
    forged = _copy({"decklist": directory}, "decklist", tmp_path / "forged")
    _rewrite(forged, rows=[{**rows[0], "decks": [{**rows[0]["decks"][0], "deck_id": "sha256:" + "5" * 64},
                                                 rows[0]["decks"][1]]}, *rows[1:]])
    assert validate_tournament_dir(forged) == [
        "ledger row 0 does not match the schedule: decks differs", BOARD_JSON, BOARD_MD,
    ]
    _write_manifest(directory, _set("information_rules.rules.card_name_domain", domain))
    assert validate_tournament_dir(directory) == [
        f"manifest information_rules.rules.card_name_domain.domain_id is {_cut(domain['domain_id'])}; recomputed: "
        f"{_cut(mountains)} (spec 12.2)",
        "manifest information_rules.rules.card_name_domain.names is a list of 2 items; recomputed: a list of 1 items "
        "(spec 12.2)",
    ]


def test_a_manifest_that_cannot_be_rebuilt_never_passes(published: dict[str, Path], tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    directory = _copy(published, "unrated", tmp_path)
    monkeypatch.setattr(validate, "_information_rules", lambda *args: None)      # a check that bailed out silently
    assert validate_tournament_dir(directory) == ["manifest.json cannot be rebuilt from the run's files"]


def test_a_missing_or_unreadable_file_is_named(published: dict[str, Path], tmp_path: Path) -> None:
    for name in HASHED:
        directory = tmp_path / name
        shutil.copytree(published["unrated"], directory)
        (directory / name).unlink()
        assert validate_tournament_dir(directory)[0] == f"missing file: {name}"
        (directory / name).mkdir()
        assert validate_tournament_dir(directory)[0] == f"{name} is not a regular file"


def test_a_manifest_that_is_not_the_v2_record_fails_before_anything_else(published: dict[str, Path],
                                                                         tmp_path: Path) -> None:
    directory = _copy(published, "unrated", tmp_path)
    document = manifest(directory)
    (directory / "manifest.json").write_text(json.dumps(document) + "\n", encoding="utf-8", newline="\n")
    assert validate_tournament_dir(directory) == ["manifest.json is not canonical JSON (spec 4.3)"]
    _write_manifest(directory, lambda m: m.pop("engine_files"))
    assert validate_tournament_dir(directory) == ["manifest.json fields mismatch: missing=['engine_files'] extra=[]"]
    (directory / "manifest.json").write_bytes(b"[]\n")
    assert validate_v2_run(directory) == ["manifest.json: top-level JSON value is not an object"]
    (directory / "manifest.json").unlink()
    assert validate_v2_run(directory) == ["missing file: manifest.json"]
    assert validate_tournament_dir(directory) == [f"{directory} has no manifest.json (not a published tournament)"]


def test_every_failure_is_one_printable_ascii_line(published: dict[str, Path], tmp_path: Path) -> None:
    directory = _copy(published, "unrated", tmp_path)
    (directory / "caf\u00e9.txt").write_text("x", encoding="utf-8")
    _write_manifest(directory, _set("run.label", "line\nbreak"))
    failures = validate_tournament_dir(directory)
    assert failures == [
        "unexpected file in the run directory: caf\\xe9.txt",
        'the commitment in COMMITMENT.json was made for another run: its run_label is null, this run\'s label is '
        '"line\\nbreak" (spec 11.6, R3-30)',
    ]
    assert all(failure.isascii() and failure.isprintable() for failure in failures)


def test_the_cli_reports_each_failure(published: dict[str, Path], tmp_path: Path, capsys) -> None:
    directory = _copy(published, "unrated", tmp_path)
    assert cli.main(["validate", str(directory)]) == 0
    assert capsys.readouterr().out == f"OK {directory}: digests verified, ratings re-derived from the ledger\n"
    (directory / "notes.txt").write_text("x", encoding="utf-8")
    _write_manifest(directory, _set("run.status", "aborted"))
    assert cli.main(["validate", str(directory)]) == 1
    assert capsys.readouterr().err.splitlines() == [
        "FAIL unexpected file in the run directory: notes.txt",
        'FAIL manifest run.status is "aborted"; recomputed: "complete" (R3-13)',
    ]
