"""RunPod cgroup v1/v2 limits must bound host-wide resource reports."""

from pathlib import Path

import pytest

from spellbench.arena import machine


@pytest.mark.parametrize("version", [1, 2])
def test_container_cpu_quota_affinity_and_memory_bound_machine_facts(monkeypatch, version):
    files = ({"/sys/fs/cgroup/cpu/cpu.cfs_quota_us": "200000",
              "/sys/fs/cgroup/cpu/cpu.cfs_period_us": "100000",
              "/sys/fs/cgroup/memory/memory.limit_in_bytes": "8000000000"} if version == 1 else
             {"/sys/fs/cgroup/cpu.max": "200000 100000", "/sys/fs/cgroup/memory.max": "8000000000"})
    def read(path, **kwargs):
        if path.as_posix() not in files:
            raise OSError("absent cgroup file")
        return files[path.as_posix()]
    monkeypatch.setattr(machine.sys, "platform", "linux")
    # Replace only this module's os, preserving the actual platform elsewhere.
    from types import SimpleNamespace
    monkeypatch.setattr(machine, "os", SimpleNamespace(name="posix", process_cpu_count=lambda: 192,
                                                       sched_getaffinity=lambda pid: {1, 2, 3, 4},
                                                       sysconf=lambda key: 4096 if key == "SC_PAGE_SIZE" else 200000000))
    monkeypatch.setattr(Path, "read_text", read)
    assert machine.usable_cpus() == 2
    assert machine.total_memory() == 8000000000
    files.clear()
    assert machine.usable_cpus() == 4
    assert machine.total_memory() == 819200000000
