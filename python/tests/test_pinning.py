"""Engine and bot files pinned by hash, verified at launch and registered (ARTIFACT-LAW.md clauses 4 and 9)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from spellbench.bench.pinning import (
    CITED_BY, CLOSURE_STATUS, PinningError, engine_files, pin_and_register, pin_files, pinned_command, register_pins,
    register_tree, resolve_command, verify_files, verify_pins,
)


def _register_script(tmp_path: Path, *, show: str = "not found", body: str = "") -> tuple[Path, Path]:
    """A stand-in for the collab tools/artifact_register.py: it logs each call's arguments and answers "show"."""
    log = tmp_path / "calls.jsonl"
    script = tmp_path / "register.py"
    script.write_text("import json, os, sys\n"
                      f"open({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
                      f"{body}"
                      f"print({show!r} if sys.argv[1] == 'show' else 'registered')\n", encoding="utf-8")
    return script, log


def _calls(log: Path) -> list[list[str]]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def test_engine_files_hash_the_parts_that_name_files(tmp_path: Path) -> None:
    script = tmp_path / "engine.py"
    script.write_bytes(b"print('engine')\n")
    files = engine_files([sys.executable, str(script), "--flag"])
    assert [(file.index, file.file_name) for file in files] == [(0, Path(sys.executable).name), (1, "engine.py")]
    assert files[1].sha256 == hashlib.sha256(b"print('engine')\n").hexdigest()
    assert files[1].to_json() == {"index": 1, "file_name": "engine.py", "sha256": files[1].sha256, "bytes": 16}


def test_a_bare_engine_name_is_found_on_the_path_and_other_parts_must_be_files(tmp_path: Path, monkeypatch) -> None:
    bridge = tmp_path / "kernel-bridge"
    bridge.write_bytes(b"bridge")
    monkeypatch.setattr(shutil, "which", lambda name: str(bridge) if name == "kernel-bridge" else None)
    (file,) = engine_files(["kernel-bridge", "--deck=burn", str(tmp_path), str(tmp_path / "missing.bin")])
    assert (file.index, file.file_name, file.bytes) == (0, "kernel-bridge", 6)
    assert file == replace(file, path=tmp_path / "elsewhere")  # the path is not part of the identity


def test_an_unresolvable_command_is_refused_instead_of_pinning_nothing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    for command, reason in (
        ([], "empty"),
        (["${MTG_KERNEL_BRIDGE}"], "placeholder"),  # pauper-kernel's engine before placeholder expansion
        ([sys.executable, "${FAKE_ENGINE}"], "placeholder"),
        (["kernel-bridge"], "PATH"),
        ([str(tmp_path / "missing.exe")], "not a regular file"),
        ([str(tmp_path)], "not a regular file"),
    ):
        with pytest.raises(PinningError, match=reason):
            engine_files(command)


def test_declared_files_such_as_a_checkpoint_are_hashed_after_the_command(tmp_path: Path) -> None:
    bot, checkpoint = tmp_path / "bot.py", tmp_path / "g115.pt"
    bot.write_bytes(b"print('bot')\n")
    checkpoint.write_bytes(b"weights")
    files = engine_files([sys.executable, str(bot), "--seed", "3"], extra=[checkpoint])
    assert [(file.index, file.file_name) for file in files] == [(0, Path(sys.executable).name), (1, "bot.py"), (4, "g115.pt")]
    assert files[2].sha256 == hashlib.sha256(b"weights").hexdigest()
    with pytest.raises(PinningError, match="declared file"):
        engine_files([sys.executable], extra=[tmp_path / "missing.pt"])


