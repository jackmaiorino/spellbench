"""Engine files pinned by hash and registered (ARTIFACT-LAW.md clauses 4 and 9)."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from spellbench.bench.pinning import PinningError, engine_files, pin_files, register_pins


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
    assert [path for path in (tmp_path / "pins").rglob("*") if path.is_file()] == []


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
