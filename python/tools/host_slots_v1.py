"""Core slots beside the host reservation (v1): untimed work uses the cores timed work leaves free.

host_reservation_v1.py (mtg-kernel python/tools) reserves a whole host with
one lock file, <root>/<HOST>.lock. This module never writes that lock and
never changes what it means. It keeps its own records beside it, under
<root>/<HOST>.slots/:

- Timed work that holds the v1 reservation may give back the cores it does
  not need. `timed --cores 0-7 -- CMD`, run inside the v1 supervisor (so
  MTG_HOST_RESERVATION_TOKEN names the held lock), pins CMD and all its
  descendants to those cores. While CMD runs, it declares them in
  share-<token hash>.json. A reservation acquired with `--cores SPEC`
  records its cores in the lock itself, and those count from the moment
  the lock exists (before `timed` starts and after it ends). Without either,
  a held v1 lock still reserves the whole host, exactly as before.
- Untimed work runs as `run --cores N [--wait] -- CMD`. It claims N cores
  that no declaration and no other claim holds. It pins CMD and all its
  descendants to those cores at the configured priority (below normal by
  default), and it frees the cores once the whole process tree has ended.
  Whenever a held v1 lock leaves the claim no room, every process in the
  claim is suspended until the room comes back. A lock leaves no room when
  it has no declaration, or when its declaration overlaps the claim's
  cores. Timed work therefore never shares a core with untimed work.
- With `--wait`, a claim joins the queue, and queued claims start in
  arrival order as cores free up. `submit` starts a detached waiting `run`
  and returns at once.
- Backfill: a request that declares `--max-seconds S` may start before the
  queue head when it fits in free cores now (never a background claim's) and
  cannot delay the head, under every order in which the live claims could end
  (at most 12 claims, never while a timed reservation is held, and only when
  the head was queued under the current config). A request that could delay
  the head may still start when the head declared its own --max-seconds H
  and every such delaying backfill for that head fits in one window (first
  start to last deadline) of at most min(15 minutes, H / 10); none starts
  while an earlier one is overdue. Only the first eligible request behind
  the head starts, and only ordinary requests behind an ordinary head. S is
  at most 30 days.
- Any claim with --max-seconds S is handled by its own runner once S has
  passed (--on-overdue): flag (default) only marks it; demote (opt-in)
  republishes it as background work that ordinary claims and timed holds
  may suspend; kill (opt-in) ends its own job's processes outside the
  admission mutex (never the runner, never another claim). A flag request
  carries backfill_policy 0 and never gets a delaying backfill.
- Shared claims (`run --shared --cores N --min-cores M`): the claim guarantees
  M cores and lends the rest of its current cores. A later claim may take a
  lent core; the shared claim narrows its job's affinity before it republishes
  its cores, and the later claim starts only after that (as with background
  claims). Lenders also give cores back to keep occupied cores within the
  budget (configured minus keep_free), give back every lent core while any
  request is queued, and grow onto cores no claim runs on only while nothing
  is queued. While it lends, a deliberately unreadable delay-lending-<id>.json
  stops every backfill engine at or after c543e1b4 (mtg-kernel e2657b8c,
  #427). Older engines (#407) ignore it, so shared claims are off on a host
  until its config says "lending": true, which the deploy sets only once no
  older copy can queue there. Never for timing work.
- `--core-pool` is a hard restriction and needs `--pool-reason` (POOL_REASONS).
- `status` prints the timed reservation (lane, work and declared cores),
  the claims, the queue and the free cores. It never prints the token.
- `watch` samples per-CPU use and the records, logs to <root>/<HOST>.util/,
  flags low use and queued requests beside unclaimed cores, and nudges;
  it never changes a claim. `watch-report` sums its logs and the runners'
  admit/end events.
  `topology` lists the logical CPUs with each core's efficiency class:
  hybrid Intel P cores rank above E cores.

Background jobs (`run --background` or Windows `adopt --background`) yield
to both timed reservations and ordinary claims. Ordinary admission waits
for complete suspension before using borrowed CPUs. Once a background or
shared command exits, its remaining descendants drain on the CPUs they still
need. Shared claims give back lent CPUs if their descendants can narrow.
Timed reservations and acknowledged handoffs still take precedence, and new
requests wait for CPUs the draining tree still holds. Background tickets come after
every ordinary ticket. OS --priority is independent of this allocation class;
CI uses --background --priority idle. `adopt` watches a verified existing worker
and all descendants until its job object empties.
Idle CI listeners do not need a claim.

Rollout: switch all launchers on the host together, once there are no claim
or queue records (running, suspended or waiting). Old and new launchers
must never run together on the same host.

Optional per-host config, <root>/<HOST>.slots/config.json:
  {"cores": "23-0", "keep_free": 0, "priority": "below_normal", "ci_floor": 0}
"ci_floor" reserves the last that many cores in preference order for background
(CI) claims, which try them first; no other claim takes them.
"cores" lists the cores untimed work may use, in order of preference. The
default is every logical CPU, highest-numbered first, so claims stay off the
low-numbered cores (P cores on hybrid Intel) that timed work usually
declares. "keep_free" is how many of those cores are never handed out, for
the owner of a shared machine. "priority" is the default for claims, one of
normal, below_normal or idle.

Containment: on Windows, each claim (and each timed declaration) runs in a
job object. The job kills every member when its runner exits, sets the
affinity of the whole tree, and for claims also sets the priority class of
the whole tree. On Linux the claim runs in its own session. Affinity and
nice values are inherited, and suspension uses SIGSTOP/SIGCONT on that
process group, so a process that leaves the group escapes. Linux is
supported for WSL runners and tests; Windows is the production platform.

CLI (JSON on stdout; exit 0 ok, 2 usage, 3 no room, 6 refused):
  run --lane L --work-id W --cores N [--wait] [--wait-timeout S] [--max-seconds S] [--priority P] [--id ID] [--cwd DIR]
      [--shared [--min-cores M]] [--core-pool SPEC --pool-reason R] [--on-overdue A] -- CMD...
  submit --log FILE (same options as run) -- CMD...
  timed --cores SPEC [--cwd DIR] -- CMD...
  status
  topology
  watch [--interval S] [--once] [--duration S] [-- NOTIFY_CMD...]
  watch-report [--since ISO] [--until ISO]
Roots and host move only through HOST_SLOTS_ROOT / HOST_SLOTS_HOST.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import struct
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = "spellbench-host-slots/v1"
LOCK_SCHEMA = "mtg-host-reservation/v1"
TOKEN_ENV = "MTG_HOST_RESERVATION_TOKEN"
ROOT_ENV = "HOST_SLOTS_ROOT"
HOST_ENV = "HOST_SLOTS_HOST"
POLL_ENV = "HOST_SLOTS_POLL_SECONDS"
GROW_ENV = "HOST_SLOTS_GROW_SECONDS"
CLAIM_ENV = "HOST_SLOTS_CLAIM"
CORES_ENV = "HOST_SLOTS_CORES"
# A Linux container's granted CPUs need not be 0..n-1 (a 32-vCPU RunPod Pod on a 192-CPU host was granted 5, 9,
# 11, ...). This variable lists the granted CPUs; under it the host is n logical CPUs 0..n-1, logical i being the
# i-th listed CPU: cpu_total, topology, pinning and current_affinity speak logical CPUs, so the records of work
# placed here carry the same CPU lists on every such host.
CPU_BINDING_ENV = "MTG_CPU_BINDING_V1"
CANONICAL_ROOT = "C:/mtg-node/host-lock" if os.name == "nt" else "/mnt/c/mtg-node/host-lock"
PRIORITIES = ("normal", "below_normal", "idle")
EXIT_OK, EXIT_USAGE, EXIT_HELD, EXIT_REFUSED = 0, 2, 3, 6
MUTEX_TIMEOUT_SECONDS = 30.0
MUTEX_STALE_SECONDS = 30.0
TIMED_VACATE_SECONDS = 60.0
BACKFILL_MAX_RUNNING = 12
BACKFILL_MAX_SECONDS = 30 * 86400.0
# Bounded delay: a backfill that could delay the head starts only if every such backfill for that head fits in one
# window (first start to last deadline) of at most min(15 minutes, 10% of the head's declared max seconds).
BACKFILL_DELAY_CAP_SECONDS = 900.0
BACKFILL_DELAY_HEAD_SHARE = 0.10
# Launchers that apply the bounded-delay rule record this in their queue tickets.
BACKFILL_POLICY = 2
# A core pool is a hard restriction, so it needs one of these recorded reasons.
POOL_REASONS = ("timing", "isolation", "determinism", "play-client", "hardware")
# A running shared claim tries to grow onto unclaimed cores at most this often.
SHARE_GROW_SECONDS = 10.0
# What a claim's own runner does once the claim outlives its declared --max-seconds (`--on-overdue`, default
# flag): flag only marks it; demote (opt-in) republishes it as background work, which every ordinary claim and
# timed hold may then take cores from (it suspends, as CI does, and resumes when they are free); kill (opt-in) ends
# its own job object's processes. A timed declaration is never a claim, so none of these ever touches timed work.
# Today's callers pass --max-seconds as an estimate, so enforcement is opt-in; flipping the default needs its own
# note to every caller.
OVERDUE_ACTIONS = ("flag", "demote", "kill")
# A --core-pool without --pool-reason is accepted until this UTC date (14 days after the deploy), recorded as
# core_pool_reason "unspecified" and nudged by the watcher; from this date on it is refused (exit 2).
POOL_REASON_REQUIRED_FROM = "2026-11-17"
POOL_REASON_UNSPECIFIED = "unspecified"


def pool_reason_required(today=None) -> bool:
    """Whether the pool-reason transition is over (HOST_SLOTS_TODAY, an ISO date, overrides today for tests)."""
    today = today or os.environ.get("HOST_SLOTS_TODAY") or datetime.now(timezone.utc).date().isoformat()
    return today >= POOL_REASON_REQUIRED_FROM
# While a shared claim lends any core it keeps this file, deliberately not a JSON object, beside the delay windows:
# every backfill engine at or after c543e1b4 (mtg-kernel e2657b8c, #427) refuses to backfill while a delay file
# cannot be read, so none of them (this one included) proves a backfill while a lent core could still be given
# back. The #407 engine (05fd27807) has no such refusal; config "lending" (below) keeps shared claims off a host
# until no such copy can queue there. This engine skips the markers and removes those whose claim is gone.
LENDING_MARKER = "delay-lending-"


class NoRoom(Exception):
    """Not enough free cores (or a queue ahead) and not waiting."""


class Refused(Exception):
    """A declaration or claim was refused."""


# ---------------------------------------------------------------- child command

WSL_BASH = re.compile(r"(?:^|[\\/])(?:system32|sysnative|windowsapps)[\\/]bash(?:\.exe)?$", re.IGNORECASE)


def child_command(command: list[str], windows: bool = os.name == "nt") -> list[str]:
    """Windows' CreateProcess searches System32 before PATH, so a bare `bash` starts WSL's bash.exe, which cannot
    see drive paths such as D:/ and exits at once, after the claim already took its queue turn. A bare `bash` runs
    the first Git Bash found instead (PATH, then the default install); WSL's bash is refused before any ticket."""
    if not windows or not command:
        return command
    program = command[0]
    if re.fullmatch(r"bash(?:\.exe)?", program, re.IGNORECASE):
        install = os.path.join(os.environ.get("ProgramFiles", "C:/Program Files"), "Git", "bin", "bash.exe")
        for folder in [*os.environ.get("PATH", "").split(os.pathsep), os.path.dirname(install)]:
            candidate = os.path.join(folder, "bash.exe") if folder else ""
            if candidate and not WSL_BASH.search(os.path.normpath(candidate)) and os.path.isfile(candidate):
                return [candidate, *command[1:]]
        raise Refused("`bash` would start WSL's bash.exe, which cannot see drive paths such as D:/; "
                      "install Git Bash or give the full path of a non-WSL bash")
    if WSL_BASH.search(os.path.normpath(program)):
        raise Refused(f"{program} is WSL's bash, which cannot see drive paths such as D:/; "
                      "use Git Bash (C:/Program Files/Git/bin/bash.exe)")
    return command


# ---------------------------------------------------------------- cores


def parse_cores(spec: str) -> list[int]:
    """'0-3,8,11-10' -> [0, 1, 2, 3, 8, 11, 10], in the order written, without repeats."""
    out: list[int] = []
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise ValueError(f"bad core list {spec!r}")
        a, b = int(m.group(1)), int(m.group(2) if m.group(2) is not None else m.group(1))
        step = 1 if b >= a else -1
        for core in range(a, b + step, step):
            if core not in out:
                out.append(core)
    if not out:
        raise ValueError(f"empty core list {spec!r}")
    return out


def format_cores(cores) -> str:
    """[0, 1, 2, 5, 7, 8] -> '0-2,5,7-8'."""
    cores = sorted(set(cores))
    runs: list[str] = []
    i = 0
    while i < len(cores):
        j = i
        while j + 1 < len(cores) and cores[j + 1] == cores[j] + 1:
            j += 1
        runs.append(str(cores[i]) if i == j else f"{cores[i]}-{cores[j]}")
        i = j + 1
    return ",".join(runs)


def cpu_binding() -> list[int] | None:
    """The granted CPUs in logical order (CPU_BINDING_ENV), or None when CPU numbers are the OS's own."""
    spec = os.environ.get(CPU_BINDING_ENV)
    if not spec:
        return None
    if os.name == "nt":
        raise ValueError(CPU_BINDING_ENV + " is for Linux containers")
    return parse_cores(spec)


def physical_cpus(cpus) -> list[int]:
    """The OS's numbers for logical ``cpus``."""
    binding = cpu_binding()
    if binding is None:
        return list(cpus)
    if any(type(cpu) is not int or not 0 <= cpu < len(binding) for cpu in cpus):
        raise ValueError(f"CPUs {list(cpus)} exceed the {len(binding)} bound logical CPUs")
    return [binding[cpu] for cpu in cpus]


def logical_cpus(cpus) -> list[int]:
    """The logical numbers of the OS's ``cpus``, sorted."""
    binding = cpu_binding()
    if binding is None:
        return sorted(cpus)
    index = {cpu: i for i, cpu in enumerate(binding)}
    if not set(cpus) <= set(index):
        raise ValueError(f"CPUs {sorted(set(cpus) - set(index))} are outside the CPU binding")
    return sorted(index[cpu] for cpu in cpus)


def cpu_total() -> int:
    binding = cpu_binding()
    return len(binding) if binding is not None else os.cpu_count() or 1


