"""Optional operator-only engine transcripts with bounded, acknowledged collection."""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
import re
from pathlib import Path

from .. import wire

CONFIG_ENV = "SPELLBENCH_ENGINE_RECORDING"
HASH_ENV = "SPELLBENCH_ENGINE_RECORDING_SHA256"
FROM_ENV = object()


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def settings(environ=None):
    environ = os.environ if environ is None else environ
    path, expected = environ.get(CONFIG_ENV), environ.get(HASH_ENV)
    if not path and not expected:
        return None
    if not path or not expected or sha(path) != expected:
        raise ValueError("operator engine recording config differs from its pin")
    data = json.loads(Path(path).read_bytes())
    if (data.get("schema") != "spellbench-engine-recording/v1"
            or not Path(data["root"]).is_absolute()
            or type(data["per_game_cap_bytes"]) is not int or not 0 < data["per_game_cap_bytes"] <= 128*2**20
            or type(data["collection_timeout_seconds"]) is not int or not 0 < data["collection_timeout_seconds"] <= 3600
            or not Path(data["cold_source"]).is_absolute() or not Path(data["recovery"]).is_absolute()):
        raise ValueError("invalid bounded operator engine recording config")
    transport = data.get("transport", {})
    if (not re.fullmatch(r"[A-Za-z0-9_.@-]+", transport.get("ssh_target", ""))
            or type(transport.get("poll_seconds")) is not int or not 1 <= transport["poll_seconds"] <= 60
            or type(transport.get("command_timeout_seconds")) is not int or not 1 <= transport["command_timeout_seconds"] <= 120
            or type(transport.get("copy_timeout_seconds")) is not int or not 1 <= transport["copy_timeout_seconds"] <= 600
            or transport.get("compression") not in ("gzip", "none")
            or not isinstance(data.get("source_sha256"), dict)
            or data.get("remote_config_path") != str(path)
            or any(type(data.get(key)) is not int or data[key] <= 0
                   for key in ("cold_cap_bytes", "recovery_cap_bytes", "reserve_bytes"))
            or data["reserve_bytes"] < 60*2**30):
        raise ValueError("invalid pinned operator collection transport")
    data["_config_path"], data["_config_sha256"] = str(path), expected
    assert_current(data)
    return data


def identity(data):
    if data is None:
        return None
    package = Path(__file__).resolve().parents[1]
    paths = [Path(__file__), package / "arena/runner.py", package / "arena/executor.py",
             package / "bench/run.py", package.parent / "tools/xmage_engine_record_collect.py"]
    return {"settings": data, "source_sha256": {str(path.relative_to(package.parent)): sha(path) for path in paths}}


def assert_current(data):
    if data is None:
        return
    if "_config_path" in data and sha(data["_config_path"]) != data["_config_sha256"]:
        raise ValueError("operator recording config changed during execution")
    if "source_sha256" in data and identity(data)["source_sha256"] != data["source_sha256"]:
        raise ValueError("operator recording pipeline differs from its declared source pins")


def put(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".partial")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    # A hard link publishes the complete fsynced file atomically and refuses an existing receipt.
    os.link(temporary, path)
    temporary.unlink()


def plain_path(path):
    path = Path(path)
    if any(parent.is_symlink() or parent.is_junction() for parent in (path, *path.parents)):
        raise ValueError("operator artifact path redirects through a link")
    return path


def work_command(command, directory):
    command = list(command)
    if "--work" in command:
        command[command.index("--work") + 1] = str(directory)
    return command