def test_pinning_is_idempotent_and_detects_a_tampered_pin(tmp_path: Path) -> None:
    source = tmp_path / "bridge.exe"
    source.write_bytes(b"binary")
    (file,) = engine_files([str(source)])
    root = tmp_path / "pins"
    (pinned,) = pin_files([file], root)
    assert pinned == root / file.sha256 and (pinned / "bridge.exe").read_bytes() == b"binary"
    assert pin_files([file], root) == (pinned,)
    (pinned / "bridge.exe").write_bytes(b"tampered")
    with pytest.raises(PinningError, match="does not match"):
        pin_files([file], root)


def test_a_file_that_changes_after_hashing_is_not_pinned(tmp_path: Path) -> None:
    source = tmp_path / "bridge.exe"
    source.write_bytes(b"binary")
    (file,) = engine_files([str(source)])
    source.write_bytes(b"rebuilt")
    with pytest.raises(PinningError, match="changed"):
        pin_files([file], tmp_path / "pins")
    assert list((tmp_path / "pins").iterdir()) == []  # no file and no empty pin directory left behind


def test_an_unwritable_pin_root_is_an_error(tmp_path: Path) -> None:
    source = tmp_path / "bridge.exe"
    source.write_bytes(b"binary")
    (file,) = engine_files([str(source)])
    blocker = tmp_path / "pins"
    blocker.write_bytes(b"a file where the pin root should be")
    with pytest.raises(PinningError, match="cannot pin"):
        pin_files([file], blocker)


def test_a_launch_runs_the_hashed_bytes_and_refuses_files_changed_after_pinning(tmp_path: Path, monkeypatch) -> None:
    script = tmp_path / "engine.py"
    script.write_text("print('pinned build')\n", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda name: sys.executable if name == "python-for-tests" else None)
    resolved = resolve_command(["python-for-tests", str(script)])  # resolved once, for hashing and for launching
    files = engine_files(resolved)
    assert Path(resolved[0]) == files[0].path == Path(sys.executable).absolute()
    (script_file,) = [file for file in files if file.index == 1]
    root = tmp_path / "pins"
    pin_files([script_file], root)
    verify_files(files)
    verify_pins([script_file], root)
    script.write_text("print('rebuilt')\n", encoding="utf-8")  # a rebuild lands between pinning and launch
    with pytest.raises(PinningError, match="changed since it was hashed"):
        verify_files(files)
    verify_pins([script_file], root)
    launched = subprocess.run(pinned_command(resolved, [script_file], root), capture_output=True, text=True, check=True)
    assert launched.stdout.strip() == "pinned build"
    (root / script_file.sha256 / "engine.py").write_text("print('tampered')\n", encoding="utf-8")
    with pytest.raises(PinningError, match="does not match"):
        verify_pins([script_file], root)


def test_registration_calls_the_register_script(tmp_path: Path) -> None:
    log = tmp_path / "calls.json"
    script = tmp_path / "register.py"
    script.write_text(f"import json, sys\nopen({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n", encoding="utf-8")
    register_pins(script, [tmp_path / "pins" / "abc"], owner="spellbench", purpose="engine of run x", doc="manifest.json", regen="cargo build")
    (call,) = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert call[:3] == ["add", "--path", str(tmp_path / "pins" / "abc")]
    assert ["--retention", "keep-full"] == call[call.index("--retention"):call.index("--retention") + 2]


def test_a_failing_register_script_is_an_error(tmp_path: Path) -> None:
    script = tmp_path / "register.py"
    script.write_text("import sys\nsys.exit('catalog locked')\n", encoding="utf-8")
    with pytest.raises(PinningError, match="catalog locked"):
        register_pins(script, [tmp_path], owner="spellbench", purpose="p", doc="d", regen="r")


def test_a_new_pin_is_added_live_with_its_citing_run(tmp_path: Path) -> None:
    script, log = _register_script(tmp_path)
    directory = tmp_path / "pins" / "abc"
    register_pins(script, [directory], owner="spellbench", purpose="pinned engine files",
                  doc="benchmarks/x/runs/r/manifest.json", regen="cargo build", cited_by="x run r")
    show, add = _calls(log)
    assert show == ["show", "--id", str(directory)] and add[:3] == ["add", "--path", str(directory)]
    assert add[add.index("--status") + 1] == "live" and add[add.index("--note") + 1] == "cited by: x run r"