# ---------------------------------------------------------------- processes

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")
    HANDLE = wintypes.HANDLE
    PROCESS_QUERY_LIMITED_INFORMATION, SYNCHRONIZE, PROCESS_SUSPEND_RESUME = 0x1000, 0x00100000, 0x0800
    WAIT_OBJECT_0, WAIT_TIMEOUT = 0x0, 0x102
    ERROR_INVALID_PARAMETER, ERROR_SHARING_VIOLATION, ERROR_INSUFFICIENT_BUFFER = 87, 32, 122
    ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND = 2, 3
    GENERIC_READ, OPEN_EXISTING = 0x80000000, 3
    FILE_SHARE_ALL = 1 | 2 | 4
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    JOB_OBJECT_BASIC_PROCESS_ID_LIST, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 3, 9
    JOB_OBJECT_LIMIT_AFFINITY, JOB_OBJECT_LIMIT_PRIORITY_CLASS = 0x10, 0x20
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    PRIORITY_CLASS = {"normal": 0x20, "below_normal": 0x4000, "idle": 0x40}
    DETACHED_PROCESS, CREATE_NEW_PROCESS_GROUP, CREATE_BREAKAWAY_FROM_JOB = 0x8, 0x200, 0x01000000

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    def _fn(lib, name, restype, *argtypes):
        f = getattr(lib, name)
        f.restype, f.argtypes = restype, argtypes
        return f

    _FT = ctypes.POINTER(wintypes.FILETIME)
    _OpenProcess = _fn(_k32, "OpenProcess", HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _GetProcessTimes = _fn(_k32, "GetProcessTimes", wintypes.BOOL, HANDLE, _FT, _FT, _FT, _FT)
    _WaitForSingleObject = _fn(_k32, "WaitForSingleObject", wintypes.DWORD, HANDLE, wintypes.DWORD)
    _CloseHandle = _fn(_k32, "CloseHandle", wintypes.BOOL, HANDLE)
    _GetCurrentProcess = _fn(_k32, "GetCurrentProcess", HANDLE)
    _CreateFileW = _fn(_k32, "CreateFileW", HANDLE, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, HANDLE)
    _ReadFile = _fn(_k32, "ReadFile", wintypes.BOOL, HANDLE, wintypes.LPVOID, wintypes.DWORD,
                    ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID)
    _CreateJobObjectW = _fn(_k32, "CreateJobObjectW", HANDLE, wintypes.LPVOID, wintypes.LPCWSTR)
    _SetInformationJobObject = _fn(_k32, "SetInformationJobObject", wintypes.BOOL, HANDLE, ctypes.c_int,
                                   wintypes.LPVOID, wintypes.DWORD)
    _AssignProcessToJobObject = _fn(_k32, "AssignProcessToJobObject", wintypes.BOOL, HANDLE, HANDLE)
    _QueryInformationJobObject = _fn(_k32, "QueryInformationJobObject", wintypes.BOOL, HANDLE, ctypes.c_int,
                                     wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
    _GetLogicalProcessorInformationEx = _fn(_k32, "GetLogicalProcessorInformationEx", wintypes.BOOL,
                                            ctypes.c_int, wintypes.LPVOID, ctypes.POINTER(wintypes.DWORD))
    _NtSuspendProcess = _fn(_ntdll, "NtSuspendProcess", ctypes.c_long, HANDLE)
    _TerminateProcess = _fn(_k32, "TerminateProcess", wintypes.BOOL, HANDLE, wintypes.UINT)
    _IsProcessInJob = _fn(_k32, "IsProcessInJob", wintypes.BOOL, HANDLE, HANDLE, ctypes.POINTER(wintypes.BOOL))
    _NtResumeProcess = _fn(_ntdll, "NtResumeProcess", ctypes.c_long, HANDLE)
    _TerminateJobObject = _fn(_k32, "TerminateJobObject", wintypes.BOOL, HANDLE, wintypes.UINT)
    _GetProcessAffinityMask = _fn(_k32, "GetProcessAffinityMask", wintypes.BOOL, HANDLE,
                                  ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t))

    def _creation_of(handle) -> int | None:
        c, e, k, u = (wintypes.FILETIME() for _ in range(4))
        if not _GetProcessTimes(handle, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
            return None
        return (c.dwHighDateTime << 32) | c.dwLowDateTime

    def self_identity() -> tuple[int, int]:
        creation = _creation_of(_GetCurrentProcess())
        if creation is None:
            raise OSError(ctypes.get_last_error(), "GetProcessTimes failed on the current process")
        return os.getpid(), creation

    def creation_time(pid: int) -> int | None:
        handle = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            return _creation_of(handle)
        finally:
            _CloseHandle(handle)

    def process_state(pid, creation) -> str:
        """'alive', 'absent' or 'unknown' (as host_reservation_v1: absent needs positive evidence)."""
        if not isinstance(pid, int) or not isinstance(creation, int) or pid <= 0 or creation <= 0:
            return "unknown"
        handle = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
        if not handle:
            return "absent" if ctypes.get_last_error() == ERROR_INVALID_PARAMETER else "unknown"
        try:
            actual = _creation_of(handle)
            if actual is None:
                return "unknown"
            if actual != creation:
                return "absent"
            return {WAIT_OBJECT_0: "absent", WAIT_TIMEOUT: "alive"}.get(_WaitForSingleObject(handle, 0), "unknown")
        finally:
            _CloseHandle(handle)

    def read_shared(path: Path) -> bytes:
        """Read a file sharing read, write and delete, so a v1 state change (which renames the
        lock) is never blocked by this read. Raises FileNotFoundError when it is absent."""
        handle = _CreateFileW(str(path), GENERIC_READ, FILE_SHARE_ALL, None, OPEN_EXISTING, 0x80, None)
        if handle == INVALID_HANDLE_VALUE or not handle:
            err = ctypes.get_last_error()
            if err in (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND):
                raise FileNotFoundError(str(path))
            if err in (5, ERROR_SHARING_VIOLATION):  # access denied: a pending delete or rename
                raise PermissionError(f"{path} is being replaced (Win32 error {err})")
            raise OSError(f"CreateFileW failed for {path} (Win32 error {err})")
        try:
            chunks = []
            buf = ctypes.create_string_buffer(65536)
            got = wintypes.DWORD(0)
            while True:
                if not _ReadFile(handle, buf, len(buf), ctypes.byref(got), None):
                    raise OSError(ctypes.get_last_error(), f"ReadFile failed for {path}")
                if got.value == 0:
                    return b"".join(chunks)
                chunks.append(buf.raw[:got.value])
        finally:
            _CloseHandle(handle)

    def _job_members(job) -> list[int]:
        capacity = 8192
        size = 8 + 8 * capacity
        buf = ctypes.create_string_buffer(size)
        if not _QueryInformationJobObject(job, JOB_OBJECT_BASIC_PROCESS_ID_LIST, buf, size, None):
            raise OSError(ctypes.get_last_error(), "QueryInformationJobObject failed")
        _, listed = struct.unpack_from("<II", buf, 0)
        return list(struct.unpack_from(f"<{listed}Q", buf, 8))

    def _suspend_pid(pid: int, suspend: bool) -> bool:
        handle = _OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
        if not handle:
            return False
        try:
            return (_NtSuspendProcess if suspend else _NtResumeProcess)(handle) >= 0
        finally:
            _CloseHandle(handle)

    def current_affinity() -> list[int]:
        process, system = ctypes.c_size_t(0), ctypes.c_size_t(0)
        if not _GetProcessAffinityMask(_GetCurrentProcess(), ctypes.byref(process), ctypes.byref(system)):
            raise OSError(ctypes.get_last_error(), "GetProcessAffinityMask failed")
        return [i for i in range(64) if process.value >> i & 1]

else:
    def _linux_start(pid: int) -> int | None:
        """The start time of a live (not zombie) pid, None when it is absent; OSError when unreadable."""
        try:
            text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
        except FileNotFoundError:
            return None
        fields = text[text.rindex(")") + 2:].split()
        return None if fields[0] in ("Z", "X") else int(fields[19])

    def self_identity() -> tuple[int, int]:
        start = _linux_start(os.getpid())
        if start is None:
            raise OSError("cannot read this process's start time")
        return os.getpid(), start

    def creation_time(pid: int) -> int | None:
        try:
            return _linux_start(pid)
        except OSError:
            return None

    def process_state(pid, creation) -> str:
        if not isinstance(pid, int) or not isinstance(creation, int) or pid <= 0 or creation <= 0:
            return "unknown"
        try:
            start = _linux_start(pid)
        except (OSError, ValueError, IndexError):
            return "unknown"
        return "alive" if start == creation else "absent"

    def read_shared(path: Path) -> bytes:
        return Path(path).read_bytes()

    def current_affinity() -> list[int]:
        return logical_cpus(os.sched_getaffinity(0))


if os.name == "nt":
    class ProcessEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("pid", wintypes.DWORD), ("heap", ctypes.c_size_t), ("module", wintypes.DWORD),
                    ("threads", wintypes.DWORD), ("parent", wintypes.DWORD),
                    ("priority", wintypes.LONG), ("flags", wintypes.DWORD), ("name", wintypes.WCHAR * 260)]


def process_table() -> dict:
    if os.name != "nt":
        raise Refused("process ancestry requires Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), "cannot read process ancestry")
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        rows = {}
        present = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while present:
            rows[int(entry.pid)] = (int(entry.parent), entry.name.lower())
            present = kernel.Process32NextW(handle, ctypes.byref(entry))
        return rows
    finally:
        kernel.CloseHandle(handle)


# ---------------------------------------------------------------- records


def host() -> str:
    return os.environ.get(HOST_ENV) or re.sub(r"[^A-Za-z0-9-]", "-", platform.node()).upper()


def root_dir() -> Path:
    return Path(os.environ.get(ROOT_ENV) or CANONICAL_ROOT)


def lock_path() -> Path:
    return root_dir() / f"{host()}.lock"


def slots_dir() -> Path:
    return root_dir() / f"{host()}.slots"


def poll_seconds() -> float:
    return float(os.environ.get(POLL_ENV) or 2.0)


def grow_seconds() -> float:
    """How often a running shared claim tries to grow (HOST_SLOTS_GROW_SECONDS, for tests)."""
    return float(os.environ.get(GROW_ENV) or SHARE_GROW_SECONDS)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def write_json(path: Path, value: dict) -> None:
    """Write through a temp file and a rename. On Windows a reader that has the file open
    briefly blocks the rename, so it is retried for up to a second."""
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 19:
                os.remove(tmp)
                raise
            time.sleep(0.05)


def read_json(path: Path) -> dict | None:
    """A JSON object, or None when the file is absent or not one. A read that a concurrent
    rename blocks is retried for up to a second."""
    for attempt in range(20):
        try:
            value = json.loads(read_shared(path).decode("utf-8"))
        except FileNotFoundError:
            return None
        except PermissionError:
            time.sleep(0.05)
            continue
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None
    return None


def load_config() -> dict:
    """The host's slot config with defaults: cores (preference order), keep_free, priority, and ci_floor (only
    when above 0, so a host without one keeps the config digest older launchers compute)."""
    raw = read_json(slots_dir() / "config.json") or {}
    total = cpu_total()
    cores = parse_cores(str(raw["cores"])) if raw.get("cores") is not None else list(range(total - 1, -1, -1))
    if any(core >= total for core in cores):
        raise ValueError(f"config cores {format_cores(cores)} exceed this host's {total} logical CPUs")
    keep_free = int(raw.get("keep_free", 0))
    ci_floor = int(raw.get("ci_floor", 0))
    priority = raw.get("priority", "below_normal")
    if priority not in PRIORITIES or not 0 <= keep_free < len(cores) or not 0 <= ci_floor < len(cores) - keep_free:
        raise ValueError(f"bad slot config {raw}")
    config = {"cores": cores, "keep_free": keep_free, "priority": priority}
    if ci_floor:
        config["ci_floor"] = ci_floor
    return config


def lending_enabled() -> bool:
    """Whether shared claims may lend on this host: config "lending": true. It is kept out of load_config (and so
    out of the config digest) and is set by the deploy only after an inventory shows that every host_slots copy
    that can queue on this host honors the lending marker (c543e1b4 or later)."""
    return (read_json(slots_dir() / "config.json") or {}).get("lending") is True


def legacy_backfill_engine(tickets: list[dict], claims: list[dict]) -> bool:
    """Evidence that a backfill engine older than c543e1b4 is in use here: a queued request with a limit but no
    backfill_policy (the #407 engine's tickets), or a live backfill without deadline_mono (the #407 engine's
    claims). A runtime guard only: it cannot see an older copy that has not queued yet."""
    return (any(_max_seconds(t) is not None and "backfill_policy" not in t for t in tickets)
            or any(c.get("backfill") and "deadline_mono" not in c for c in claims))


def ci_floor_cores(config: dict) -> list[int]:
    """The CI floor: the last `ci_floor` cores in preference order. Only background (CI) claims may take them;
    background claims try them first and may also use any other free core. Separate from keep_free, which no
    claim may take."""
    count = config.get("ci_floor", 0)
    return config["cores"][-count:] if count else []


class Mutex:
    """A short-held directory mutex over the slot records (mkdir is atomic on both platforms).
    A holder that is absent by pid and creation time, or that never recorded itself within
    MUTEX_STALE_SECONDS, is broken."""

    def __init__(self):
        self.path = slots_dir() / ".mutex"

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + MUTEX_TIMEOUT_SECONDS
        pid, creation = self_identity()
        while True:
            try:
                self.path.mkdir()
            except FileExistsError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"slot mutex {self.path} stayed held for {MUTEX_TIMEOUT_SECONDS} s")
                if self._stale():
                    stale = self.path.with_name(f".mutex.stale-{uuid.uuid4().hex}")
                    try:
                        os.rename(self.path, stale)
                        shutil.rmtree(stale, ignore_errors=True)
                    except OSError:
                        time.sleep(0.05)
                    continue
                time.sleep(0.05)
                continue
            except PermissionError as error:
                # Windows can transiently deny directory recreation. Never
                # admit work until atomic mkdir succeeds within the deadline.
                if os.name != "nt" or getattr(error, "winerror", None) != 5:
                    raise
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)
                continue
            write_json(self.path / "owner.json", {"pid": pid, "creation_time": creation})
            return self

    def _stale(self) -> bool:
        owner = read_json(self.path / "owner.json")
        if owner is not None:
            return process_state(owner.get("pid"), owner.get("creation_time")) == "absent"
        try:
            return time.time() - self.path.stat().st_mtime > MUTEX_STALE_SECONDS
        except OSError:
            return False

    def __exit__(self, *_):
        try:
            (self.path / "owner.json").unlink()
        except OSError:
            pass
        try:
            self.path.rmdir()
        except OSError:
            shutil.rmtree(self.path, ignore_errors=True)


def _lock_cores(record: dict) -> list[int] | None:
    """Cores the reservation recorded when it was acquired (acquire --cores), or None."""
    cores = record.get("cores")
    if (isinstance(cores, list) and cores and len(set(cores)) == len(cores)
            and all(isinstance(c, int) and not isinstance(c, bool) and c >= 0 for c in cores)):
        return sorted(cores)
    return None


def timed_state() -> dict:
    """The v1 reservation as slots see it. held=False: free. cores=None: the whole host.
    A live declaration by `timed` names the cores; without one, cores recorded in the lock at
    acquire do. An unreadable lock, or no live declaration and no recorded cores, means the
    whole host."""
    try:
        body = read_shared(lock_path())
    except FileNotFoundError:
        return {"held": False, "cores": []}
    except OSError as exc:
        return {"held": True, "cores": None, "why": f"lock unreadable: {exc}"}
    try:
        record = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        record = None
    if not isinstance(record, dict) or record.get("schema") != LOCK_SCHEMA or not isinstance(record.get("token"), str):
        return {"held": True, "cores": None, "why": "lock record unreadable or incomplete"}
    digest = token_hash(record["token"])
    out = {"held": True, "cores": None, "token_sha256": digest,
           "lane": record.get("lane"), "work_id": record.get("work_id"), "acquired_at": record.get("acquired_at")}
    share = read_json(slots_dir() / f"share-{digest[:16]}.json")
    live = (share is not None and share.get("token_sha256") == digest
            and process_state(share.get("pid"), share.get("creation_time")) == "alive")
    if live:
        return {**out, "cores": sorted(share["cores"]), "why": "timed work declared its cores"}
    recorded = _lock_cores(record)
    if recorded is not None:
        return {**out, "cores": recorded, "why": "the reservation recorded its cores when it was acquired"}
    if share is None:
        return {**out, "why": "no core declaration: the whole host is reserved"}
    return {**out, "why": "core declaration is not live: the whole host is reserved"}


def _live(pattern: str) -> list[dict]:
    """Records matching pattern whose process is not absent; absent ones are removed (call under the mutex)."""
    rows = []
    for path in sorted(slots_dir().glob(pattern)):
        record = read_json(path)
        if record is None:
            continue
        if process_state(record.get("pid"), record.get("creation_time")) == "absent":
            try:
                path.unlink()
            except OSError:
                pass
            continue
        rows.append({**record, "path": str(path)})
    return rows


def live_claims() -> list[dict]:
    return _live("claim-*.json")


def live_tickets() -> list[dict]:
    return _live("queue-*.json")


def _check_drain_rollout(claims: list[dict]) -> None:
    for claim in claims:
        if (claim.get("background") or claim.get("shared")) and "draining" not in claim:
            raise Refused(f"legacy background or shared claim {claim.get('id', claim.get('path'))} "
                          "lacks the draining field. "
                          "Empty the host's claims and queue before switching all launchers.")


def _core_list(value) -> list[int] | None:
    """A non-empty list of distinct non-negative ints, or None."""
    if (isinstance(value, list) and value and len(set(value)) == len(value)
            and all(isinstance(c, int) and not isinstance(c, bool) and c >= 0 for c in value)):
        return value
    return None


def _guaranteed_cores(claim: dict) -> list[int]:
    if claim.get("shared") is True:
        guaranteed = _core_list(claim.get("guaranteed"))
        if guaranteed is not None and set(guaranteed) <= set(claim["cores"]):
            return guaranteed
    return claim["cores"]


