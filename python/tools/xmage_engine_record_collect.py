"""Collect operator-only complete engine records to verified cold and recovery stores."""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from spellbench.arena import engine_records as records


def durable(path, data):
    path = records.plain_path(path)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("existing operator custody copy differs")
        return
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def preserve(bundle, data):
    """Verify complete input before acknowledging two fsynced, lossless copies."""
    bundle = Path(bundle)
    ready_raw = (bundle / "READY.json").read_bytes()
    ready = json.loads(ready_raw)
    row_raw = (bundle / "ROW.json").read_bytes()
    row = json.loads(row_raw)
    transcript = (bundle / "engine.jsonl").read_bytes()
    if (ready["config"] != records.identity(data) or ready["operator_only"] is not True
            or ready["game_index"] != row["game_index"] or ready["game_id"] != row["game_id"]
            or records.wire.canonical_json_dumps(row) != row_raw
            or hashlib.sha256(row_raw).hexdigest() != ready["row_sha256"] or len(row_raw) != ready["row_bytes"]
            or hashlib.sha256(transcript).hexdigest() != ready["transcript_sha256"]
            or len(transcript) != ready["transcript_bytes"] or len(transcript) > data["per_game_cap_bytes"]):
        raise ValueError("operator record differs from its complete pinned receipt")
    compressed = data.get("transport", {}).get("compression") == "gzip"
    payload = gzip.compress(transcript, compresslevel=6, mtime=0) if compressed else transcript
    name = "engine.jsonl.gz" if compressed else "engine.jsonl"
    ack = records.acknowledgement(ready, bundle.name, hashlib.sha256(ready_raw).hexdigest())
    if compressed:
        ack.update(compressed_sha256=hashlib.sha256(payload).hexdigest(), compressed_bytes=len(payload))
    for role, root in (("cold", data["cold_source"]), ("recovery", data["recovery"])):
        root = records.plain_path(root)
        root.mkdir(parents=True, exist_ok=True)
        extra = len(payload) + len(row_raw) + len(ready_raw) + len(json.dumps(ack)) + 4*4096
        check_storage(data, role, extra)
        destination = records.plain_path(root / bundle.name)
        destination.mkdir(parents=True, exist_ok=True)
        for filename, value in (("READY.json", ready_raw), ("ROW.json", row_raw), (name, payload)):
            durable(destination / filename, value)
            if (destination / filename).read_bytes() != value:
                raise ValueError("operator custody readback differs")
        if compressed and gzip.decompress((destination / name).read_bytes()) != transcript:
            raise ValueError("operator lossless custody reconstruction differs")
        durable(destination / "COLLECTED.json", json.dumps(ack, sort_keys=True).encode() + b"\n")
        check_storage(data, role, 0)
    return ack


def check_storage(data, role, extra):
    root = records.plain_path(data["cold_source" if role == "cold" else "recovery"])
    root.mkdir(parents=True, exist_ok=True)
    cap = data.get(role + "_cap_bytes")
    if cap is None:
        return  # Pure receipt tests do not launch the transport; pinned CLI settings require caps.
    files = [p for p in root.rglob("*") if p.is_file()]
    for p in files:
        records.plain_path(p)
    physical_bound = sum(((p.stat().st_size + 4095)//4096)*4096 for p in files)
    if physical_bound + extra > cap or shutil.disk_usage(root).free - extra < data["reserve_bytes"]:
        raise ValueError("operator custody cap or target reserve would be exceeded")


def powershell(target, text, timeout):
    encoded = base64.b64encode(text.encode("utf-16-le")).decode()
    return subprocess.run(["ssh", "-o", "BatchMode=yes", target, "powershell", "-NoLogo", "-NoProfile",
                           "-NonInteractive", "-EncodedCommand", encoded], check=True,
                          capture_output=True, text=True, timeout=timeout).stdout.strip()


def quoted(path):
    return "'" + str(path).replace("'", "''") + "'"


def collect_remote(data, *, duration, stop):
    transport = data["transport"]
    target = transport["ssh_target"]
    timeout = transport["command_timeout_seconds"]
    root = str(data["root"]).replace("\\", "/")
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline and not stop.exists():
        code = (f"$r={quoted(root)}; $a=@(); if(Test-Path -LiteralPath $r){{"
                "Get-ChildItem -LiteralPath $r -Directory | ForEach-Object {"
                "if((Test-Path -LiteralPath ($_.FullName+'/READY.json')) -and "
                "-not(Test-Path -LiteralPath ($_.FullName+'/COLLECTED.json'))){$a+= $_.Name}}};"
                "ConvertTo-Json -InputObject @($a) -Compress")
        names = json.loads(powershell(target, code, timeout))
        for name in names:
            if not re.fullmatch(r"game-[0-9]+-[a-zA-Z0-9_-]+-[0-9a-f]{32}", name):
                raise ValueError("unexpected owned engine record directory")
            # Charge raw SSD staging before the first SCP, plus bounded receipt/row overhead.
            check_storage(data, "recovery", data["per_game_cap_bytes"] + 16*2**20)
            with tempfile.TemporaryDirectory(prefix="collection-", dir=data["recovery"]) as scratch:
                bundle = Path(scratch) / name
                bundle.mkdir()
                for filename in ("READY.json", "ROW.json", "engine.jsonl"):
                    subprocess.run(["scp", "-o", "BatchMode=yes", f"{target}:{root}/{name}/{filename}",
                                    str(bundle / filename)], check=True, timeout=transport["copy_timeout_seconds"])
                check_storage(data, "recovery", 0)
                ack = preserve(bundle, data)
                encoded = base64.b64encode(json.dumps(ack, sort_keys=True).encode() + b"\n").decode()
                final = f"{root}/{name}/COLLECTED.json"
                temporary = final + ".partial"
                script = (f"[IO.File]::WriteAllBytes({quoted(temporary)},[Convert]::FromBase64String('{encoded}'));"
                          f"Move-Item -LiteralPath {quoted(temporary)} -Destination {quoted(final)} -ErrorAction Stop")
                powershell(target, script, timeout)
                print(json.dumps({"state": "collected", "record": name, **ack}), flush=True)
        time.sleep(transport["poll_seconds"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--remote-config-path", required=True)
    parser.add_argument("--duration-seconds", type=int, required=True)
    parser.add_argument("--stop", type=Path, required=True)
    args = parser.parse_args()
    if records.sha(args.config) != args.config_sha256:
        raise ValueError("operator collector config differs")
    data = json.loads(args.config.read_bytes())
    if args.remote_config_path != data["remote_config_path"] or args.duration_seconds <= 0:
        raise ValueError("operator collector transport config or duration differs")
    data["_config_path"], data["_config_sha256"] = args.remote_config_path, args.config_sha256
    if records.identity(data)["source_sha256"] != data["source_sha256"]:
        raise ValueError("operator collector pipeline source differs")
    if os.name == "nt":
        from xmage_native_qualified_job import below_normal
        below_normal()
    for root in (data["cold_source"], data["recovery"]):
        Path(root).mkdir(parents=True, exist_ok=True)
    collect_remote(data, duration=args.duration_seconds, stop=args.stop)


if __name__ == "__main__":
    main()
