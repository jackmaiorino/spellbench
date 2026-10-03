"""This machine, as a launch sees it: cores, memory, GPUs, free space and CPU use (standard library only).

:func:`machine_facts` records what COMPUTE-POLICY.md item 1 asks a
placement to consider, keyed by volume role (``run_dir``, ``pin_root``) and
never by path; :func:`check_reserve` keeps every target volume
``RESERVE_BYTES`` free (ARTIFACT-LAW.md clause 1); :class:`CpuSampler`
feeds the idle monitor (COMPUTE-POLICY.md item 6). An allocation names its
machine by an alias (:func:`host_name`), never by the machine's own name.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .allocation import VOLUME_ROLES, MachineFacts, ThroughputError

# Free space every target volume keeps (ARTIFACT-LAW.md clause 1).
RESERVE_BYTES = 60 * 2**30

# The alias an allocation publishes for its machine (R3-28): this variable's value, else DEFAULT_HOST_ALIAS.
HOST_ALIAS_ENV = "SPELLBENCH_HOST_ALIAS"
DEFAULT_HOST_ALIAS = "local"

_MAX_INT = (1 << 53) - 1


def host_name(host: str | None = None) -> str:
    """The host an allocation records: ``host`` when given, else ``SPELLBENCH_HOST_ALIAS``, else ``"local"``.

    The manifest publishes it, so it is an alias the operator chooses and
    never this machine's network name (R3-28). It also keys the reuse of
    local throughput evidence, so machines that share an evidence file need
    distinct aliases.
    """
    if host is not None:
        return host
    return os.environ.get(HOST_ALIAS_ENV, "").strip() or DEFAULT_HOST_ALIAS


def cgroup_cpus(text: str | None) -> int | None:
    """The CPUs a cgroup v2 ``cpu.max`` quota allows (``"<quota> <period>"``), or None without a quota."""
    parts = (text or "").split()
    if len(parts) != 2 or not all(part.isdigit() for part in parts) or int(parts[1]) == 0:
        return None
    return max(1, math.ceil(int(parts[0]) / int(parts[1])))


def usable_cpus(cpu_count: int | None = None) -> int:
    """``cpu_count``, or the CPUs this process may use, bounded by a Linux container's quota (RunPod)."""
    if cpu_count is not None:
        return cpu_count
    count = (getattr(os, "process_cpu_count", None) or os.cpu_count)() or 1
    if sys.platform.startswith("linux"):
        try:
            quota = cgroup_cpus(Path("/sys/fs/cgroup/cpu.max").read_text(encoding="ascii"))
        except (OSError, UnicodeDecodeError):
            quota = None
        if quota is None:
            try:
                quota = cgroup_cpus(" ".join(Path("/sys/fs/cgroup/cpu/" + name).read_text(encoding="ascii").strip()
                                             for name in ("cpu.cfs_quota_us", "cpu.cfs_period_us")))
            except (OSError, UnicodeDecodeError):
                quota = None
        try:
            count = min(count, len(os.sched_getaffinity(0)))
        except (AttributeError, OSError):
            pass
        if quota is not None:
            count = min(count, quota)
    return count


def total_memory() -> int | None:
    """Physical memory bounded by the Linux container limit, or None if unknown."""
    try:
        if os.name == "nt":
            import ctypes

            class _MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                    (name, ctypes.c_ulonglong) for name in ("total_phys", "avail_phys", "total_page", "avail_page",
                                                            "total_virtual", "avail_virtual", "avail_extended")
                ]

            status = _MemoryStatus()
            status.length = ctypes.sizeof(status)
            total = int(status.total_phys) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else 0
        else:
            total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            if sys.platform.startswith("linux"):
                for filename in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
                    try:
                        limit = Path(filename).read_text(encoding="ascii").strip()
                        if limit.isdigit() and int(limit) > 0:
                            total = min(total, int(limit))
                    except (OSError, UnicodeDecodeError):
                        pass
    except (AttributeError, OSError, ValueError):
        return None
    return total if 0 < total <= _MAX_INT else None