def held(claim: dict) -> list[int]:
    """Draining claims stop lending their current cores to new admissions."""
    return claim["cores"] if claim.get("draining") else _guaranteed_cores(claim)


def lent(claim: dict) -> list[int]:
    """A shared claim's current cores beyond its guarantee (the cores any other claim may take)."""
    keep = set(held(claim))
    return [core for core in claim["cores"] if core not in keep]


def _preferred(cores: list[int], prefer: list[int] | None) -> list[int]:
    """cores with the preferred ones first, each part in its original order."""
    if not prefer:
        return cores
    return [c for c in cores if c in prefer] + [c for c in cores if c not in prefer]


def available(config: dict, timed: dict, claims: list[dict], *, background: bool = True,
              core_pool: list[int] | None = None, ci: bool | None = None) -> list[int]:
    """Cores a new claim may take now, in preference order. A shared claim's lent cores count as
    free: the new claim may take them, and the shared claim gives them back before the new claim's command starts.
    `background` says whether preemptible background cores count as used (a background request, or a backfill,
    which never takes them); `ci` (default: the same) says whether the request is CI work that may use the CI floor."""
    ci = background if ci is None else ci
    if timed["held"] and timed["cores"] is None:
        return []
    blocked = set(timed["cores"]) if timed["held"] else set()
    floor = ci_floor_cores(config)
    # The CI floor is for background (CI) claims only, which try it first; ordinary work never counts it as room.
    allowed = config["cores"] if ci else [core for core in config["cores"] if core not in floor]
    order = _preferred(allowed, floor) if ci else allowed
    used = {core for claim in claims if background or not claim.get("background", False) or claim.get("draining")
            for core in held(claim)}
    room = len(allowed) - config["keep_free"] - len(used & set(allowed))
    free = [core for core in order if core not in blocked and core not in used
            and (core_pool is None or core in core_pool)]
    return free[:max(0, room)]


def background_order(config: dict, room: list[int]) -> list[int]:
    """Take the CI floor first, then the other cores from the far end of the preference order.

    Ordinary admission takes the front of the same order, so this reduces avoidable overlap between ordinary and
    background work at admission; it does not remove it: once other claims end, a later ordinary request can still
    take a background claim's core while other cores are free.
    A host with a keep_free reserve retains the original order: an ordinary core pool can use the whole
    allocatable budget, so moving a background claim off that pool could keep it running outside the budget.
    Ordinary admission and its prediction both use the live claims' cores and their original placement order, so
    copies with the old and the new rule decide alike on an identical live snapshot; different placement histories
    can still lead to different later admissions.
    """
    if config["keep_free"]:
        return room
    floor = set(ci_floor_cores(config))
    return [core for core in room if core in floor] + [core for core in reversed(room) if core not in floor]


def unclaimed(config: dict, timed: dict, claims: list[dict], *, core_pool: list[int] | None = None) -> list[int]:
    """Cores no claim of any class runs on now (lent cores count as used), outside timed work and keep_free room,
    in preference order. A shared claim grows only onto these, so it never takes a core another claim holds or
    lends, and never a background claim's."""
    if timed["held"] and timed["cores"] is None:
        return []
    blocked = set(timed["cores"]) if timed["held"] else set()
    floor = set(ci_floor_cores(config))
    allowed = [core for core in config["cores"] if core not in floor]      # growth is ordinary work
    used = {core for claim in claims for core in claim["cores"]}
    room = len(allowed) - config["keep_free"] - len(used & set(allowed))
    free = [core for core in allowed if core not in blocked and core not in used
            and (core_pool is None or core in core_pool)]
    return free[:max(0, room)]


def conflicts(cores) -> bool:
    """True when held timed work leaves these cores no room (no declaration, or an overlapping one)."""
    timed = timed_state()
    return timed["held"] and (timed["cores"] is None or bool(set(timed["cores"]) & set(cores)))


def claim_conflicts(cores, background: bool) -> bool:
    """Called under the admission mutex. Background work also yields to ordinary claims."""
    return conflicts(cores) or (background and any(
        not claim.get("background", False) and set(cores).intersection(
            _guaranteed_cores(claim) if claim.get("draining") and claim.get("state") == "suspended"
            else claim["cores"])
        for claim in live_claims()))


def background_busy(cores, claim_id: str) -> bool:
    """True while a lender still runs on these cores: a background claim that has not suspended, or a shared claim
    whose published current cores (its job affinity, narrowed before it republishes) still include them."""
    return any(claim["id"] != claim_id and (claim.get("background", False) or claim.get("shared") is True)
               and set(claim["cores"]) & set(cores) and claim.get("state") != "suspended"
               for claim in live_claims())


def occupied(config: dict, claims: list[dict]) -> set[int]:
    """Configured cores some claim may run on: every claim's current cores, suspended claims included (a suspended
    claim resumes on its own, without asking anyone)."""
    allowed = set(config["cores"])
    return {core for claim in claims for core in claim["cores"] if core in allowed}


def over_budget(config: dict, claims: list[dict]) -> int:
    """How many occupied cores exceed the cores this host may hand out (configured minus keep_free)."""
    return len(occupied(config, claims)) - (len(config["cores"]) - config["keep_free"])


def lending(claim: dict) -> bool:
    """Whether a running claim occupies more than its guarantee, including while its helpers drain."""
    return claim.get("state") != "suspended" and len(_guaranteed_cores(claim)) < len(claim["cores"])


def budget_pending(config: dict, claims: list[dict], claim_id: str) -> bool:
    """True while occupied cores exceed the budget and another claim still lends: the lenders give back first."""
    return over_budget(config, claims) > 0 and any(c.get("id") != claim_id and lending(c) for c in claims)


def give_back(claim: dict, timed: dict, claims: list[dict], config: dict | None = None,
              queued: bool = False) -> list[int]:
    """The lent cores a shared claim must give back now: all of them while any request is queued (or the queue
    cannot be read), so it lends only while nobody waits; otherwise those timed work blocks, those another claim
    holds (another shared claim's guarantee, any other claim's cores, background included), and then, least
    preferred first, as many as occupied cores exceed the budget. `claim` carries this runner's actual cores."""
    mine = set(lent(claim))
    if not mine or queued:
        return sorted(mine)
    if timed["held"]:
        taken = set(mine) if timed["cores"] is None else mine & set(timed["cores"])
    else:
        taken = set()
    for other in claims:
        if other.get("id") != claim.get("id"):
            taken |= mine & set(held(other))
    if config is not None:
        others = [c for c in claims if c.get("id") != claim.get("id")]
        after = {**claim, "cores": [c for c in claim["cores"] if c not in taken]}
        excess = over_budget(config, others + [after])
        if excess > 0:
            order = [c for c in reversed(config["cores"]) if c in mine - taken]
            order += sorted(mine - taken - set(order))
            taken |= set(order[:excess])
    return sorted(taken)


def _max_seconds(record: dict) -> float | None:
    value = record.get("max_seconds")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= BACKFILL_MAX_SECONDS:
        return None
    return float(value)


def _pool(record: dict) -> list[int] | None:
    pool = record.get("core_pool")
    return pool if isinstance(pool, list) else None


def _head_start(config: dict, timed: dict, claims: list[dict], head: dict) -> tuple[set, set] | None:
    """The cores head's own admission would take with these claims, and the handoffs it would wait for (the
    background claims' and lenders' cores among them, and -1 when lenders must make budget room), or None when
    it cannot start."""
    room = available(config, timed, claims, background=bool(head.get("background", False)), core_pool=_pool(head))
    if len(room) < head["cores_wanted"]:
        return None
    chosen = set(room[:head["cores_wanted"]])
    # Handoffs the head would wait for: background cores (they suspend), lent cores (their lender narrows) and,
    # marked -1, lenders making room when the head's admission would exceed the budget.
    borrowed = {core for claim in claims if claim.get("background", False) for core in claim["cores"]}
    borrowed |= {core for claim in claims for core in lent(claim)}
    handoffs = chosen & borrowed
    if (any(lending(claim) for claim in claims)
            and over_budget(config, claims + [{"id": head.get("id"), "cores": sorted(chosen)}]) > 0):
        handoffs.add(-1)
    return chosen, handoffs


def _delay_terms(claims: list[dict], head: dict, ticket: dict, now: float, window: dict | None) -> dict | None:
    """The bounded-delay terms for a backfill that could delay head, or None. `now` and every bound are on the
    host's monotonic clock (shared by its processes, unmoved by clock changes). The head can only be held up
    while one of its delaying backfills runs, and `window` keeps the first one's start and the latest deadline
    for this head after those claims end, so the whole window, this backfill included, must stay within
    min(15 minutes, 10% of the head's declared max seconds). A head without a declared limit gets no delaying
    backfill, and none starts while an earlier one for the same head is overdue or unreadable. The bound holds
    while backfills keep their declared limits; nothing is preempted."""
    head_max, own = _max_seconds(head), _max_seconds(ticket)
    if head_max is None or own is None or not isinstance(head.get("id"), str):
        return None
    if ticket.get("on_overdue") == "flag":
        return None        # its own launcher will not enforce its limit, so it may only backfill without delaying
    limit = min(BACKFILL_DELAY_CAP_SECONDS, BACKFILL_DELAY_HEAD_SHARE * head_max)
    for claim in claims:
        if claim.get("backfill") and claim.get("delays_head") == head["id"]:
            deadline = claim.get("deadline_mono")
            if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or now > deadline:
                return None
    if window is not None:
        first, last = window.get("start_mono"), window.get("end_mono")
        if (window.get("head_id") != head["id"] or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                                      for v in (first, last)) or not first <= last or first > now):
            return None        # unreadable, or from before a restart: no delaying backfill for this head
    else:
        first = last = now
    last = max(last, now + own)
    if last - first > limit:
        return None
    return {"delays_head": head["id"], "delay_bound_seconds": round(last - first, 3), "delay_limit_seconds": limit,
            "deadline_mono": now + own, "delay_window": {"head_id": head["id"], "start_mono": first, "end_mono": last}}


def _backfill_cores(config: dict, timed: dict, claims: list[dict], head: dict, ticket: dict,
                    now: float | None = None, window: dict | None = None) -> tuple[list[int], dict | None] | None:
    """Cores ticket may take ahead of head, with the bounded-delay terms when it could delay the head
    (None when it cannot), or None when it may not start.

    A head that can start now is never jumped. Otherwise the live claims, backfills included, may end in any
    order, so every subset of them is tried: whenever ending a subset would let the head start with no
    backfills, it must still start with the remaining backfills and this one running, without waiting on more
    background cores. If some subset would leave the head waiting on backfills, the request may start only
    under `_delay_terms`, and only if its own launcher applies that rule (`backfill_policy` 2; an older
    launcher refuses such a start, so judging its ticket by it would strand the requests behind it). It never
    starts if it would leave the head waiting on more background cores. A backfill never takes a background
    claim's cores, so it never suspends one.
    Only ordinary requests backfill, behind an ordinary head: later ordinary requests overtake a
    background head, so its proof would not hold. Ending a backfill only adds non-background cores to
    the head's choices, so including backfills in the enumeration never refuses more; it is kept so the
    proof does not depend on that argument.
    Scope: the guarantee covers claims ending. A timed reservation outranks the queue and may block any
    cores at any time, so no backfill starts while one is held, and none can be proof against one
    acquired later."""
    if (_max_seconds(ticket) is None or ticket.get("background", False) or head.get("background", False)
            or timed["held"] or len(claims) > BACKFILL_MAX_RUNNING or any(lent(claim) for claim in claims)):
        return None        # lenders give every lent core back within a poll of a ticket appearing (and keep a
        # marker that stops older engines meanwhile)
    wanted, head_wanted = ticket.get("cores_wanted"), head.get("cores_wanted")
    for value in (wanted, head_wanted):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            return None
    if _head_start(config, timed, claims, head) is not None:
        return None        # the head can start now: it is never jumped
    room = available(config, timed, claims, core_pool=_pool(ticket), ci=False)
    if len(room) < wanted:
        return None
    cores = sorted(room[:wanted])
    candidate = {"cores": cores, "background": False, "backfill": True}
    delays = False
    for mask in range(1 << len(claims)):
        rest = [claim for bit, claim in enumerate(claims) if not mask >> bit & 1]
        without = _head_start(config, timed, [claim for claim in rest if not claim.get("backfill")], head)
        if without is None:
            continue
        with_backfill = _head_start(config, timed, rest + [candidate], head)
        if with_backfill is None:
            delays = True
        elif not with_backfill[1] <= without[1]:
            return None
    if not delays:
        return cores, None
    if ticket.get("backfill_policy") != BACKFILL_POLICY:
        return None
    terms = _delay_terms(claims, head, ticket, time.monotonic() if now is None else now, window)
    return None if terms is None else (cores, terms)


def _ticket_path(queue_class: str, claim_id: str) -> Path:
    """A queue ticket name that sorts after every ticket already queued. Called under the admission
    mutex, so a launcher paused before publishing can never queue ahead of a head that a backfill
    was proved against."""
    stamp = time.time_ns()
    for existing in slots_dir().glob("queue-*.json"):
        match = re.match(r"queue-(?:z-)?(\d{20})-", existing.name)
        if match:
            stamp = max(stamp, int(match.group(1)) + 1)
    return slots_dir() / f"queue-{queue_class}{stamp:020d}-{claim_id}.json"


def config_digest(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode("utf-8")).hexdigest()


def _marker_path(claim_id: str) -> Path:
    return slots_dir() / f"{LENDING_MARKER}{claim_id}.json"


def _set_lending_marker(claim_id: str, on: bool) -> None:
    """Create (before a shared claim publishes any lent core) or remove (after it published none) its marker.
    Called under the admission mutex."""
    path = _marker_path(claim_id)
    if not on:
        path.unlink(missing_ok=True)
        return
    if path.exists():
        return
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text('"lending: this file is deliberately not a JSON object, so no backfill is proved"\n',
                   encoding="utf-8")
    os.replace(tmp, path)


def _delay_window_path(head_id: str) -> Path:
    return slots_dir() / f"delay-{head_id}.json"


def _snapshot() -> dict | None:
    """One read of every queue, claim and delay file, for a whole admission decision (called under the admission
    mutex), or None when the folder cannot be listed (`os.scandir` raises where `Path.glob` would return
    nothing). Each file is read once: live tickets and claims come from those reads exactly as `_live` builds
    them (an exited launcher's record is removed), and `unreadable` names every file that exists but could
    not be read, so a failed read is never mistaken for an absent record."""
    folder = slots_dir()
    try:
        with os.scandir(folder) as entries:
            names = sorted(entry.name for entry in entries
                           if entry.name.endswith(".json") and entry.name.startswith(("queue-", "claim-", "delay-")))
    except OSError:
        return None
    records, unreadable, tickets, claims = {}, set(), [], []
    markers = [name for name in names if name.startswith(LENDING_MARKER)]
    names = [name for name in names if not name.startswith(LENDING_MARKER)]
    for name in markers:          # a lender's marker whose claim file is gone (its runner was killed)
        if f"claim-{name.removeprefix(LENDING_MARKER)}" not in names:
            (folder / name).unlink(missing_ok=True)
    for name in names:
        record = read_json(folder / name)
        if record is None:
            try:
                os.stat(folder / name)
            except FileNotFoundError:
                continue           # removed since the listing
            except OSError:
                pass
            unreadable.add(name)
            continue
        if name.startswith("delay-"):
            records[name] = record
            continue
        if process_state(record.get("pid"), record.get("creation_time")) == "absent":
            try:
                (folder / name).unlink()
            except OSError:
                pass
            continue
        records[name] = record
        (tickets if name.startswith("queue-") else claims).append({**record, "path": str(folder / name)})
    return {"names": set(records) | unreadable, "unreadable": unreadable, "records": records,
            "tickets": tickets, "claims": claims}


def _snapshot_window(snap: dict, head_id: str) -> dict | None:
    """The head's persisted window from the snapshot: None only when the listing has no such file, an unreadable
    marker (refusing every delaying backfill for that head) when it exists but could not be read."""
    name = f"delay-{head_id}.json"
    if name in snap["unreadable"]:
        return {"unreadable": True}
    window = snap["records"].get(name)
    return window if window is None or isinstance(window, dict) else {"unreadable": True}


