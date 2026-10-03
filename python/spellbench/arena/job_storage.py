"""Whole-job storage admission and reconciliation, including logs and staging."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from .allocation import ThroughputError
from .machine import RESERVE_BYTES

ROOT_ENV = "SPELLBENCH_JOB_ROOT"


def validate_settings(value):
    if value is None:
        return None
    if (type(value) is not dict or set(value) != {"projected_bytes", "cap_bytes"}
            or any(type(count) is not int or not 0 < count <= (1 << 53) - 1 for count in value.values())
            or value["projected_bytes"] > value["cap_bytes"]):
        raise ValueError("job_storage_budget requires positive projected_bytes <= cap_bytes")
    return dict(value)


def tree_bytes(root: Path) -> int:
    """Conservatively count every file, including broker logs and recovery copies.

    Links outside the owned job root are refused rather than silently omitted.
    Internal directory links are skipped; their canonical files are counted.
    """
    def scan_error(error):
        raise ThroughputError("cannot enumerate whole-job storage") from error

    total = 0
    for directory, folders, files in os.walk(root, followlinks=False, onerror=scan_error):
        for name in list(folders):
            path = Path(directory) / name
            if path.is_symlink() or path.is_junction():
                if not path.resolve().is_relative_to(root):
                    raise ThroughputError("job storage contains an external directory link")
                folders.remove(name)
        for name in files:
            path = Path(directory) / name
            try:
                if path.is_symlink() and not path.resolve().is_relative_to(root):
                    raise ThroughputError("job storage contains an external file link")
                stat = path.stat()
                # Allocation blocks when available; logical bytes remain a
                # conservative floor for sparse/compressed files and Windows.
                total += max(stat.st_size, getattr(stat, "st_blocks", 0) * 512)
            except FileNotFoundError:
                continue  # an atomic writer replaced its temporary file
    return total


class JobStorageGuard:
    def __init__(self, settings, *, environ, paths=()):
        self.settings = validate_settings(settings)
        if self.settings is None:
            raise ValueError("whole-job storage settings are required")
        raw = environ.get(ROOT_ENV)
        if not raw or not Path(raw).is_absolute():
            raise ThroughputError(f"whole-job storage guard needs absolute {ROOT_ENV}")
        self.root = Path(raw).resolve(strict=True)
        if not self.root.is_dir():
            raise ThroughputError("job storage root is not a directory")
        for path in paths:
            if not Path(path).resolve().is_relative_to(self.root):
                raise ThroughputError("run, pins and qualification staging must be inside the owned job root")
        self.initial = tree_bytes(self.root)
        self.previous = self.initial
        self.peak_game_growth = 0
        self.projected = self.settings["projected_bytes"]
        self.check()

    def check(self):
        actual = tree_bytes(self.root)
        if max(actual, self.projected) > self.settings["cap_bytes"]:
            raise ThroughputError("whole-job storage exceeds its declared cap")
        remaining = max(0, self.projected - actual)
        if shutil.disk_usage(self.root).free - remaining < RESERVE_BYTES:
            raise ThroughputError("whole-job storage would breach the 60 GiB reserve")
        return actual

    def reconcile_game(self, games_total, *, qualification_games=0):
        actual = self.check()
        self.peak_game_growth = max(self.peak_game_growth, actual - self.previous)
        self.previous = actual
        # All files under the root are included. Two copies of measured game
        # growth cover hot evidence and its staged recovery archive. Existing
        # runtime, source, pins and qualification bytes stay in the baseline.
        forecast = actual + 2 * self.peak_game_growth * (games_total + qualification_games)
        self.projected = max(self.projected, forecast)
        self.check()
        receipt = {"schema": "spellbench-whole-job-storage/v1", "actual_bytes": actual,
                   "projected_bytes": self.projected, "cap_bytes": self.settings["cap_bytes"],
                   "peak_game_growth_bytes": self.peak_game_growth,
                   "reserve_bytes": RESERVE_BYTES, "includes": ["logs", "qualification", "staging", "pins", "recovery"]}
        target = self.root / "storage-reconciliation.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(target)