def test_a_shared_pin_keeps_its_first_citation_and_appends_the_next_run(tmp_path: Path) -> None:
    row = {"id": "p", "purpose": "first", "doc": "d1", "note": "cited by: x run r"}
    script, log = _register_script(tmp_path, show=json.dumps(row, indent=1))
    directory = tmp_path / "pins" / "abc"
    register_pins(script, [directory], owner="spellbench", purpose="second", doc="d2", regen="r", cited_by="x run r2",
                  status="frozen")
    register_pins(script, [directory], owner="spellbench", purpose="second", doc="d2", regen="r", cited_by="x run r")
    _, update, _, again = _calls(log)
    assert update[:3] == ["update", "--id", str(directory)] and "--purpose" not in update and "--doc" not in update
    assert update[update.index("--note") + 1] == "cited by: x run r; x run r2"
    assert update[update.index("--status") + 1] == "frozen"
    assert again[again.index("--note") + 1] == "cited by: x run r"  # already cited: the note is unchanged


def test_a_run_directory_is_registered_as_its_own_tree(tmp_path: Path) -> None:
    script, log = _register_script(tmp_path)
    register_tree(script, tmp_path / "runs" / "r", owner="spellbench", status="closed", purpose="published run x/r",
                  doc="benchmarks/x/runs/r/manifest.json", regen="spellbench bench rerun benchmarks/x/runs/r")
    (add,) = _calls(log)
    assert add[:3] == ["add", "--path", str(tmp_path / "runs" / "r")] and add[add.index("--status") + 1] == "closed"
    assert add[add.index("--retention") + 1] == "keep-full" and add[add.index("--lane") + 1] == "spellbench"


def test_registration_is_bounded_and_registers_each_directory_once(tmp_path: Path) -> None:
    script, log = _register_script(tmp_path)
    directory = tmp_path / "pins" / "abc"
    register_pins(script, [directory, directory], owner="o", purpose="p", doc="d", regen="r")
    assert len(_calls(log)) == 1
    stuck = tmp_path / "stuck.py"
    stuck.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    with pytest.raises(PinningError, match="within 0.5 s"):
        register_pins(stuck, [directory], owner="o", purpose="p", doc="d", regen="r", timeout_s=0.5)
    with pytest.raises(PinningError, match="cannot run"):
        register_pins(script, [directory], owner="o", purpose="p", doc="d", regen="r", python=str(tmp_path / "no-python.exe"))


def test_each_pin_is_catalogued_before_its_copy_lands_and_updated_after(tmp_path: Path) -> None:
    root = tmp_path / "pins"
    seen = tmp_path / "seen.jsonl"
    # Each call records the pin directories that hold a file at that moment.
    body = (f"root = {str(root)!r}\n"
            "held = sorted(name for name in (os.listdir(root) if os.path.isdir(root) else [])\n"
            "              if os.path.isdir(os.path.join(root, name)) and os.listdir(os.path.join(root, name)))\n"
            f"open({str(seen)!r}, 'a').write(json.dumps(held) + '\\n')\n")
    script, log = _register_script(tmp_path, body=body)
    first, second = tmp_path / "a.bin", tmp_path / "b.bin"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    files = engine_files([str(first), str(second)])
    directories = pin_and_register(files, root, script, owner="spellbench", purpose="engine of x run r", doc="d",
                                   regen="r", cited_by="x run r")
    one, two = files[0].sha256, files[1].sha256
    assert directories == (root / one, root / two)
    assert [call[0] for call in _calls(log)] == ["show", "add", "update", "show", "add", "update"]
    views = [json.loads(line) for line in seen.read_text(encoding="utf-8").splitlines()]
    assert views == [[], [], [one], [one], [one], sorted([one, two])]  # catalogued first, re-measured after the copy