def _prune_delay_windows(snap: dict) -> None:
    """A delay window goes once no queue file for its head exists at all, judged from a snapshot whose listing
    succeeded (called under the admission mutex)."""
    queued = {name.rsplit("-", 1)[-1].removesuffix(".json") for name in snap["names"] if name.startswith("queue-")}
    for name in snap["names"]:
        if (name.startswith("delay-") and not name.startswith(LENDING_MARKER)
                and name.removeprefix("delay-").removesuffix(".json") not in queued):
            (slots_dir() / name).unlink(missing_ok=True)


def backfill_admission(config: dict, timed: dict, claims: list[dict], tickets: list[dict], claim_id: str,
                       now: float | None = None, window: dict | None = None) -> tuple[list[int], dict | None] | None:
    """Cores for claim_id to start before the queue head with its bounded-delay terms (None when it cannot
    delay the head), or None. Called under the admission mutex with tickets in admission order and the
    current config. Only the first eligible ticket behind the head may start. The head admits with the
    config it read before queueing, so nothing backfills unless its ticket records that same config (a
    ticket from an older launcher records none). `window` is the head's persisted delay window, if any."""
    if not tickets or tickets[0].get("config_sha256") != config_digest(config):
        return None
    for ticket in tickets[1:]:
        admitted = _backfill_cores(config, timed, claims, tickets[0], ticket, now, window)
        if admitted is not None:
            return admitted if ticket["id"] == claim_id else None
    return None


def backfill_admits(config: dict, timed: dict, claims: list[dict], tickets: list[dict], claim_id: str,
                    now: float | None = None, window: dict | None = None) -> list[int] | None:
    """The cores of `backfill_admission`, or None."""
    admitted = backfill_admission(config, timed, claims, tickets, claim_id, now, window)
    return None if admitted is None else admitted[0]


# ---------------------------------------------------------------- containment


class Tree:
    """The pinned process tree of one claim or declaration."""

    def __init__(self, cores, priority: str | None, *, contain_self: bool = True):
        self.cores = sorted(cores)
        # The last mask the OS accepted for the job (None when unknown). It can differ from `cores` after a failed
        # change; a shared claim's runner re-applies `cores` before it resumes.
        self.applied = self.cores
        self.priority = priority
        self.job = None
        self.child = None
        self.suspended: set[int] = set()
        if os.name == "nt":
            if max(self.cores) >= 64:
                raise ValueError("cores above 63 (a second processor group) are not supported")
            job = _CreateJobObjectW(None, None)
            if not job:
                raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            limits = info.BasicLimitInformation
            limits.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_AFFINITY
            limits.Affinity = sum(1 << core for core in self.cores)
            if priority is not None:
                limits.LimitFlags |= JOB_OBJECT_LIMIT_PRIORITY_CLASS
                limits.PriorityClass = PRIORITY_CLASS[priority]
            if not _SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
                                            ctypes.sizeof(info)):
                err = ctypes.get_last_error()
                _CloseHandle(job)
                raise OSError(err, "SetInformationJobObject failed")
            if contain_self and not _AssignProcessToJobObject(job, _GetCurrentProcess()):
                err = ctypes.get_last_error()
                _CloseHandle(job)
                raise OSError(err, "AssignProcessToJobObject failed")
            self.job = job
        else:
            if not contain_self:
                raise Refused("adopting an existing worker requires Windows")
            os.sched_setaffinity(0, physical_cpus(self.cores))
            if priority is not None:
                floor = {"normal": 0, "below_normal": 10, "idle": 19}[priority]
                current = os.getpriority(os.PRIO_PROCESS, 0)
                if current < floor:
                    os.setpriority(os.PRIO_PROCESS, 0, floor)

    def start(self, command: list[str], cwd: str | None, env: dict) -> subprocess.Popen:
        self.child = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=os.name != "nt")
        return self.child

    def set_cores(self, cores) -> bool:
        """Change the affinity of the whole tree (this runner, its command and every descendant) to cores.
        Returns False when the change could not be applied to every member; the caller then suspends the tree.
        On Windows the job's affinity limit applies to every process in the job at once; on Linux each thread of
        each process in the claim's session is set."""
        cores = sorted(cores)
        if os.name == "nt":
            if max(cores) >= 64:
                return False
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            limits = info.BasicLimitInformation
            limits.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_AFFINITY
            limits.Affinity = sum(1 << core for core in cores)
            if self.priority is not None:
                limits.LimitFlags |= JOB_OBJECT_LIMIT_PRIORITY_CLASS
                limits.PriorityClass = PRIORITY_CLASS[self.priority]
            if not _SetInformationJobObject(self.job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
                                            ctypes.sizeof(info)):
                return False
            self.applied = cores      # the job limit took effect, even if a member's read-back disagrees below
            # Read back every member's affinity: the limit must have reached all of them (a nested job could
            # refuse it).
            for pid in [os.getpid(), *self.members()]:
                handle = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if not handle:
                    continue          # it exited
                try:
                    actual, system = ctypes.c_size_t(0), ctypes.c_size_t(0)
                    if not _GetProcessAffinityMask(handle, ctypes.byref(actual), ctypes.byref(system)):
                        return False
                    if actual.value != limits.Affinity:
                        return False
                finally:
                    _CloseHandle(handle)
            self.cores = cores
            return True
        physical = physical_cpus(cores)
        ok = True
        self.applied = None           # some threads may already have the new mask
        try:
            os.sched_setaffinity(0, physical)
        except OSError:
            ok = False
        if self.child is not None:
            for entry in Path("/proc").iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    text = (entry / "stat").read_text(encoding="ascii", errors="replace")
                    if int(text[text.rindex(")") + 2:].split()[3]) != self.child.pid:
                        continue
                    tasks = [int(t.name) for t in (entry / "task").iterdir()]
                except (OSError, ValueError, IndexError):
                    continue
                for tid in tasks:
                    try:
                        os.sched_setaffinity(tid, physical)
                        if sorted(os.sched_getaffinity(tid)) != sorted(physical):
                            ok = False
                    except ProcessLookupError:
                        pass
                    except OSError:
                        ok = False
        if ok:
            self.cores = self.applied = cores
        return ok

    def adopt(self, pid: int, creation: int, *, suspend: bool = False) -> None:
        """Bind a verified existing process using the same handle for identity and assignment."""
        if os.name != "nt":
            raise Refused("adopting an existing worker requires Windows")
        handle = _OpenProcess(0x0100 | 0x0001 | PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE
                              | PROCESS_SUSPEND_RESUME, False, pid)
        if not handle:
            raise Refused(f"cannot open worker {pid} for containment")
        bound = frozen = False
        try:
            if _creation_of(handle) != creation or _WaitForSingleObject(handle, 0) != WAIT_TIMEOUT:
                raise Refused(f"worker {pid} no longer has the declared identity")
            if suspend:
                if _NtSuspendProcess(handle) < 0:
                    raise Refused(f"cannot suspend worker {pid} for adoption")
                frozen = True
            if not _AssignProcessToJobObject(self.job, handle):
                raise OSError(ctypes.get_last_error(), f"cannot contain worker {pid}")
            bound = True
            if frozen:
                self.suspended.add(pid)
            actual, system = ctypes.c_size_t(0), ctypes.c_size_t(0)
            if not _GetProcessAffinityMask(handle, ctypes.byref(actual), ctypes.byref(system)):
                raise Refused(f"cannot verify worker {pid} affinity after containment")
            if actual.value != sum(1 << core for core in self.cores):
                raise Refused(f"worker {pid} inherited an incompatible outer job affinity")
        finally:
            if frozen and not bound:
                _NtResumeProcess(handle)
            _CloseHandle(handle)

    def adopt_worker_tree(self, pid: int, creation: int) -> None:
        """Freeze Worker first, then freeze/contain existing descendants until none escape."""
        # Keep handles across snapshots: an exited parent's PID cannot be reused,
        # and its surviving children retain a verified path to the original Worker.
        root_handle = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
        if not root_handle:
            raise Refused("cannot retain the worker identity during adoption")
        known = {pid: (root_handle, creation)}
        try:
            if _creation_of(root_handle) != creation:
                raise Refused("worker identity changed before adoption")
            self.adopt(pid, creation, suspend=True)
            while True:
                if _WaitForSingleObject(root_handle, 0) != WAIT_TIMEOUT:
                    raise Refused("worker exited during descendant adoption")
                snapshot_start = time.time_ns() // 100 + 116444736000000000
                rows = process_table()
                found = set(known)
                while True:
                    children = {child for child, (parent, _) in rows.items()
                                if parent in found and child != os.getpid()}
                    if children <= found:
                        break
                    found |= children
                candidates = found - set(known)
                for child in candidates:
                    handle = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, child)
                    if not handle:
                        raise Refused("cannot bind an existing worker descendant")
                    stamp = _creation_of(handle)
                    if stamp is None or stamp > snapshot_start:
                        _CloseHandle(handle)
                        raise Refused("a descendant identity changed during the process snapshot")
                    known[child] = (handle, stamp)
                for child in candidates:
                    parent = rows[child][0]
                    # A reused parent PID points to a process born after its child.
                    if parent not in known or known[parent][1] > known[child][1]:
                        raise Refused("descendant ancestry contains a reused or unverified parent")
                for child in candidates:
                    handle, stamp = known[child]
                    if _WaitForSingleObject(root_handle, 0) != WAIT_TIMEOUT:
                        raise Refused("worker exited during descendant adoption")
                    if _WaitForSingleObject(handle, 0) == WAIT_OBJECT_0:
                        continue
                    try:
                        self.adopt(child, stamp, suspend=True)
                    except Refused:
                        if _WaitForSingleObject(handle, 0) != WAIT_OBJECT_0:
                            raise
                if not candidates:
                    if process_state(pid, creation) != "alive" or not self.set_suspended(True):
                        raise Refused("worker tree could not be fully suspended during adoption")
                    return
        finally:
            for handle, _ in known.values():
                if handle:
                    _CloseHandle(handle)

    def members(self) -> list[int]:
        """Live processes of the tree other than this runner."""
        if os.name == "nt":
            return [pid for pid in _job_members(self.job) if pid != os.getpid()]
        if self.child is None:
            return []
        try:
            os.killpg(self.child.pid, 0)
        except ProcessLookupError:
            return []
        except PermissionError:
            pass
        return [self.child.pid]

    def set_suspended(self, suspend: bool) -> bool:
        if os.name == "nt":
            if suspend:
                for _ in range(2):  # a second pass catches a process created during the first
                    for pid in self.members():
                        if pid not in self.suspended and _suspend_pid(pid, True):
                            self.suspended.add(pid)
                return set(self.members()) <= self.suspended
            else:
                for pid in sorted(self.suspended):
                    if _suspend_pid(pid, False):
                        self.suspended.discard(pid)
                self.suspended.intersection_update(self.members())
                return not self.suspended
        elif self.child is not None:
            try:
                os.killpg(self.child.pid, signal.SIGSTOP if suspend else signal.SIGCONT)
            except ProcessLookupError:
                pass
            self.suspended = {self.child.pid} if suspend else set()
        return True

    def kill_members(self, timeout: float = 30.0) -> bool:
        """End every process of this claim's tree except this runner, so the runner survives to release the claim.
        Windows: each member listed by the job is opened by PID and ended only if that handle is still a process
        in this job (a reused PID is never touched); repeated until the job holds only the runner. Linux: the
        command's own process group (the runner is outside it). True when the tree is empty."""
        if os.name != "nt":
            if self.child is not None:
                for sig in (signal.SIGKILL, signal.SIGCONT):
                    try:
                        os.killpg(self.child.pid, sig)
                    except ProcessLookupError:
                        pass
            return True
        deadline = time.monotonic() + timeout
        while self.members():
            if time.monotonic() > deadline:
                return False
            for pid in self.members():
                handle = _OpenProcess(0x0001 | PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SUSPEND_RESUME, False, pid)
                if not handle:
                    continue
                try:
                    inside = wintypes.BOOL(False)
                    if _IsProcessInJob(handle, self.job, ctypes.byref(inside)) and inside.value:
                        _NtResumeProcess(handle)      # a suspended process still ends, but resume it first
                        _TerminateProcess(handle, 1)
                finally:
                    _CloseHandle(handle)
            time.sleep(0.05)
        self.suspended.clear()
        return True

    def kill(self) -> None:
        if os.name == "nt":
            if self.job is not None:
                _TerminateJobObject(self.job, 1)
        elif self.child is not None:
            for sig in (signal.SIGKILL, signal.SIGCONT):
                try:
                    os.killpg(self.child.pid, sig)
                except ProcessLookupError:
                    pass


# ---------------------------------------------------------------- operations


def _claim_record(base: dict, cores: list[int], priority: str, acquired_at: str, enqueued_at: str,
                  queued_seconds: float, config: dict, timed: dict, claims: list[dict],
                  core_pool: list[int] | None, queue_empty: bool) -> dict:
    """The record of a claim admitted onto cores (called under the admission mutex with the decision's claims).
    It records how long the request queued and which cores it took from shared claims (`took_lent`). A shared
    claim guarantees cores and, only when no other request is queued, starts on up to its maximum by adding
    cores that no claim of any class runs on."""
    record = {**base, "cores": cores, "priority": priority, "state": "running", "acquired_at": acquired_at,
              "enqueued_at": enqueued_at, "queued_seconds": round(queued_seconds, 3)}
    if base.get("background") or base.get("shared"):
        record["draining"] = False
    took = sorted(set(cores) & {core for claim in claims for core in lent(claim)})
    if took:
        record["took_lent"] = took
    if base.get("shared"):
        extra = [] if not queue_empty else unclaimed(
            config, timed, claims + [{"id": base["id"], "cores": cores}],
            core_pool=core_pool)[:base["max_cores"] - len(cores)]
        record.update(guaranteed=cores, cores=sorted(cores + extra))
    return record


def old_rules_room(config: dict, timed: dict, claims: list[dict], base: dict, wanted: int,
                   core_pool: list[int] | None) -> bool:
    """Whether the rules before shared claims would have found room for this request on the same snapshot: every
    claim holds all its current cores, and a shared request asks for its maximum as one exclusive claim. Room
    only: the queue order and backfill rules are not replayed."""
    plain = [{**claim, "shared": False} for claim in claims]
    need = base["max_cores"] if base.get("shared") else wanted
    before = {k: v for k, v in config.items() if k != "ci_floor"}
    return len(available(before, timed, plain, background=bool(base.get("background")), core_pool=core_pool)) >= need


def _event(kind: str, record: dict, **extra) -> None:
    """Append one lifecycle event (called under the admission mutex). Measurement only: a failure is ignored."""
    keep = ("id", "lane", "work_id", "background", "shared", "cores", "guaranteed", "max_cores", "core_pool",
            "core_pool_reason", "queued_seconds", "took_lent", "backfill", "delays_head")
    try:
        row = {"event": kind, "t": now_utc(), "mono": round(time.monotonic(), 3),
               **{k: record[k] for k in keep if k in record}, **extra}
        _append_jsonl(util_dir() / f"events-{row['t'][:10].replace('-', '')}.jsonl", [row])
    except Exception:  # noqa: BLE001 - measurement never stops a claim
        pass