def nvidia_gpus(*, timeout_s: float = 10.0) -> tuple[str, ...]:
    """The NVIDIA GPUs ``nvidia-smi`` lists, or none when it is absent or fails."""
    program = shutil.which("nvidia-smi")
    if program is None:
        return ()
    try:
        result = subprocess.run([program, "--query-gpu=name", "--format=csv,noheader"], stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=timeout_s, check=False)
    except (OSError, subprocess.SubprocessError):
        return ()
    if result.returncode != 0:
        return ()
    return tuple(line.strip() for line in result.stdout.decode("utf-8", errors="replace").splitlines() if line.strip())


def free_bytes(path: Path) -> int:
    """Free bytes on the volume that holds ``path``, or its nearest existing parent."""
    candidate = Path(path).absolute()
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    try:
        return shutil.disk_usage(candidate).free
    except OSError as exc:
        raise ThroughputError(f"cannot read the free space for {path}: {exc}") from exc


def machine_facts(
    volumes: Mapping[str, Path],
    *,
    memory: Callable[[], int | None] = total_memory,
    gpus: Callable[[], Sequence[str]] = nvidia_gpus,
    disk_free: Callable[[Path], int] = free_bytes,
) -> MachineFacts:
    """This machine's memory, GPUs and the free bytes of each target volume, by role (``run_dir``, ``pin_root``)."""
    return MachineFacts(memory_bytes=memory(), gpus=tuple(gpus()),
                        free_bytes=tuple(sorted((role, disk_free(Path(path))) for role, path in volumes.items())))


def check_reserve(machine: MachineFacts, projected_bytes: int) -> None:
    """Refuse unless the facts cover ``run_dir`` and ``pin_root`` and every volume keeps ``RESERVE_BYTES`` free
    after ``projected_bytes`` more.

    Each volume is charged the whole projection, which is conservative when
    the rows and the pins land on different volumes.
    """
    if machine.missing_roles:
        raise ThroughputError(
            f"the reserve check needs the free space of {' and '.join(VOLUME_ROLES)}; "
            f"the machine facts lack {', '.join(machine.missing_roles)} (ARTIFACT-LAW.md clause 1)"
        )
    for role, free in machine.free_bytes:
        if free - projected_bytes < RESERVE_BYTES:
            raise ThroughputError(
                f"{role} has {free / 2**30:.1f} GiB free; {projected_bytes} more bytes would leave less than the "
                f"{RESERVE_BYTES // 2**30} GiB reserve (ARTIFACT-LAW.md clause 1)"
            )


def _system_times() -> tuple[int, int] | None:
    """Windows ``GetSystemTimes``: (idle, kernel + user) in 100 ns units since boot; kernel time includes idle."""
    try:
        import ctypes
        from ctypes import wintypes

        idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
    except (AttributeError, ImportError, OSError):
        return None

    def ticks(value: Any) -> int:
        return (value.dwHighDateTime << 32) | value.dwLowDateTime

    return ticks(idle), ticks(kernel) + ticks(user)


def _load_share() -> float | None:
    """POSIX: the one-minute load average per logical CPU, capped at 1."""
    try:
        load = os.getloadavg()[0]
    except (AttributeError, OSError):
        return None
    return min(1.0, max(0.0, load / (os.cpu_count() or 1)))


class CpuSampler:
    """The machine's CPU busy share since the previous sample (COMPUTE-POLICY.md item 6).

    Windows reads ``GetSystemTimes`` through ctypes, and its first sample is
    None (nothing to compare with yet); POSIX reports the load average per
    CPU. ``counters`` replaces the Windows source with any function returning
    cumulative ``(idle, total)`` ticks.
    """

    def __init__(self, counters: Callable[[], tuple[int, int] | None] | None = None) -> None:
        self._counters = counters if counters is not None else (_system_times if os.name == "nt" else None)
        self._last: tuple[int, int] | None = None

    def sample(self) -> float | None:
        if self._counters is None:
            return _load_share()
        now = self._counters()
        last, self._last = self._last, now
        if now is None or last is None or now[1] <= last[1]:
            return None
        return min(1.0, max(0.0, 1.0 - (now[0] - last[0]) / (now[1] - last[1])))