class EngineRecord:
    def __init__(self, data, context):
        self.data = data
        root = plain_path(data["root"])
        root.mkdir(parents=True, exist_ok=True)
        self.directory = root / f"game-{context.game_index}-{context.game_id}-{uuid.uuid4().hex}"
        self.directory.mkdir()
        self.path = self.directory / "engine.jsonl"
        self.stream = self.path.open("xb")
        self.bytes = 0

    def write(self, direction, payload):
        line = wire.canonical_json_dumps({"dir": direction, "message": wire.strict_json_loads(payload)}) + b"\n"
        if self.bytes + len(line) > self.data["per_game_cap_bytes"]:
            raise ValueError("operator engine transcript exceeded its declared per-game byte cap")
        self.stream.write(line)
        self.stream.flush()
        self.bytes += len(line)

    def close(self):
        if not self.stream.closed:
            self.stream.flush()
            os.fsync(self.stream.fileno())
            self.stream.close()

    def seal(self, row):
        self.close()
        engine_work = self.directory / "engine-work"
        if engine_work.exists() and any(engine_work.iterdir()):
            raise ValueError("private engine working database remains after cleanup")
        for agent_work in self.directory.glob("agent-work-*"):
            for path in agent_work.iterdir():
                if path.is_dir():
                    raise ValueError("private model working database remains after cleanup")
                if path.name.endswith(".owned.json"):
                    cleanup = path.with_name(path.name.replace(".owned.json", ".cleanup.json"))
                    owned = json.loads(path.read_bytes())
                    cleaned = json.loads(cleanup.read_bytes()) if cleanup.is_file() else {}
                    container = owned.get("container")
                    if (not isinstance(container, str) or not container or path.name != container + ".owned.json"
                            or cleaned.get("confirmed_absent") is not True or cleaned.get("container") != container):
                        raise ValueError("model container lacks confirmed cleanup before collection")
        receipt = {"schema": "spellbench-engine-record-ready/v1", "game_index": row.game_index,
                   "game_id": row.game_id, "row_sha256": hashlib.sha256(wire.canonical_json_dumps(row.to_json())).hexdigest(),
                   "transcript_sha256": sha(self.path), "transcript_bytes": self.path.stat().st_size,
                   "cold_source": self.data["cold_source"], "recovery": self.data["recovery"],
                   "config": identity(self.data), "operator_only": True}
        row_bytes = wire.canonical_json_dumps(row.to_json())
        with (self.directory / "ROW.json").open("xb") as stream:
            stream.write(row_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        receipt["row_bytes"] = len(row_bytes)
        put(self.directory / "READY.json", receipt)
        return str(self.directory)


class RecordPeer:
    def __init__(self, peer, record):
        self.peer, self.record = peer, record
    def write_line(self, payload):
        self.record.write("host_to_engine", payload)
        self.peer.write_line(payload)
    def read_line(self):
        payload = self.peer.read_line()
        self.record.write("engine_to_host", payload)
        return payload
    def set_timeout(self, seconds): self.peer.set_timeout(seconds)
    def stderr_text(self): return self.peer.stderr_text()
    def close(self): self.peer.close()


def acknowledgement(ready, name, ready_sha256):
    compressed = ready["config"]["settings"].get("transport", {}).get("compression") == "gzip"
    filename = "engine.jsonl.gz" if compressed else "engine.jsonl"
    return {"schema": "spellbench-engine-record-collected/v1", "ready_sha256": ready_sha256,
            "transcript_sha256": ready["transcript_sha256"], "transcript_bytes": ready["transcript_bytes"],
            "row_sha256": ready["row_sha256"], "row_bytes": ready["row_bytes"],
            "cold_path": str(Path(ready["cold_source"]) / name / filename),
            "recovery_path": str(Path(ready["recovery"]) / name / filename),
            "cold_verified": True, "recovery_verified": True}


def collect(directory, row, *, guard=None):
    """An ordered callback includes copy/verification latency in completed work."""
    if directory is None:
        return
    directory = Path(directory)
    plain_path(directory)
    ready_path = directory / "READY.json"
    ready = json.loads(ready_path.read_bytes())
    if ready["game_id"] != row.game_id or ready["game_index"] != row.game_index:
        raise ValueError("operator terminal game identity differs; attempt retained")
    row_bytes = wire.canonical_json_dumps(row.to_json())
    if ((directory / "ROW.json").read_bytes() != row_bytes
            or hashlib.sha256(row_bytes).hexdigest() != ready["row_sha256"]
            or len(row_bytes) != ready["row_bytes"]):
        raise ValueError("operator terminal row differs from callback row; attempt retained")
    deadline = time.monotonic() + ready["config"]["settings"]["collection_timeout_seconds"]
    ack_path = directory / "COLLECTED.json"
    while not ack_path.exists():
        if guard is not None:
            guard()
        if time.monotonic() > deadline:
            raise TimeoutError("operator transcript collection acknowledgement expired; attempt retained")
        time.sleep(0.25)
    ack = json.loads(ack_path.read_bytes())
    expected = acknowledgement(ready, directory.name, sha(ready_path))
    if ready["config"]["settings"].get("transport", {}).get("compression") == "gzip":
        digest, size = ack.get("compressed_sha256"), ack.get("compressed_bytes")
        if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest) or type(size) is not int or size <= 0:
            raise ValueError("operator compressed custody receipt is malformed")
        expected.update(compressed_sha256=digest, compressed_bytes=size)
    if ack != expected or sha(directory / "engine.jsonl") != ready["transcript_sha256"]:
        raise ValueError("operator transcript collection acknowledgement differs; hot copy retained")
    if guard is not None:
        guard()
    put(directory / "HOT-RELEASE.json", {**ack, "schema": "spellbench-engine-record-hot-release/v1",
                                        "note": "only the redundant hot transcript copy is released; receipts and attempts remain"})
    (directory / "engine.jsonl").unlink()