def run(lane: str, work_id: str, cores_wanted: int, command: list[str], *, wait: bool = False,
        wait_timeout: float | None = None, priority: str | None = None, claim_id: str | None = None,
        cwd: str | None = None, on_claim=None, background: bool = False, adopted: dict | None = None,
        core_pool: list[int] | None = None, max_seconds: float | None = None, pool_reason: str | None = None,
        shared: bool = False, min_cores: int | None = None,
        on_overdue: str | None = None) -> int:
    """Claim cores (queueing with wait), run command pinned to them, free them when its tree ends.
    With max_seconds, a waiting request may also start before the queue head (backfill_admits).
    A core pool restricts the request and needs a recorded reason (POOL_REASONS).
    With shared, cores_wanted is the most the claim runs on and min_cores (default 1) the cores it guarantees and
    queues for; it lends the rest, giving them back to any later claim and growing onto unclaimed cores."""
    if not (lane and work_id and command):
        raise ValueError("lane, work_id and a command are required")
    if max_seconds is not None and _max_seconds({"max_seconds": max_seconds}) is None:
        raise ValueError(f"max seconds must be a number above 0 and at most {BACKFILL_MAX_SECONDS:.0f}")
    _check_placement(core_pool, pool_reason, shared, min_cores, background, adopted is not None,
                     max_seconds, on_overdue)
    if max_seconds is not None and on_overdue is None:
        on_overdue = "flag"
    if core_pool is not None and pool_reason is None:
        pool_reason = POOL_REASON_UNSPECIFIED       # the transition window (_check_placement refused after it)
    if adopted is not None and not background:
        raise ValueError("an adopted worker must be a background claim")
    min_cores = (1 if min_cores is None else min_cores) if shared else None
    if shared and not 1 <= min_cores <= cores_wanted:
        raise ValueError("--min-cores must be from 1 to --cores")
    wanted = min_cores if shared else cores_wanted
    config = load_config()
    if core_pool is not None:
        if not core_pool or not set(core_pool) <= set(config["cores"]) or len(set(core_pool)) < wanted:
            raise ValueError("core pool must contain enough configured usable CPUs")
    if shared and not lending_enabled():
        raise ValueError("shared claims are off on this host: set \"lending\": true in its slots config.json only "
                         "after every host_slots copy that can queue here is c543e1b4 or later")
    priority = priority or config["priority"]
    if priority not in PRIORITIES:
        raise ValueError(f"priority must be one of {PRIORITIES}")
    # Ordinary work never gets the CI floor, so a request larger than the rest could never start.
    most = len(config["cores"]) - config["keep_free"] - (0 if background else config.get("ci_floor", 0))
    if not 1 <= cores_wanted <= most:
        raise ValueError(f"{cores_wanted} cores: this host hands out 1 to {most}"
                         + ("" if background else " to work other than CI"))
    claim_id = claim_id or uuid.uuid4().hex
    if not re.fullmatch(r"[0-9a-f]{32}", claim_id):
        raise ValueError("claim id must be 32 lowercase hex digits")
    pid, creation = self_identity()
    base = {"schema": SCHEMA, "id": claim_id, "lane": lane, "work_id": work_id, "pid": pid,
            "creation_time": creation, "background": background}
    if core_pool is not None:
        base["core_pool"] = sorted(set(core_pool))
        base["core_pool_reason"] = pool_reason
    if shared:
        base["shared"] = True
        base["max_cores"] = cores_wanted
    # Legacy launchers use filename FIFO without reading the background flag.
    # Sort background filenames after ordinary ones so both generations agree
    # on who may enter. Otherwise each can wait for the other's first ticket.
    queue_class = "z-" if background else ""
    claim = slots_dir() / f"claim-{claim_id}.json"
    deadline = None if wait_timeout is None else time.monotonic() + wait_timeout
    enqueued_at = now_utc()
    request = {**base, "cores_wanted": wanted, "enqueued_at": enqueued_at, "config_sha256": config_digest(config)}
    if max_seconds is not None:
        request["max_seconds"] = max_seconds
        # A flag request's limit is not enforced, so it never takes a bounded delay; backfill_policy 0 makes every
        # engine (the #427 one included) judge it by the zero-delay rule only, so all agree on the first eligible.
        request["backfill_policy"] = BACKFILL_POLICY if on_overdue != "flag" else 0
        request["on_overdue"] = on_overdue
    with Mutex():
        ticket = _ticket_path(queue_class, claim_id)
        write_json(ticket, request)
    queued_mono = time.monotonic()
    backfill = None
    try:
        while True:
            with Mutex():
                # One snapshot for the whole decision. A file that exists but cannot be read leaves the true
                # queue order or the claims unknown: no request starts while a queue file ahead of it is
                # unreadable, and nothing backfills while any queue, claim or delay file is.
                snap = _snapshot()
                if snap is not None:
                    _check_drain_rollout(snap["claims"])
                tickets = [] if snap is None else snap["tickets"]
                tickets.sort(key=lambda ticket: bool(ticket.get("background", False)))
                if snap is None or any(name.startswith("queue-") and name < ticket.name
                                       for name in snap["unreadable"]):
                    pass
                elif tickets and tickets[0]["id"] == claim_id:
                    timed = timed_state()
                    room = available(config, timed, snap["claims"], background=background,
                                     core_pool=core_pool)
                    if len(room) >= wanted:
                        cores = sorted((background_order(config, room) if background else room)[:wanted])
                        alone = not any(n.startswith("queue-") and n != ticket.name for n in snap["names"])
                        record = _claim_record(base, cores, priority, now_utc(), enqueued_at,
                                               time.monotonic() - queued_mono, config, timed, snap["claims"],
                                               core_pool, alone)
                        if lent(record):
                            _set_lending_marker(claim_id, True)
                        if max_seconds is not None:
                            mono = time.monotonic()
                            record.update(max_seconds=max_seconds, on_overdue=on_overdue,
                                          deadline_mono=mono + max_seconds, deadline_at=(datetime.now(
                                              timezone.utc) + timedelta(seconds=max_seconds)).isoformat(
                                              timespec="milliseconds"))
                        write_json(claim, record)
                        ticket.unlink()
                        _event("admit", record, old_rules_room=old_rules_room(
                            config, timed, snap["claims"], base, wanted, core_pool))
                        break
                elif max_seconds is not None and len(tickets) > 1 and not snap["unreadable"]:
                    try:
                        current = load_config()
                    except ValueError:  # an unreadable edit: no backfill until it is fixed
                        current = None
                    _prune_delay_windows(snap)
                    started, mono = datetime.now(timezone.utc), time.monotonic()
                    window = _snapshot_window(snap, tickets[0]["id"])
                    timed = timed_state()
                    admitted = None if current is None else backfill_admission(
                        current, timed, snap["claims"], tickets, claim_id, mono, window)
                    if admitted is not None:
                        cores, terms = admitted
                        if terms is not None:
                            terms = dict(terms)
                            write_json(_delay_window_path(tickets[0]["id"]), terms.pop("delay_window"))
                        backfill = {"backfill": True, "max_seconds": max_seconds, "on_overdue": on_overdue,
                                    "head_id": tickets[0]["id"],
                                    "deadline_at": (started + timedelta(seconds=max_seconds)).isoformat(
                                        timespec="milliseconds"), "deadline_mono": mono + max_seconds,
                                    **(terms or {})}
                        record = _claim_record(base, cores, priority, started.isoformat(timespec="milliseconds"),
                                               enqueued_at, mono - queued_mono, current, timed, snap["claims"],
                                               core_pool, False)
                        record = {**record, **backfill}
                        write_json(claim, record)
                        ticket.unlink()
                        _event("admit", record, old_rules_room=old_rules_room(
                            current, timed, snap["claims"], base, wanted, core_pool))
                        break
            if not wait:
                raise NoRoom(f"{host()} has no {wanted} free cores for {lane}/{work_id} now")
            if adopted and process_state(adopted["pid"], adopted["creation"]) == "absent":
                raise Refused("worker exited while waiting for CPU slots")
            if deadline is not None and time.monotonic() > deadline:
                raise NoRoom(f"{host()} had no {wanted} free cores within {wait_timeout} s")
            time.sleep(poll_seconds())
    except BaseException:
        with Mutex():
            try:
                ticket.unlink()
            except OSError:
                pass
        raise
    share = None
    if shared:
        share = {"guaranteed": record["guaranteed"], "max_cores": cores_wanted, "pool": core_pool}
        cores = record["cores"]
    code = None
    try:
        if on_claim is not None:
            on_claim({"id": claim_id, "cores": cores, **({"backfill": True} if backfill else {}),
                      **({"guaranteed": share["guaranteed"]} if share else {})})
        if adopted is not None:
            code = _run_adopted(claim, cores, priority, claim_id, background, adopted)
        else:
            limit = None if max_seconds is None else {"deadline_mono": record["deadline_mono"], "action": on_overdue}
            code = _run_claimed(claim, cores, priority, command, cwd, claim_id, background=background, share=share,
                                overdue=limit)
        return code
    finally:
        with Mutex():
            try:
                claim.unlink()
            except OSError:
                pass
            if shared:
                _set_lending_marker(claim_id, False)
            _event("end", {"id": claim_id, "lane": lane, "work_id": work_id}, exit_code=code)


def _check_placement(core_pool, pool_reason, shared: bool, min_cores, background: bool, adopting: bool,
                     max_seconds=None, on_overdue=None, warn: bool = False) -> None:
    """Placement options that are refused before any ticket is written."""
    if on_overdue is not None and (max_seconds is None or on_overdue not in OVERDUE_ACTIONS):
        raise ValueError("--on-overdue needs --max-seconds and is one of " + ", ".join(OVERDUE_ACTIONS))
    if core_pool is not None and pool_reason is None and not pool_reason_required():
        if warn:              # once, from the CLI
            print(json.dumps({"warning": "--core-pool without --pool-reason is accepted as \"unspecified\" until "
                              + POOL_REASON_REQUIRED_FROM + " and refused after; add --pool-reason ("
                              + ", ".join(POOL_REASONS) + ") or drop the pool"}), file=sys.stderr)
    elif core_pool is not None and pool_reason not in POOL_REASONS:
        raise ValueError("--core-pool needs --pool-reason, one of " + ", ".join(POOL_REASONS)
                         + "; without one, drop the pool and the scheduler places the job, so it never waits "
                           "while other cores are free")
    if core_pool is None and pool_reason is not None:
        raise ValueError("--pool-reason applies only with --core-pool")
    if shared and (background or adopting):
        raise ValueError("--shared is for ordinary claims (background claims already yield their cores)")
    if not shared and min_cores is not None:
        raise ValueError("--min-cores applies only with --shared")


def _update_claim_locked(claim: Path, **fields) -> bool:
    """Publish fields of this runner's own claim record (under the admission mutex), and return whether they are
    on disk: the record is read back after the write, and an unreadable record or a failed write is False. A
    change of state also records when it happened."""
    record = read_json(claim)
    if record is None:
        return False
    if not all(record.get(k) == v for k, v in fields.items()):
        update = dict(fields)
        if "state" in fields and record.get("state") != fields["state"]:
            update["state_at"] = now_utc()
        try:
            write_json(claim, {**record, **update})
        except OSError:
            return False
    after = read_json(claim)
    return after is not None and all(after.get(k) == v for k, v in fields.items())


def _record_lends(claim: Path) -> bool:
    """Whether this runner's published claim record lends any core, as read back now; an unreadable record counts
    as lending, so its lending marker stays."""
    record = read_json(claim)
    return record is None or _core_list(record.get("cores")) is None or bool(lent(record))


def _set_state_locked(claim: Path, state: str) -> bool:
    """Publish under the same mutex that protects timed admission and tree transitions."""
    return _update_claim_locked(claim, state=state)


def _acknowledge_suspension_locked(claim: Path, complete: bool, vacated: bool) -> bool:
    if complete:
        _set_state_locked(claim, "suspended")
        # A failed read-back can still mean the write reached disk.
        return True
    return vacated


def _resume_tree_locked(tree: "Tree", claim: Path) -> bool:
    # Make the record busy before any process can resume. A partial resume is busy too.
    state = "resuming" if tree.suspended else "running"
    if not _set_state_locked(claim, state) or not tree.set_suspended(False):
        return False
    if state == "resuming":
        _set_state_locked(claim, "running")
    return True


def _drain_conflict(tree: "Tree", claim: Path, claim_id: str, guard: list[int],
                    background: bool, shared: bool, vacated: bool) -> bool:
    """Stop lending the current footprint, and continue to honor handoffs already acknowledged."""
    record = read_json(claim)
    if record is None:
        return True
    # The published mask can be wider than tree.cores after a failed shared-affinity change.
    cores = set(record["cores"]) | set(tree.cores)
    if not _update_claim_locked(claim, draining=True, cores=sorted(cores)) or conflicts(cores):
        return True
    if not vacated:
        return False
    lent_cores = cores - set(guard) if shared else set()
    claims = live_claims()
    for other in claims:
        if other["id"] == claim_id:
            continue
        if background and not other.get("background"):
            # A suspended shared lender still owns its guarantee. On its lent CPUs it yields
            # to its borrower, even when both are draining.
            occupied = _guaranteed_cores(other) if other.get("state") == "suspended" else other["cores"]
            if cores.intersection(occupied):
                return True
        if lent_cores.intersection(held(other)):
            return True
    if lent_cores and len(claims) > 1:
        # A suspended shared drainer with extra cores checks the budget before resuming too.
        # Charge only its guarantee here so either tree can drain first if it fits.
        owners = [{**c, "cores": _guaranteed_cores(c)}
                  if c["id"] != claim_id and c.get("draining") and c.get("state") == "suspended" else c
                  for c in claims]
        try:
            return over_budget(load_config(), owners) > 0
        except ValueError:
            pass
    return False


def _share_step(tree: "Tree", claim: Path, claim_id: str, share: dict, *, grow: bool, draining: bool = False) -> bool:
    """One give-back (and optionally growth) step of a shared claim, under the admission mutex. The lent cores
    `give_back` names are given back first: the job affinity narrows, and only then does the record publish the
    narrower cores, so a claim waiting for them (`background_busy`, `budget_pending`) never starts while this tree
    can still run there. Growth, onto unclaimed cores and only while no queue file exists, publishes first and
    widens second. Returns False when a narrowing could not be applied; the caller then suspends the tree until a
    later step succeeds. A draining shared tree tries to give back every lent core."""
    snap = _snapshot()
    try:
        config = load_config()
    except ValueError:
        config = None
    timed = timed_state()
    claims = live_claims() if snap is None else snap["claims"]
    queued = snap is None or any(name.startswith("queue-") for name in snap["names"])
    # Lend nothing while lending is off here, or while an engine older than c543e1b4 shows itself (partial: it
    # cannot see an older copy that has not queued yet; the config gate is what keeps those away).
    closed = (config is None or not lending_enabled()
              or (snap is not None and legacy_backfill_engine(snap["tickets"], claims)))
    # After a failed change the OS may still hold another mask: re-apply the intended cores before anything else,
    # and report failure (the caller keeps the tree suspended) until that succeeds.
    if getattr(tree, "applied", tree.cores) != tree.cores and not tree.set_cores(tree.cores):
        return False
    me = {"id": claim_id, "shared": True, "guaranteed": share["guaranteed"], "cores": tree.cores}
    back = give_back(me, timed, claims, config, queued=queued or closed or draining)
    if back and not tree.set_cores(sorted(set(tree.cores) - set(back))):
        return False
    # The record must show exactly the job's cores (this also repairs an earlier failed publish); until it does,
    # it may still lend cores already given back: suspend and keep the marker.
    if not _update_claim_locked(claim, cores=tree.cores):
        return False
    if grow and not queued and not closed and len(tree.cores) < share["max_cores"]:
        others = [c for c in claims if c.get("id") != claim_id] + [{"id": claim_id, "cores": tree.cores}]
        extra = unclaimed(config, timed, others, core_pool=share["pool"])[:share["max_cores"] - len(tree.cores)]
        if extra:
            wider = sorted(set(tree.cores) | set(extra))
            narrow = tree.cores
            _set_lending_marker(claim_id, True)       # before any lent core is published
            # Widen only once the wider cores are confirmed on disk, so nobody is admitted onto them unseen.
            if _update_claim_locked(claim, cores=wider) and not tree.set_cores(wider):
                # The job may hold part of the wider set: put it and the record back, or suspend.
                if not tree.set_cores(narrow) or not _update_claim_locked(claim, cores=narrow):
                    return False
    if set(tree.cores) <= set(share["guaranteed"]) and not _record_lends(claim):
        _set_lending_marker(claim_id, False)          # only once a read-back record lends nothing
    return True


def _budget_wait(claim_id: str) -> bool:
    """True while lenders must still make budget room before this claim may run (under the admission mutex)."""
    try:
        config = load_config()
    except ValueError:
        return False
    return budget_pending(config, live_claims(), claim_id)