def _catalog_script(tmp_path: Path) -> Path:
    """A register script over a JSON catalog beside it, whose "show" is slow: two unlocked writers would both read
    the same note before either writes, and the second write would drop the first run's citation."""
    script = tmp_path / "register.py"
    script.write_text(
        "import json, os, sys, time\n"
        "args, path = sys.argv[1:], os.path.splitext(sys.argv[0])[0] + '.json'\n"
        "rows = json.load(open(path))\n"
        "def arg(name):\n"
        "    return args[args.index(name) + 1] if name in args else None\n"
        "if args[0] == 'show':\n"
        "    time.sleep(1.0)\n"
        "    row = rows.get(arg('--id'))\n"
        "    print(json.dumps(row) if row else 'not found')\n"
        "else:\n"
        "    key = arg('--id') or arg('--path')\n"
        "    row = dict(rows.get(key, {}), status=arg('--status'))\n"
        "    if arg('--note') is not None:\n"
        "        row['note'] = arg('--note')\n"
        "    rows[key] = row\n"
        "    json.dump(rows, open(path, 'w'))\n",
        encoding="utf-8",
    )
    return script


def test_concurrent_citations_of_a_shared_pin_are_all_kept(tmp_path: Path) -> None:
    script = _catalog_script(tmp_path)
    directory = tmp_path / "pins" / "abc"
    catalog = tmp_path / "register.json"
    catalog.write_text(json.dumps({str(directory): {"note": "cited by: x run r", "status": "live"}}), encoding="utf-8")
    failures: list[BaseException] = []

    def cite(run: str) -> None:
        try:
            register_pins(script, [directory], owner="o", purpose="p", doc="d", regen="r", cited_by=run)
        except BaseException as exc:  # reported below: a thread's exception would otherwise vanish
            failures.append(exc)

    threads = [threading.Thread(target=cite, args=(run,)) for run in ("x run r2", "x run r3")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    note = json.loads(catalog.read_text(encoding="utf-8"))[str(directory)]["note"]
    assert failures == [] and note.startswith("cited by: x run r; ")
    assert sorted(note.split("; ")[1:]) == ["x run r2", "x run r3"]


# The collab tools/artifact_register.py pattern that matters here: main() loads the whole catalog first, and "add"
# and "update" start from the newest row for the id, set the given fields, and append the whole row (the newest line
# wins). A post-copy "update" (no --note) pauses after loading until the test releases it, bounded at 3 s.
_LOAD_THEN_APPEND = '''\
import json, os, sys, time
catalog = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ARTIFACTS", "catalog.jsonl")
rows = {}
if os.path.exists(catalog):
    for line in open(catalog, encoding="utf-8"):
        if line.strip():
            row = json.loads(line)
            rows[row["id"].lower()] = row
args = sys.argv[1:]
def arg(name):
    return args[args.index(name) + 1] if name in args else None
rid = os.path.normpath(arg("--path") or arg("--id")).replace("\\\\", "/").rstrip("/")
if args[0] == "show":
    print(json.dumps(rows[rid.lower()], indent=1) if rid.lower() in rows else "not found")
    sys.exit(0)
if args[0] == "update" and rid.lower() not in rows:
    sys.exit(f"unknown id {rid}; use add")
row = dict(rows.get(rid.lower(), {"id": rid, "paths": [rid]}))
for key in ("lane", "owner", "status", "retention", "purpose", "doc", "regen", "note"):
    if arg("--" + key):
        row[key] = arg("--" + key)
if args[0] == "update" and "--note" not in args:
    flag = os.environ["REGISTER_PAUSE_FLAG"]
    open(flag, "w").close()
    deadline = time.monotonic() + 3.0
    while not os.path.exists(flag + ".release") and time.monotonic() < deadline:
        time.sleep(0.02)
os.makedirs(os.path.dirname(catalog), exist_ok=True)
with open(catalog, "a", encoding="utf-8", newline="\\n") as handle:
    handle.write(json.dumps(row) + "\\n")
print("registered " + rid)
'''


def test_two_launches_citing_one_pin_keep_both_citations(tmp_path: Path, monkeypatch) -> None:
    """Launch B pins and catalogues an engine; while B's post-copy update holds the catalog it loaded, launch A cites
    the same pin. B's update must not append the row it loaded before A's citation (re-review race)."""
    script = tmp_path / "collab" / "tools" / "artifact_register.py"
    script.parent.mkdir(parents=True)
    script.write_text(_LOAD_THEN_APPEND, encoding="utf-8")
    flag = tmp_path / "loaded.flag"
    monkeypatch.setenv("REGISTER_PAUSE_FLAG", str(flag))
    engine = tmp_path / "engine.bin"
    engine.write_bytes(b"engine bytes")
    files = engine_files([str(engine)])
    pin_root = tmp_path / "pins"
    fields = {"owner": "spellbench", "purpose": "engine", "doc": "manifest.json", "regen": "cargo build"}
    failures: list[BaseException] = []

    def launch_b() -> None:
        try:
            pin_and_register(files, pin_root, script, cited_by="bench run B", **fields)
        except BaseException as exc:  # reported below: a thread's exception would otherwise vanish
            failures.append(exc)

    b = threading.Thread(target=launch_b)
    b.start()
    while not flag.exists():  # B's post-copy update has loaded the catalog and paused
        assert b.is_alive(), failures
        time.sleep(0.02)
    register_pins(script, [pin_root / files[0].sha256], cited_by="bench run A", **fields)
    Path(str(flag) + ".release").write_bytes(b"")  # unblocks B at once if B was not holding the pin's lock
    b.join()
    newest = json.loads((tmp_path / "collab" / "ARTIFACTS" / "catalog.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert failures == [] and newest["note"].startswith(CITED_BY)
    assert sorted(newest["note"][len(CITED_BY):].split("; ")) == ["bench run A", "bench run B"]


def test_a_held_catalog_lock_bounds_the_wait_and_a_stale_one_is_broken(tmp_path: Path) -> None:
    script, log = _register_script(tmp_path)
    directory = tmp_path / "pins" / "abc"
    directory.parent.mkdir(parents=True)
    lock = directory.with_name("abc.lock")
    lock.write_text("4242", encoding="utf-8")  # another launch is writing this pin's catalog row
    for cited_by in ("x run r", None):  # a plain add re-appends the row it loads, so it waits for the lock too
        with pytest.raises(PinningError, match="lock"):
            register_pins(script, [directory], owner="o", purpose="p", doc="d", regen="r", cited_by=cited_by,
                          timeout_s=0.5)
    assert not log.exists()
    an_hour_ago = time.time() - 3600
    os.utime(lock, (an_hour_ago, an_hour_ago))  # left by a launch that crashed an hour ago
    register_pins(script, [directory], owner="o", purpose="p", doc="d", regen="r", cited_by="x run r")
    assert not lock.exists() and [call[0] for call in _calls(log)] == ["show", "add"]


def test_registration_uses_the_catalog_statuses_and_pins_freeze_at_closure(tmp_path: Path) -> None:
    assert CLOSURE_STATUS == "frozen"  # Decision 10: a closed run's pins stay, frozen
    script, log = _register_script(tmp_path)
    for register in (lambda: register_pins(script, [tmp_path / "pins" / "abc"], owner="o", purpose="p", doc="d",
                                           regen="r", status="done"),
                     lambda: register_tree(script, tmp_path / "runs" / "r", owner="o", status="archived", purpose="p",
                                           doc="d", regen="r")):
        with pytest.raises(PinningError, match="status"):
            register()
    assert not log.exists()