def _overdue_step(tree: "Tree", claim: Path, claim_id: str, overdue: dict, share: dict | None) -> str | None:
    """Apply the claim's own --on-overdue action once its deadline passed (under the admission mutex, by the
    runner that owns the job, so only this claim's own processes are ever touched). Returns the action taken, or
    None when nothing happened yet (not due, or a shared claim could not yet narrow to its guarantee)."""
    if overdue.get("done") or time.monotonic() <= overdue["deadline_mono"]:
        return None
    action = overdue["action"]
    if action == "demote" and share is not None:
        # A demoted claim is background work: it lends nothing, so it narrows to its guarantee first.
        if not tree.set_cores(share["guaranteed"]):
            return None
        if not _update_claim_locked(claim, cores=tree.cores, shared=False):
            return None
        if not _record_lends(claim):
            _set_lending_marker(claim_id, False)
    fields = {"overdue": True, "overdue_action": action, "overdue_at": now_utc()}
    if action == "demote":
        fields.update(background=True, draining=False)
    if not _update_claim_locked(claim, **fields) and action != "kill":
        return None           # retried next poll; a kill does not depend on its record
    overdue["done"] = True
    if action != "kill":
        _event("overdue", {"id": claim_id, "cores": tree.cores}, action=action)
    # A kill happens in the caller, outside the admission mutex (it may take up to its timeout).
    return action


def _run_claimed(claim: Path, cores: list[int], priority: str, command: list[str], cwd: str | None,
                 claim_id: str, *, background: bool = False, share: dict | None = None,
                 overdue: dict | None = None) -> int:
    tree = Tree(cores, priority)
    # A shared claim's command sees only its guarantee in HOST_SLOTS_CORES: the rest can be taken back any time.
    env = dict(os.environ, **{CLAIM_ENV: claim_id, CORES_ENV: format_cores(share["guaranteed"] if share else cores)})
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    # A shared claim suspends only when timed work overlaps its guaranteed cores; on its lent cores it narrows.
    guard = share["guaranteed"] if share else cores

    def stop(signum, _frame):
        tree.kill()
        raise SystemExit(128 + signum)

    for sig in previous:
        signal.signal(sig, stop)
    try:
        deadline = time.monotonic() + TIMED_VACATE_SECONDS
        while True:
            with Mutex():
                narrowed = _share_step(tree, claim, claim_id, share, grow=False) if share else True
                conflict = claim_conflicts(guard, background) or not narrowed
                budget_wait = not conflict and _budget_wait(claim_id)
                if not conflict and not budget_wait and not background_busy(tree.cores, claim_id):
                    if _set_state_locked(claim, "running"):
                        child = tree.start(command, cwd, env)
                        _event("start", {"id": claim_id, "cores": cores})
                        break
                # No child exists yet, so these cores are already vacated.
                _set_state_locked(claim, "suspended")
                # A lender may have started draining after this claim had already left the queue.
                draining = not conflict and any(
                    c.get("draining") and c["id"] != claim_id and c.get("state") != "suspended"
                    and (set(c["cores"]).intersection(tree.cores) or (budget_wait and lending(c)))
                    for c in live_claims())
            if conflict or draining:
                deadline = time.monotonic() + TIMED_VACATE_SECONDS
            elif time.monotonic() > deadline:
                raise Refused("background or shared work did not vacate the requested CPUs")
            time.sleep(poll_seconds())
        code = None
        kill_pending = False
        vacated = False
        grow_at = time.monotonic() + grow_seconds()
        while True:
            if kill_pending:
                # Outside the admission mutex: other runners keep admitting while this claim's own processes end.
                kill_pending = False
                ended = tree.kill_members()   # its own job's members only, never this runner or another claim
                with Mutex():
                    _event("overdue", {"id": claim_id, "cores": tree.cores}, action="kill", ended=ended)
                    if not ended:
                        _update_claim_locked(claim, kill_failed=True)
            if code is None:
                try:
                    code = child.wait(timeout=poll_seconds())
                except subprocess.TimeoutExpired:
                    pass
            # A member seen in this snapshot could spawn another before exiting. Wait for an empty snapshot.
            if code is not None and not tree.members():
                break
            with Mutex():
                if overdue is not None and code is None:
                    action = _overdue_step(tree, claim, claim_id, overdue, share)
                    if action == "demote":
                        share, background, guard = None, True, tree.cores
                    elif action == "kill":
                        kill_pending = True
                complete = None
                if code is None or not (background or share):
                    narrowed = _share_step(tree, claim, claim_id, share, grow=False) if share else True
                    conflict = claim_conflicts(guard, background) or not narrowed
                    if conflict and code is None and (background or share):
                        # An exit can race a complete or partial suspension. Recheck before acknowledging it.
                        complete = tree.set_suspended(True)
                        code = child.poll()
                if code is not None and (background or share):
                    if share:
                        # If narrowing fails, drain using the still-published footprint.
                        _share_step(tree, claim, claim_id, share, grow=False, draining=True)
                    conflict = _drain_conflict(tree, claim, claim_id, guard, background, share is not None, vacated)
                if conflict:
                    if complete is None:
                        complete = tree.set_suspended(True)
                    vacated = _acknowledge_suspension_locked(claim, complete, vacated)
                elif _resume_tree_locked(tree, claim):
                    vacated = False
                    if share and code is None and time.monotonic() >= grow_at:
                        if not _share_step(tree, claim, claim_id, share, grow=True):
                            # The job's mask or record is not settled: suspend until a later step settles it.
                            vacated = _acknowledge_suspension_locked(claim, tree.set_suspended(True), vacated)
                        grow_at = time.monotonic() + grow_seconds()
            if code is not None:
                time.sleep(poll_seconds())
        return code
    except BaseException:
        # Retain containment on every exit, including partial suspension errors.
        tree.kill()
        raise
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _run_adopted(claim: Path, cores: list[int], priority: str, claim_id: str,
                 background: bool, adopted: dict) -> int:
    """A CI worker first joins an empty job; its controller stays outside the worker job."""
    tree = Tree(cores, priority, contain_self=False)
    pid, creation = adopted["pid"], adopted["creation"]
    ready = Path(adopted["ready"])
    try:
        with Mutex():
            tree.adopt_worker_tree(pid, creation)
            _set_state_locked(claim, "suspended")
            # The contained hook cannot return while suspended. Publish readiness
            # now so a long legitimate preemption cannot become an admission timeout.
            write_json(ready, {"id": claim_id, "pid": os.getpid(), "creation_time": self_identity()[1],
                               "cores": cores, "worker_pid": pid, "worker_creation": creation})
        vacated = True
        draining = False
        while tree.members():
            with Mutex():
                complete = None
                draining = draining or process_state(pid, creation) == "absent"
                if not draining:
                    conflict = claim_conflicts(cores, background)
                    if conflict:
                        complete = tree.set_suspended(True)
                        draining = process_state(pid, creation) == "absent"
                if draining:
                    conflict = _drain_conflict(tree, claim, claim_id, cores, background, False, vacated)
                if conflict:
                    if complete is None:
                        complete = tree.set_suspended(True)
                    vacated = _acknowledge_suspension_locked(claim, complete, vacated)
                elif _resume_tree_locked(tree, claim):
                    vacated = False
            time.sleep(poll_seconds())
        return 0
    except BaseException:
        tree.kill()
        while tree.members():
            time.sleep(0.1)
        raise
    finally:
        ready.unlink(missing_ok=True)
        if tree.job is not None:
            _CloseHandle(tree.job)


def timed(cores: list[int], command: list[str], cwd: str | None = None,
          vacate_seconds: float = TIMED_VACATE_SECONDS) -> int:
    """Inside the v1 supervisor: pin command to cores, declare them for its lifetime, so
    untimed claims may use the rest of the host."""
    token = os.environ.get(TOKEN_ENV)
    if not token:
        raise Refused(f"{TOKEN_ENV} is not set: timed must run inside the host reservation's supervisor")
    if max(cores) >= cpu_total():
        raise ValueError(f"cores {format_cores(cores)} exceed this host's {cpu_total()} logical CPUs")
    held = timed_state()
    digest = token_hash(token)
    if not held["held"] or held.get("token_sha256") != digest:
        raise Refused(f"{TOKEN_ENV} does not hold {host()}")
    pid, creation = self_identity()
    share = slots_dir() / f"share-{digest[:16]}.json"
    with Mutex():
        _check_drain_rollout(live_claims())
        existing = read_json(share)
        if existing is not None and process_state(existing.get("pid"), existing.get("creation_time")) != "absent":
            raise Refused("this reservation already declared its cores")
        write_json(share, {"schema": SCHEMA, "token_sha256": digest, "cores": sorted(cores), "pid": pid,
                           "creation_time": creation, "lane": held.get("lane"), "work_id": held.get("work_id"),
                           "declared_at": now_utc()})
    try:
        tree = Tree(cores, None)
        deadline = time.monotonic() + vacate_seconds
        while True:  # claims on these cores suspend themselves; wait until each one has
            with Mutex():
                busy = [c["id"] for c in live_claims() if set(c["cores"]) & set(cores) and c.get("state") != "suspended"]
            if not busy:
                break
            if time.monotonic() > deadline:
                raise Refused(f"claims {busy} did not vacate cores {format_cores(cores)} within {vacate_seconds} s")
            time.sleep(0.25)
        child = tree.start(command, cwd, dict(os.environ, **{CORES_ENV: format_cores(cores)}))
        code = child.wait()
        while tree.members():
            time.sleep(1.0)
        return code
    finally:
        with Mutex():
            try:
                share.unlink()
            except OSError:
                pass


def submit(options: list[str], command: list[str], log: str) -> dict:
    """Start a detached `run --wait` and return its claim id at once."""
    with Mutex():
        _check_drain_rollout(live_claims())
    claim_id = uuid.uuid4().hex
    argv = [sys.executable, os.path.abspath(__file__), "run", "--wait", "--id", claim_id, *options, "--", *command]
    Path(log).parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as out:
        kwargs = {"stdin": subprocess.DEVNULL, "stdout": out, "stderr": subprocess.STDOUT}
        if os.name == "nt":
            try:
                proc = subprocess.Popen(argv, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
                                        | CREATE_BREAKAWAY_FROM_JOB, **kwargs)
            except OSError:  # the caller's job forbids breakaway: the run then ends with that job
                proc = subprocess.Popen(argv, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, **kwargs)
        else:
            proc = subprocess.Popen(argv, start_new_session=True, **kwargs)
    return {"id": claim_id, "pid": proc.pid, "log": log}


def status() -> dict:
    config = load_config()
    timed = timed_state()
    slots_dir().mkdir(parents=True, exist_ok=True)
    with Mutex():
        claims, tickets = live_claims(), live_tickets()
        live = {c.get("id") for c in claims}
        for marker in slots_dir().glob(f"{LENDING_MARKER}*.json"):   # a killed lender's marker
            if marker.name.removeprefix(LENDING_MARKER).removesuffix(".json") not in live:
                marker.unlink(missing_ok=True)
    keep = ("id", "lane", "work_id", "pid", "cores", "priority", "state", "acquired_at", "background", "draining")
    shared_keep = ("shared", "guaranteed", "max_cores", "core_pool", "core_pool_reason",
                   "max_seconds", "on_overdue", "overdue", "overdue_action")
    now = datetime.now(timezone.utc)
    backfills = []
    for c in claims:
        if c.get("backfill"):
            deadline_mono = c.get("deadline_mono")
            if isinstance(deadline_mono, (int, float)) and not isinstance(deadline_mono, bool):
                overdue = time.monotonic() > deadline_mono      # unmoved by wall-clock changes
            else:
                try:
                    overdue = now > datetime.fromisoformat(c["deadline_at"])
                except (KeyError, TypeError, ValueError):
                    overdue = None
            backfills.append({**{k: c.get(k) for k in ("id", "lane", "work_id", "cores", "max_seconds",
                                                       "acquired_at", "deadline_at", "head_id")},
                              # A delaying backfill's bound: the head's worst-case delay from its backfills.
                              "delay_bound_seconds": c.get("delay_bound_seconds", 0.0),
                              "delay_limit_seconds": c.get("delay_limit_seconds"),
                              "overdue": overdue})
    return {
        "host": host(), "root": str(root_dir()), "logical_cpus": cpu_total(),
        "config": {**config, "cores": format_cores(config["cores"])},
        "timed": {k: v for k, v in timed.items() if k != "token_sha256"},
        "claims": [{**{k: c.get(k) for k in keep}, **{k: c[k] for k in shared_keep if k in c}} for c in claims],
        "queue": [{**{k: t.get(k) for k in ("id", "lane", "work_id", "pid", "cores_wanted", "enqueued_at",
                                            "background", "max_seconds")},
                   **{k: t[k] for k in shared_keep if k in t}} for t in tickets],
        "backfill": backfills,
        # free counts lent cores (a new claim may take them); unclaimed and lent split them out.
        "free": format_cores(available(config, timed, claims)) or "",
        "foreground_available": format_cores(available(config, timed, claims, background=False)) or "",
        "unclaimed": format_cores(unclaimed(config, timed, claims)) or "",
        "lent": format_cores({core for c in claims for core in lent(c)}) or "",
        "ci_floor": format_cores(ci_floor_cores(config)) or "",
        "watch": watch_status(),
    }


def topology() -> list[dict]:
    """Physical cores: their logical CPUs and efficiency class (higher is faster; None when unknown)."""
    rows = []
    if os.name == "nt":
        length = wintypes.DWORD(0)
        _GetLogicalProcessorInformationEx(0, None, ctypes.byref(length))
        if ctypes.get_last_error() != ERROR_INSUFFICIENT_BUFFER:
            raise OSError(ctypes.get_last_error(), "GetLogicalProcessorInformationEx failed")
        buf = ctypes.create_string_buffer(length.value)
        if not _GetLogicalProcessorInformationEx(0, buf, ctypes.byref(length)):
            raise OSError(ctypes.get_last_error(), "GetLogicalProcessorInformationEx failed")
        offset = 0
        while offset < length.value:
            relation, size = struct.unpack_from("<II", buf, offset)
            if relation == 0:  # RelationProcessorCore
                flags, efficiency = struct.unpack_from("<BB", buf, offset + 8)
                (groups,) = struct.unpack_from("<H", buf, offset + 30)
                cpus = []
                for g in range(groups):
                    mask, group = struct.unpack_from("<QH", buf, offset + 32 + 16 * g)
                    cpus += [group * 64 + i for i in range(64) if mask >> i & 1]
                rows.append({"cpus": format_cores(cpus), "efficiency_class": efficiency, "smt": bool(flags & 1)})
            offset += size
        return rows
    hybrid = {}
    for kind, rank in (("cpu_core", 1), ("cpu_atom", 0)):
        listed = Path(f"/sys/devices/{kind}/cpus")
        if listed.exists():
            hybrid.update({cpu: rank for cpu in parse_cores(listed.read_text().strip())})
    seen, binding = set(), cpu_binding()
    index = None if binding is None else {cpu: i for i, cpu in enumerate(binding)}
    for cpu in (range(cpu_total()) if binding is None else binding):
        siblings = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology/thread_siblings_list")
        group = parse_cores(siblings.read_text().strip()) if siblings.exists() else [cpu]
        if index is not None:  # logical numbers; siblings outside the binding are not this host's
            group = [index[sibling] for sibling in group if sibling in index]
        if tuple(group) in seen:
            continue
        seen.add(tuple(group))
        rows.append({"cpus": format_cores(group), "efficiency_class": hybrid.get(cpu), "smt": len(group) > 1})
    return rows


# ---------------------------------------------------------------- utilization watcher
#
# `watch` samples per-CPU busy time and the slot records, and flags; it never acts on a claim:
# - low_use: a running ordinary claim whose aggregate busy over its held cores (a shared claim's guaranteed ones)
#   stays under WATCH_LOW_BUSY for WATCH_LOW_SECONDS;
# - queued_idle: a ticket seen twice and queued WATCH_QUEUED_SECONDS while a configured core outside timed work
#   and keep_free is unclaimed, with the cause from the same `available()` view admission uses.
# Each sample appends one line to <root>/<HOST>.util/util-YYYYMMDD.jsonl; runners append admit and end events to
# events-YYYYMMDD.jsonl beside it; `watch-report` sums both. The watcher reads records without the admission
# mutex and deletes nothing.

WATCH_LOW_BUSY = 0.30
WATCH_LOW_SECONDS = 600.0
WATCH_QUEUED_SECONDS = 60.0
WATCH_NOTES_PER_HOUR = 6
# Holder kinds of a CPU, first match wins.
KINDS = ("timed", "held", "guaranteed", "lent", "background", "ci_floor", "unclaimed")

if os.name == "nt":
    class _ProcessorTimes(ctypes.Structure):
        _fields_ = [("IdleTime", ctypes.c_longlong), ("KernelTime", ctypes.c_longlong),
                    ("UserTime", ctypes.c_longlong), ("DpcTime", ctypes.c_longlong),
                    ("InterruptTime", ctypes.c_longlong), ("InterruptCount", wintypes.ULONG)]

    _NtQuerySystemInformation = _fn(_ntdll, "NtQuerySystemInformation", ctypes.c_long, ctypes.c_int,
                                    wintypes.LPVOID, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG))


def cpu_times() -> dict[int, tuple[int, int]]:
    """Cumulative (busy, total) time per logical CPU, in the OS's units. Windows: busy is kernel plus user time
    minus idle (SystemProcessorPerformanceInformation, the first processor group); Linux: /proc/stat, with idle
    plus iowait as idle, renumbered to logical CPUs under a CPU binding."""
    if os.name == "nt":
        count = min(cpu_total(), 64)
        array = (_ProcessorTimes * count)()
        got = wintypes.ULONG(0)
        status = _NtQuerySystemInformation(8, ctypes.byref(array), ctypes.sizeof(array), ctypes.byref(got))
        if status < 0:
            raise OSError(f"NtQuerySystemInformation failed ({status & 0xFFFFFFFF:#x})")
        rows = {}
        for cpu in range(got.value // ctypes.sizeof(_ProcessorTimes)):
            total = array[cpu].KernelTime + array[cpu].UserTime
            rows[cpu] = (total - array[cpu].IdleTime, total)
        return rows
    binding = cpu_binding()
    index = None if binding is None else {cpu: i for i, cpu in enumerate(binding)}
    rows = {}
    for line in Path("/proc/stat").read_text(encoding="ascii").splitlines():
        name, *values = line.split()
        if not name.startswith("cpu") or name == "cpu":
            continue
        cpu = int(name[3:])
        if index is not None:
            if cpu not in index:
                continue
            cpu = index[cpu]
        ticks = [int(v) for v in values[:8]]
        total = sum(ticks)
        rows[cpu] = (total - ticks[3] - ticks[4], total)
    return rows


def util_dir() -> Path:
    return root_dir() / f"{host()}.util"


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    if rows:
        text = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as out:
            out.write(text)


def _peek() -> tuple[list[dict], list[dict]]:
    """Live claims and tickets (tickets in admission order) without the admission mutex. Records of exited
    launchers and unreadable files are skipped, never removed."""
    claims, tickets = [], []
    try:
        names = sorted(p.name for p in slots_dir().iterdir()
                       if p.name.endswith(".json") and p.name.startswith(("claim-", "queue-")))
    except OSError:
        return [], []
    for name in names:
        record = read_json(slots_dir() / name)
        if record is None or process_state(record.get("pid"), record.get("creation_time")) == "absent":
            continue
        if name.startswith("claim-"):
            if _core_list(record.get("cores")) is not None:
                claims.append(record)
        else:
            tickets.append(record)
    tickets.sort(key=lambda t: bool(t.get("background", False)))
    return claims, tickets


def queue_cause(config: dict, timed: dict, claims: list[dict], tickets: list[dict], ticket: dict) -> str:
    """Why a queued ticket is not running, from the admission view: starting (it can start now), head_of_line
    (a head ahead of it cannot start; no_max_seconds when it has no limit to backfill with), pool (it would fit
    without its core pool), timed (without the timed hold), keep_free (without keep_free) or too_few_free."""
    wanted = ticket.get("cores_wanted")
    if isinstance(wanted, bool) or not isinstance(wanted, int) or wanted < 1:
        return "unreadable"
    background = bool(ticket.get("background", False))

    def fits(t=timed, c=config, pool=_pool(ticket)):
        return len(available(c, t, claims, background=background, core_pool=pool)) >= wanted

    if fits():
        head = tickets[0] if tickets else None
        if head is not None and head.get("id") != ticket.get("id") and isinstance(head.get("cores_wanted"), int) \
                and _head_start(config, timed, claims, head) is None:
            return "head_of_line" if _max_seconds(ticket) is not None else "no_max_seconds"
        return "starting"
    if _pool(ticket) is not None and fits(pool=None):
        return "pool"
    if timed["held"] and fits(t={"held": False, "cores": []}):
        return "timed"
    if config["keep_free"] and fits(c={**config, "keep_free": 0}):
        return "keep_free"
    if not background and config.get("ci_floor") and fits(c={k: v for k, v in config.items() if k != "ci_floor"}):
        return "ci_floor"
    return "too_few_free"


def holders(config: dict, timed: dict, claims: list[dict]) -> dict[int, str]:
    """Each configured CPU's holder kind, first match in KINDS order: timed, held (an ordinary claim), guaranteed
    (a shared claim's guarantee), lent, background, unclaimed."""
    marks = {cpu: set() for cpu in config["cores"]}
    if timed["held"]:
        for cpu in (config["cores"] if timed["cores"] is None else timed["cores"]):
            if cpu in marks:
                marks[cpu].add("timed")
    for claim in claims:
        if claim.get("background", False):
            kind_held = "background"
        else:
            kind_held = "guaranteed" if claim.get("shared") is True else "held"
        for cpu in held(claim):
            if cpu in marks:
                marks[cpu].add(kind_held)
        for cpu in lent(claim):
            if cpu in marks:
                marks[cpu].add("lent")
    floor = set(ci_floor_cores(config))
    return {cpu: next((k for k in KINDS if k in found), "ci_floor" if cpu in floor else "unclaimed")
            for cpu, found in marks.items()}


def effective_reserve(config: dict, kinds: dict[int, str]) -> int:
    """The keep_free cores beyond timed-blocked ones: `available()` hands out at most min(open CPUs, configured
    minus keep_free), so this many open CPUs are held back."""
    open_cpus = sum(1 for kind in kinds.values() if kind != "timed")
    return max(0, open_cpus - max(0, min(open_cpus, len(config["cores"]) - config["keep_free"])))


def reserved_idle(idle: dict[int, float], kinds: dict[int, str], reserve: int, capacity: float) -> dict[int, float]:
    """Per-CPU idle net of the keep_free reserve and bounded by capacity: the reserve is taken from idle CPUs,
    unclaimed ones first, then lent, background, guaranteed and held, most idle first, never below zero; if the
    rest still exceeds capacity (claims over the budget), every CPU is scaled down alike. So
    0 <= sum <= capacity."""
    left = dict(idle)
    need = float(reserve)
    rank = {kind: i for i, kind in enumerate(("unclaimed", "ci_floor", "lent", "background", "guaranteed", "held"))}
    for cpu in sorted(left, key=lambda c: (rank.get(kinds.get(c), 9), -left[c])):
        take = min(need, left[cpu])
        left[cpu] -= take
        need -= take
    total = sum(left.values())
    if total > capacity > 0:
        left = {cpu: value * capacity / total for cpu, value in left.items()}
    elif capacity <= 0:
        left = {cpu: 0.0 for cpu in left}
    return left


def eligible_idle(config: dict, timed: dict, tickets: list[dict], causes: list[str], idle: dict[int, float],
                  kinds: dict[int, str]) -> tuple[float, dict[str, float]]:
    """Idle capacity (cores) queued tickets were allowed to use: in queue order, each ticket takes idle on its
    allowed CPUs (configured, inside its pool, not timed-blocked), most idle first, up to its cores wanted,
    without double counting. `idle` is already net of the keep_free reserve (`reserved_idle`). Returns the total
    and its attribution to causes (the attribution sums to the total). Indivisible requests are not modeled: an
    upper bound."""
    left = dict(idle)
    total, by_cause = 0.0, {}
    for ticket, cause in zip(tickets, causes):
        wanted = ticket.get("cores_wanted")
        if cause == "unreadable" or not isinstance(wanted, int):
            continue
        pool = _pool(ticket)
        floor = set() if ticket.get("background", False) else set(ci_floor_cores(config))
        allowed = [c for c in left if kinds.get(c) != "timed" and c not in floor and (pool is None or c in pool)]
        need = float(wanted)
        for cpu in sorted(allowed, key=lambda c: -left[c]):
            if need <= 0:
                break
            take = min(need, left[cpu])
            left[cpu] -= take
            need -= take
            total += take
            by_cause[cause] = by_cause.get(cause, 0.0) + take
    return total, by_cause


def watch_tick(state: dict, counters: dict, mono: float, wall: str, config: dict, timed: dict,
               claims: list[dict], tickets: list[dict], *, interval: float, low: float = WATCH_LOW_BUSY,
               low_seconds: float = WATCH_LOW_SECONDS) -> tuple[dict, list[dict], list[dict]]:
    """One watcher sample: the new state, the log lines (the sample, then any claim_end) and the new nudges.
    A sample measures nothing, and every low-use run restarts, when the previous sample is missing, more than 3
    intervals old or later on the monotonic clock (a reboot); a CPU whose total time did not grow is unknown."""
    previous = state.get("mono")
    dt = None if not isinstance(previous, (int, float)) else mono - previous
    valid = dt is not None and 0 < dt <= 3 * interval
    old = state.get("counters", {})
    busy = {}
    if valid:
        for cpu in config["cores"]:
            before, now = old.get(str(cpu)), counters.get(cpu)
            if before and now and now[1] > before[1] and now[0] >= before[0]:
                busy[cpu] = min(1.0, max(0.0, (now[0] - before[0]) / (now[1] - before[1])))
    kinds = holders(config, timed, claims)
    idle = {cpu: 1.0 - b for cpu, b in busy.items() if kinds[cpu] != "timed"}
    unclaimed_count = sum(1 for kind in kinds.values() if kind == "unclaimed") - effective_reserve(config, kinds)
    causes = [queue_cause(config, timed, claims, tickets, t) for t in tickets]
    demand = sum(t["cores_wanted"] for t, c in zip(tickets, causes) if c != "unreadable")
    line = {"event": "sample", "t": wall, "dt": round(dt, 3) if valid else None, "interval": interval,
            "cpus": config["cores"], "busy": [None if c not in busy else round(busy[c], 3) for c in config["cores"]],
            "kind": [kinds[c] for c in config["cores"]],
            "queue": [{"id": t.get("id"), "lane": t.get("lane"), "work_id": t.get("work_id"),
                       "wanted": t.get("cores_wanted"), "background": bool(t.get("background", False)), "cause": c}
                      for t, c in zip(tickets, causes)],
            "queued_demand": demand}
    owner = {}
    for claim in claims:
        for cpu in claim["cores"]:
            if cpu in kinds and (cpu not in owner or cpu in held(claim)):
                owner[cpu] = claim.get("id")
    line["owner"] = [owner.get(c) for c in config["cores"]]
    line["claims"] = {c.get("id"): {"lane": c.get("lane"), "work_id": c.get("work_id"),
                                    "shared": c.get("shared") is True, "background": bool(c.get("background", False)),
                                    "state": c.get("state")} for c in claims if isinstance(c.get("id"), str)}
    if valid:
        measured = [c for c in config["cores"] if kinds[c] != "timed" and c in busy]
        open_cpus = sum(1 for kind in kinds.values() if kind != "timed")
        reserve = effective_reserve(config, kinds)
        # What available() can hand out: never negative, keep_free counted only beyond timed-blocked CPUs.
        capacity = max(0, min(len(measured), open_cpus - reserve))
        net = reserved_idle({c: idle[c] for c in measured}, kinds, reserve, capacity)
        by_kind = {kind: 0.0 for kind in KINDS[1:]}
        for cpu in measured:
            by_kind[kinds[cpu]] += net[cpu]
        total_idle = sum(by_kind.values())
        eligible, by_cause = eligible_idle(config, timed, tickets, causes, net, kinds)
        line["idle_by_owner_cs"] = {}
        for cpu in measured:
            if owner.get(cpu) is not None:
                key = owner[cpu]
                line["idle_by_owner_cs"][key] = round(line["idle_by_owner_cs"].get(key, 0.0) + net[cpu] * dt, 3)
        line.update(capacity_cs=round(capacity * dt, 3), idle_cs=round(total_idle * dt, 3),
                    eligible_idle_cs=round(eligible * dt, 3),
                    coincident_idle_cs=round(min(total_idle, demand) * dt, 3),
                    eligible_idle_by_cause={c: round(v * dt, 3) for c, v in sorted(by_cause.items())},
                    **{f"idle_{kind}_cs": round(value * dt, 3) for kind, value in by_kind.items()},
                    claimed_cs={kind: round(sum(dt for c in measured if kinds[c] == kind), 3)
                                for kind in ("held", "guaranteed", "lent", "background")})

    lows = state.get("low", {}) if valid else {}
    seen = state.get("tickets", {})
    acc = state.get("claims", {})
    flags, lines, live_lows = [], [line], {}
    for claim in claims:
        cid = claim.get("id")
        if not isinstance(cid, str):
            continue
        mine = held(claim)
        known = [cpu for cpu in mine if cpu in busy]
        if valid:
            entry = acc.setdefault(cid, {"lane": claim.get("lane"), "work_id": claim.get("work_id"),
                                         "shared": claim.get("shared") is True,
                                         "background": bool(claim.get("background", False)),
                                         "first": wall, "seconds": 0.0, "held_cs": 0.0, "busy_cs": 0.0,
                                         "lent_cs": 0.0, "lent_busy_cs": 0.0})
            entry["seconds"] += dt
            entry["held_cs"] += len(known) * dt
            entry["busy_cs"] += sum(busy[cpu] for cpu in known) * dt
            for cpu in lent(claim):
                if cpu in busy:
                    entry["lent_cs"] += dt
                    entry["lent_busy_cs"] += busy[cpu] * dt
        if claim.get("background", False) or claim.get("state") != "running" or not known:
            continue
        load = sum(busy[cpu] for cpu in known)
        if load / len(known) < low:
            since = lows.get(cid)
            since = since if isinstance(since, (int, float)) else mono - dt
            live_lows[cid] = since
            if mono - since >= low_seconds:
                flags.append({"kind": "low_use", "id": cid, "lane": claim.get("lane"), "work_id": claim.get("work_id"),
                              "held": format_cores(mine), "busy_cores": round(load, 2),
                              "detail": f"{len(mine)} held cores ({format_cores(mine)}) averaged under {low:.0%} busy "
                                        f"for {(mono - since) / 60:.0f} min (now {load:.1f} busy cores)"
                                        + ("" if claim.get("shared") else
                                           "; a build or other bursty job can run with --shared so idle cores are lent")})
    for record in [*claims, *tickets]:
        if record.get("core_pool_reason") == POOL_REASON_UNSPECIFIED and isinstance(record.get("id"), str):
            flags.append({"kind": "pool_unspecified", "id": record["id"], "lane": record.get("lane"),
                          "work_id": record.get("work_id"),
                          "detail": f"--core-pool {format_cores(_pool(record) or [])} has no --pool-reason; it is "
                                    f"refused from {POOL_REASON_REQUIRED_FROM}: add --pool-reason ("
                                    + ", ".join(POOL_REASONS) + ") or drop the pool"})
    live_ids = {c.get("id") for c in claims}
    for cid in [cid for cid in acc if cid not in live_ids]:
        entry = acc.pop(cid)
        seconds = entry["seconds"] or None
        lines.append({"event": "claim_end", "t": wall, "id": cid, **entry,
                      "mean_busy_cores": None if not seconds else round(entry["busy_cs"] / seconds, 3),
                      "mean_held_cores": None if not seconds else round(entry["held_cs"] / seconds, 3)})
    live_tickets = {}
    for t, cause in zip(tickets, causes):
        tid = t.get("id")
        if not isinstance(tid, str):
            continue
        row = seen.get(tid) if valid else None
        if not (isinstance(row, dict) and isinstance(row.get("first_mono"), (int, float))
                and isinstance(row.get("samples"), int) and row["first_mono"] <= mono):
            row = {"first_mono": mono, "samples": 0}
        row = {"first_mono": row["first_mono"], "samples": row["samples"] + 1}
        live_tickets[tid] = row
        if (unclaimed_count >= 1 and row["samples"] >= 2 and mono - row["first_mono"] >= WATCH_QUEUED_SECONDS
                and cause not in ("starting", "unreadable")):
            flags.append({"kind": "queued_idle", "id": tid, "lane": t.get("lane"), "work_id": t.get("work_id"),
                          "cause": cause, "wanted": t.get("cores_wanted"),
                          "detail": f"queued {mono - row['first_mono']:.0f} s for {t.get('cores_wanted')} cores while "
                                    f"{unclaimed_count} cores are unclaimed; cause {cause}"
                                    + (f" (pool {format_cores(_pool(t))}, reason {t.get('core_pool_reason')})"
                                       if cause == "pool" else "")})
    live = {str(i) for i in live_ids} | set(live_tickets)
    nudged = [key for key in state.get("nudged", []) if isinstance(key, str) and key.split(":", 1)[-1] in live]
    nudges = []
    for flag in flags:
        key = f"{flag['kind']}:{flag['id']}"
        if key not in nudged:
            nudged.append(key)
            nudges.append({"t": wall, **flag})
    new_state = {"mono": mono, "sampled_at": wall, "interval": interval,
                 "counters": {str(cpu): list(value) for cpu, value in counters.items()},
                 "low": live_lows, "tickets": live_tickets, "claims": acc, "flags": flags, "nudged": nudged,
                 "notes": [m for m in state.get("notes", []) if isinstance(m, (int, float)) and 0 <= mono - m < 3600]}
    return new_state, lines, nudges


def _notify(command: list[str], nudge: dict) -> str | None:
    """Run the notify command with fleet_note.py's arguments; returns an error text or None."""
    title = f"host_slots {nudge['kind']}: {nudge.get('lane')}/{nudge.get('work_id')} on {host()}"
    body = (f"{nudge['detail']}. Claim or ticket {nudge['id']}. Nothing was changed; the watcher only reports. "
            f"See `host_slots_v1.py status` (watch field) and {util_dir() / 'nudges.jsonl'}.")
    try:
        out = subprocess.run([*command, "--to", str(nudge.get("lane")), "--title", title, "--body", body,
                              "--sender", "host_slots watch"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    return None if out.returncode == 0 else (out.stderr or out.stdout)[-300:]


def watch(interval: float = 30.0, once: bool = False, notify: list[str] | None = None,
          duration: float | None = None) -> int:
    """Sample, log and flag every interval (once with `once`). Never takes the admission mutex or changes a claim."""
    folder = util_dir()
    folder.mkdir(parents=True, exist_ok=True)
    state_path = folder / "watch-state.json"
    stop_at = None if duration is None else time.monotonic() + duration
    while True:
        state = read_json(state_path) or {}
        try:
            config = load_config()
            timed = timed_state()
            claims, tickets = _peek()
            counters = cpu_times()
        except (OSError, ValueError) as exc:   # a bad config edit or a failed counter read: log it, keep watching
            _append_jsonl(folder / f"util-{now_utc()[:10].replace('-', '')}.jsonl",
                          [{"event": "error", "t": now_utc(), "error": str(exc)[:300]}])
            if once:
                return EXIT_REFUSED
            time.sleep(interval)
            continue
        mono, wall = time.monotonic(), now_utc()
        state, lines, nudges = watch_tick(state, counters, mono, wall, config, timed, claims, tickets,
                                          interval=interval)
        _append_jsonl(folder / f"util-{wall[:10].replace('-', '')}.jsonl", lines)
        for nudge in nudges:
            if notify and len(state["notes"]) < WATCH_NOTES_PER_HOUR:
                error = _notify(notify, nudge)
                state["notes"].append(mono)
                nudge = {**nudge, "notified": error is None, **({"notify_error": error} if error else {})}
            _append_jsonl(folder / "nudges.jsonl", [nudge])
        write_json(state_path, state)
        if once or (stop_at is not None and time.monotonic() >= stop_at):
            return EXIT_OK
        time.sleep(interval)


def watch_status() -> dict | None:
    """The watcher's current flags for `status`, or None when no watcher has run here."""
    state = read_json(util_dir() / "watch-state.json")
    if state is None:
        return None
    mono, interval = state.get("mono"), state.get("interval")
    stale = (not isinstance(mono, (int, float)) or not isinstance(interval, (int, float))
             or not 0 <= time.monotonic() - mono <= 3 * interval)
    return {"sampled_at": state.get("sampled_at"), "stale": stale, "flags": state.get("flags", [])}


def _rows(pattern: str, lo, hi):
    for path in sorted(util_dir().glob(pattern)):
        for text in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(text)
                at = datetime.fromisoformat(row["t"])
            except (ValueError, KeyError, TypeError):
                continue
            if (lo is None or at >= lo) and (hi is None or at < hi):
                yield at, row


def watch_report(since: str | None = None, until: str | None = None) -> dict:
    """Totals over the watcher's samples and the runners' events between two ISO times (start inclusive, end
    exclusive). Core-hours are `_ch`. Fields older launchers never wrote are counted as unknown, not zero."""
    def utc(text):
        moment = datetime.fromisoformat(text)
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)   # a naive time is UTC

    lo = utc(since) if since else None
    hi = utc(until) if until else None
    sums = {"samples": 0, "unmeasured_samples": 0, "observed_s": 0.0, "queued_s": 0.0}
    cs, by_cause, claimed, first, last, idle_lanes = {}, {}, {}, None, None, {}
    lanes = {}
    for at, row in _rows("util-*.jsonl", lo, hi):
        first, last = first or at, at
        if row.get("event") == "sample":
            if not row.get("dt"):
                sums["unmeasured_samples"] += 1
                continue
            sums["samples"] += 1
            sums["observed_s"] += row["dt"]
            if row.get("queued_demand"):
                sums["queued_s"] += row["dt"]
            for key, value in row.items():
                if key.endswith("_cs") and isinstance(value, (int, float)):
                    cs[key] = cs.get(key, 0.0) + value
            for cause, value in row.get("eligible_idle_by_cause", {}).items():
                by_cause[cause] = by_cause.get(cause, 0.0) + value
            for kind, value in row.get("claimed_cs", {}).items():
                claimed[kind] = claimed.get(kind, 0.0) + value
            for cid, value in row.get("idle_by_owner_cs", {}).items():
                meta = row.get("claims", {}).get(cid, {})
                lane = idle_lanes.setdefault(str(meta.get("lane")), {"idle_ch": 0.0, "shared_idle_ch": 0.0})
                lane["idle_ch"] += value / 3600
                if meta.get("shared"):
                    lane["shared_idle_ch"] += value / 3600
        elif row.get("event") == "claim_end":
            lane = lanes.setdefault(str(row.get("lane")), {"claims": 0, "held_ch": 0.0, "idle_held_ch": 0.0})
            lane["claims"] += 1
            lane["held_ch"] += row.get("held_cs", 0.0) / 3600
            lane["idle_held_ch"] += (row.get("held_cs", 0.0) - row.get("busy_cs", 0.0)) / 3600
    admits, starts, ends = {}, {}, {}
    for at, row in _rows("events-*.jsonl", lo, hi):
        if isinstance(row.get("id"), str):
            if row.get("event") == "admit":
                admits[row["id"]] = (at, row)
            elif row.get("event") == "start":
                starts[row["id"]] = at
            elif row.get("event") == "end":
                ends[row["id"]] = at
    handoff = [(starts[cid] - at).total_seconds() for cid, (at, _) in admits.items() if cid in starts]
    transfer_cs, replay_wait, replay_saved_s, unknown = 0.0, 0, 0.0, 0
    for cid, (at, row) in admits.items():
        if cid in ends and row.get("took_lent"):
            transfer_cs += len(row["took_lent"]) * (ends[cid] - at).total_seconds()
        if row.get("old_rules_room") is False:
            replay_wait += 1
        elif row.get("old_rules_room") is None:
            unknown += 1
    span = None if first is None else ((hi or last) - (lo or first)).total_seconds()
    hours = lambda value: round(value / 3600, 3)
    shared_cs = claimed.get("guaranteed", 0.0) + claimed.get("lent", 0.0)
    all_cs = shared_cs + claimed.get("held", 0.0)
    return {"host": host(), "since": since, "until": until,
            "observed_h": hours(sums["observed_s"]),
            "coverage": None if not span else round(sums["observed_s"] / span, 4),
            "samples": sums["samples"], "unmeasured_samples": sums["unmeasured_samples"],
            "queued_h": hours(sums["queued_s"]),
            "capacity_ch": hours(cs.get("capacity_cs", 0.0)), "idle_ch": hours(cs.get("idle_cs", 0.0)),
            "mean_utilization": None if not cs.get("capacity_cs") else
            round(1 - cs.get("idle_cs", 0.0) / cs["capacity_cs"], 4),
            "eligible_idle_ch": hours(cs.get("eligible_idle_cs", 0.0)),
            "eligible_idle_ch_per_queued_h": None if not sums["queued_s"] else
            round(cs.get("eligible_idle_cs", 0.0) / sums["queued_s"], 3),
            "coincident_idle_ch": hours(cs.get("coincident_idle_cs", 0.0)),
            "eligible_idle_ch_by_cause": {c: hours(v) for c, v in sorted(by_cause.items())},
            "idle_ch_by_kind": {k[5:-3]: hours(v) for k, v in sorted(cs.items()) if k.startswith("idle_") and k != "idle_cs"},
            "shared_share_of_claimed": None if not all_cs else round(shared_cs / all_cs, 4),
            "events_are_lower_bounds": True,
            "admits": len(admits), "starts": len(starts), "ends": len(ends),
            "censored_admits": sum(1 for cid in admits if cid not in ends),
            "handoff_seconds_max": None if not handoff else round(max(handoff), 3),
            "handoff_seconds_mean": None if not handoff else round(sum(handoff) / len(handoff), 3),
            "took_lent_transfer_ch": hours(transfer_cs),
            "admits_without_old_rules_room": replay_wait, "admits_old_rules_unknown": unknown,
            "idle_by_lane": {k: {kk: round(vv, 3) for kk, vv in v.items()} for k, v in sorted(idle_lanes.items())},
            "lanes": {k: {kk: round(vv, 3) if isinstance(vv, float) else vv for kk, vv in v.items()}
                      for k, v in sorted(lanes.items())}}


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    command: list[str] = []
    if "--" in argv:
        split = argv.index("--")
        argv, command = argv[:split], argv[split + 1:]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="op", required=True)
    for op in ("run", "submit", "adopt"):
        p = sub.add_parser(op)
        p.add_argument("--lane", required=True)
        p.add_argument("--work-id", required=True)
        p.add_argument("--cores", type=int, required=True)
        p.add_argument("--core-pool", help="restrict this request to a configured CPU set (needs --pool-reason); "
                                           "the request waits while the set lacks room even if other cores are free")
        p.add_argument("--pool-reason", choices=POOL_REASONS, help="why the request must stay inside --core-pool")
        p.add_argument("--priority", choices=PRIORITIES)
        p.add_argument("--wait-timeout", type=float)
        p.add_argument("--cwd")
        p.add_argument("--background", action="store_true")
        if op != "adopt":
            p.add_argument("--shared", action="store_true",
                           help="guarantee --min-cores and lend the rest of --cores: any later claim may take a lent "
                                "core (this claim narrows first), and it grows back onto unclaimed cores while "
                                "nothing is queued; for builds and other bursty work, never for timing")
            p.add_argument("--min-cores", type=int, help="cores a --shared claim guarantees and queues for (default 1)")
            p.add_argument("--on-overdue", choices=OVERDUE_ACTIONS,
                           help="what this claim's runner does past --max-seconds (default flag: only marks it; "
                                "demote: it becomes background work that others may suspend; kill: ends its own tree)")
            p.add_argument("--max-seconds", type=float,
                           help="declared run time limit; lets the request start before the queue head when that "
                                "cannot delay the head (past it, status flags the claim overdue)")
        if op == "run":
            p.add_argument("--wait", action="store_true")
            p.add_argument("--id")
        elif op == "submit":
            p.add_argument("--log", required=True)
        else:
            p.add_argument("--worker", required=True, help="JSON file with verified worker and existing descendants")
            p.add_argument("--ready", required=True)
    p = sub.add_parser("timed")
    p.add_argument("--cores", required=True)
    p.add_argument("--cwd")
    sub.add_parser("status")
    sub.add_parser("topology")
    p = sub.add_parser("watch", help="sample CPU use and the records, log, flag and nudge; never changes a claim "
                                     "(-- NOTIFY_CMD... is run once per new flag with --to --title --body --sender)")
    p.add_argument("--interval", type=float, default=30.0)
    p.add_argument("--once", action="store_true")
    p.add_argument("--duration", type=float, help="stop after this many seconds")
    p = sub.add_parser("watch-report")
    p.add_argument("--since", help="ISO time, inclusive")
    p.add_argument("--until", help="ISO time, exclusive")
    args = parser.parse_args(argv)
    try:
        if args.op in ("run", "submit", "timed") and not command:
            parser.error(f"{args.op} needs -- COMMAND...")
        if args.op == "watch":
            if not args.interval > 0:
                raise ValueError("--interval must be above 0")
            return watch(args.interval, once=args.once, notify=command or None, duration=args.duration)
        if args.op == "watch-report":
            print(json.dumps(watch_report(args.since, args.until), indent=1))
            return EXIT_OK
        if args.op in ("run", "submit") and args.shared and not lending_enabled():
            raise ValueError("shared claims are off on this host: set \"lending\": true in its slots config.json "
                             "only after every host_slots copy that can queue here is c543e1b4 or later")
        if args.op in ("run", "submit", "adopt"):
            _check_placement(args.core_pool, args.pool_reason, getattr(args, "shared", False),
                             getattr(args, "min_cores", None), args.background, args.op == "adopt",
                             getattr(args, "max_seconds", None), getattr(args, "on_overdue", None), warn=True)
        command = child_command(command)
        if args.op == "run":
            def announce(claimed):
                print(json.dumps({"claimed": claimed["id"], "cores": format_cores(claimed["cores"]),
                                  **({"backfill": True} if claimed.get("backfill") else {})}), flush=True)
            code = run(args.lane, args.work_id, args.cores, command, wait=args.wait, wait_timeout=args.wait_timeout,
                       priority=args.priority, claim_id=args.id, cwd=args.cwd, on_claim=announce,
                       background=args.background, core_pool=parse_cores(args.core_pool) if args.core_pool else None,
                       max_seconds=args.max_seconds, pool_reason=args.pool_reason,
                       shared=args.shared, min_cores=args.min_cores, on_overdue=args.on_overdue)
            print(json.dumps({"exit_code": code}), flush=True)
            return code
        if args.op == "submit":
            if args.max_seconds is not None and _max_seconds({"max_seconds": args.max_seconds}) is None:
                raise ValueError(f"max seconds must be a number above 0 and at most {BACKFILL_MAX_SECONDS:.0f}")
            options = ["--lane", args.lane, "--work-id", args.work_id, "--cores", str(args.cores)]
            if args.background:
                options.append("--background")
            if args.shared:
                options.append("--shared")
            for flag, value in (("--priority", args.priority), ("--wait-timeout", args.wait_timeout),
                                ("--cwd", args.cwd), ("--core-pool", args.core_pool),
                                ("--pool-reason", args.pool_reason),
                                ("--min-cores", args.min_cores), ("--max-seconds", args.max_seconds),
                                ("--on-overdue", args.on_overdue)):
                if value is not None:
                    options += [flag, str(value)]
            print(json.dumps(submit(options, command, args.log)))
            return EXIT_OK
        if args.op == "adopt":
            if os.name != "nt":
                raise Refused("adopting an existing worker requires Windows")
            if not args.background:
                raise Refused("existing CI worker adoption requires --background")
            worker = read_json(Path(args.worker))
            if not worker or not isinstance(worker.get("pid"), int) or not isinstance(worker.get("creation"), int):
                raise Refused("worker file has no process identity")
            worker["ready"] = args.ready
            return run(args.lane, args.work_id, args.cores, ["adopt"], wait=True,
                       wait_timeout=args.wait_timeout, priority=args.priority, background=args.background,
                       adopted=worker, core_pool=parse_cores(args.core_pool) if args.core_pool else None,
                       pool_reason=args.pool_reason)
        if args.op == "timed":
            return timed(parse_cores(args.cores), command, cwd=args.cwd)
        if args.op == "status":
            print(json.dumps(status(), indent=1))
            return EXIT_OK
        print(json.dumps(topology(), indent=1))
        return EXIT_OK
    except NoRoom as exc:
        print(json.dumps({"no_room": str(exc)}), file=sys.stderr)
        return EXIT_HELD
    except Refused as exc:
        print(json.dumps({"refused": str(exc)}), file=sys.stderr)
        return EXIT_REFUSED
    except ValueError as exc:
        print(json.dumps({"usage": str(exc)}), file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
