"""Core slots beside the host reservation (v1): untimed work uses the cores timed work leaves free.

host_reservation_v1.py (mtg-kernel python/tools) reserves a whole host with
one lock file, <root>/<HOST>.lock. This module never writes that lock and
never changes what it means. It keeps its own records beside it, under
<root>/<HOST>.slots/:

- Timed work that holds the v1 reservation may give back the cores it does
  not need. `timed --cores 0-7 -- CMD`, run inside the v1 supervisor (so
  MTG_HOST_RESERVATION_TOKEN names the held lock), pins CMD and all its
  descendants to those cores. While CMD runs, it declares them in
  share-<token hash>.json. Without that declaration, a held v1 lock still
  reserves the whole host, exactly as before.
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
- `status` prints the timed reservation (lane, work and declared cores),
  the claims, the queue and the free cores. It never prints the token.
  `topology` lists the logical CPUs with each core's efficiency class:
  hybrid Intel P cores rank above E cores.

Optional per-host config, <root>/<HOST>.slots/config.json:
  {"cores": "23-0", "keep_free": 0, "priority": "below_normal"}
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
  run --lane L --work-id W --cores N [--wait] [--wait-timeout S] [--priority P] [--id ID] [--cwd DIR] -- CMD...
  submit --log FILE (same options as run) -- CMD...
  timed --cores SPEC [--cwd DIR] -- CMD...
  status
  topology
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
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "spellbench-host-slots/v1"
LOCK_SCHEMA = "mtg-host-reservation/v1"
TOKEN_ENV = "MTG_HOST_RESERVATION_TOKEN"
ROOT_ENV = "HOST_SLOTS_ROOT"
HOST_ENV = "HOST_SLOTS_HOST"
POLL_ENV = "HOST_SLOTS_POLL_SECONDS"
CLAIM_ENV = "HOST_SLOTS_CLAIM"
CORES_ENV = "HOST_SLOTS_CORES"
CANONICAL_ROOT = "C:/mtg-node/host-lock" if os.name == "nt" else "/mnt/c/mtg-node/host-lock"
PRIORITIES = ("normal", "below_normal", "idle")
EXIT_OK, EXIT_USAGE, EXIT_HELD, EXIT_REFUSED = 0, 2, 3, 6
MUTEX_TIMEOUT_SECONDS = 30.0
MUTEX_STALE_SECONDS = 30.0
TIMED_VACATE_SECONDS = 60.0


class NoRoom(Exception):
    """Not enough free cores (or a queue ahead) and not waiting."""


class Refused(Exception):
    """A declaration or claim was refused."""


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


def cpu_total() -> int:
    return os.cpu_count() or 1


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
        return sorted(os.sched_getaffinity(0))


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
    """The host's slot config with defaults: cores (preference order), keep_free, priority."""
    raw = read_json(slots_dir() / "config.json") or {}
    total = cpu_total()
    cores = parse_cores(str(raw["cores"])) if raw.get("cores") is not None else list(range(total - 1, -1, -1))
    if any(core >= total for core in cores):
        raise ValueError(f"config cores {format_cores(cores)} exceed this host's {total} logical CPUs")
    keep_free = int(raw.get("keep_free", 0))
    priority = raw.get("priority", "below_normal")
    if priority not in PRIORITIES or not 0 <= keep_free < len(cores):
        raise ValueError(f"bad slot config {raw}")
    return {"cores": cores, "keep_free": keep_free, "priority": priority}


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
                if self._stale():
                    stale = self.path.with_name(f".mutex.stale-{uuid.uuid4().hex}")
                    try:
                        os.rename(self.path, stale)
                        shutil.rmtree(stale, ignore_errors=True)
                    except OSError:
                        pass
                    continue
                if time.monotonic() > deadline:
                    raise TimeoutError(f"slot mutex {self.path} stayed held for {MUTEX_TIMEOUT_SECONDS} s")
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


def timed_state() -> dict:
    """The v1 reservation as slots see it. held=False: free. cores=None: the whole host.
    An unreadable lock, a missing declaration or one whose declarer is not alive all mean
    the whole host."""
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
    if share is None:
        return {**out, "why": "no core declaration: the whole host is reserved"}
    if share.get("token_sha256") != digest or process_state(share.get("pid"), share.get("creation_time")) != "alive":
        return {**out, "why": "core declaration is not live: the whole host is reserved"}
    return {**out, "cores": sorted(share["cores"]), "why": "timed work declared its cores"}


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


def available(config: dict, timed: dict, claims: list[dict]) -> list[int]:
    """Cores a new claim may take now, in preference order."""
    if timed["held"] and timed["cores"] is None:
        return []
    blocked = set(timed["cores"]) if timed["held"] else set()
    allowed = config["cores"]
    used = {core for claim in claims for core in claim["cores"]}
    room = len(allowed) - config["keep_free"] - len(used & set(allowed))
    free = [core for core in allowed if core not in blocked and core not in used]
    return free[:max(0, room)]


def conflicts(cores) -> bool:
    """True when held timed work leaves these cores no room (no declaration, or an overlapping one)."""
    timed = timed_state()
    return timed["held"] and (timed["cores"] is None or bool(set(timed["cores"]) & set(cores)))


# ---------------------------------------------------------------- containment


class Tree:
    """The pinned process tree of one claim or declaration."""

    def __init__(self, cores, priority: str | None):
        self.cores = sorted(cores)
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
            if not _AssignProcessToJobObject(job, _GetCurrentProcess()):
                err = ctypes.get_last_error()
                _CloseHandle(job)
                raise OSError(err, "AssignProcessToJobObject failed")
            self.job = job
        else:
            os.sched_setaffinity(0, self.cores)
            if priority is not None:
                floor = {"normal": 0, "below_normal": 10, "idle": 19}[priority]
                current = os.getpriority(os.PRIO_PROCESS, 0)
                if current < floor:
                    os.setpriority(os.PRIO_PROCESS, 0, floor)

    def start(self, command: list[str], cwd: str | None, env: dict) -> subprocess.Popen:
        self.child = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=os.name != "nt")
        return self.child

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

    def set_suspended(self, suspend: bool) -> None:
        if os.name == "nt":
            if suspend:
                for _ in range(2):  # a second pass catches a process created during the first
                    for pid in self.members():
                        if pid not in self.suspended and _suspend_pid(pid, True):
                            self.suspended.add(pid)
            else:
                for pid in sorted(self.suspended):
                    _suspend_pid(pid, False)
                self.suspended.clear()
        elif self.child is not None:
            try:
                os.killpg(self.child.pid, signal.SIGSTOP if suspend else signal.SIGCONT)
            except ProcessLookupError:
                pass
            self.suspended = {self.child.pid} if suspend else set()

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


def run(lane: str, work_id: str, cores_wanted: int, command: list[str], *, wait: bool = False,
        wait_timeout: float | None = None, priority: str | None = None, claim_id: str | None = None,
        cwd: str | None = None, on_claim=None) -> int:
    """Claim cores (queueing with wait), run command pinned to them, free them when its tree ends."""
    if not (lane and work_id and command):
        raise ValueError("lane, work_id and a command are required")
    config = load_config()
    priority = priority or config["priority"]
    if priority not in PRIORITIES:
        raise ValueError(f"priority must be one of {PRIORITIES}")
    if not 1 <= cores_wanted <= len(config["cores"]) - config["keep_free"]:
        raise ValueError(f"{cores_wanted} cores: this host hands out 1 to "
                         f"{len(config['cores']) - config['keep_free']}")
    claim_id = claim_id or uuid.uuid4().hex
    if not re.fullmatch(r"[0-9a-f]{32}", claim_id):
        raise ValueError("claim id must be 32 lowercase hex digits")
    pid, creation = self_identity()
    base = {"schema": SCHEMA, "id": claim_id, "lane": lane, "work_id": work_id, "pid": pid, "creation_time": creation}
    ticket = slots_dir() / f"queue-{time.time_ns():020d}-{claim_id}.json"
    claim = slots_dir() / f"claim-{claim_id}.json"
    deadline = None if wait_timeout is None else time.monotonic() + wait_timeout
    with Mutex():
        write_json(ticket, {**base, "cores_wanted": cores_wanted, "enqueued_at": now_utc()})
    try:
        while True:
            with Mutex():
                tickets = live_tickets()
                if tickets and tickets[0]["id"] == claim_id:
                    room = available(config, timed_state(), live_claims())
                    if len(room) >= cores_wanted:
                        cores = sorted(room[:cores_wanted])
                        write_json(claim, {**base, "cores": cores, "priority": priority, "state": "running",
                                           "acquired_at": now_utc()})
                        ticket.unlink()
                        break
            if not wait:
                raise NoRoom(f"{host()} has no {cores_wanted} free cores for {lane}/{work_id} now")
            if deadline is not None and time.monotonic() > deadline:
                raise NoRoom(f"{host()} had no {cores_wanted} free cores within {wait_timeout} s")
            time.sleep(poll_seconds())
    except BaseException:
        with Mutex():
            try:
                ticket.unlink()
            except OSError:
                pass
        raise
    try:
        if on_claim is not None:
            on_claim({"id": claim_id, "cores": cores})
        return _run_claimed(claim, cores, priority, command, cwd, claim_id)
    finally:
        with Mutex():
            try:
                claim.unlink()
            except OSError:
                pass


def _set_state(claim: Path, state: str) -> None:
    with Mutex():
        record = read_json(claim)
        if record is not None:
            write_json(claim, {**record, "state": state, "state_at": now_utc()})


def _run_claimed(claim: Path, cores: list[int], priority: str, command: list[str], cwd: str | None,
                 claim_id: str) -> int:
    tree = Tree(cores, priority)
    env = dict(os.environ, **{CLAIM_ENV: claim_id, CORES_ENV: format_cores(cores)})
    if conflicts(cores):  # never start work on cores timed work holds
        _set_state(claim, "suspended")
        while conflicts(cores):
            time.sleep(poll_seconds())
        _set_state(claim, "running")
    suspended = False
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}

    def stop(signum, _frame):
        tree.kill()
        raise SystemExit(128 + signum)

    for sig in previous:
        signal.signal(sig, stop)
    try:
        child = tree.start(command, cwd, env)
        code = None
        while True:
            if code is None:
                try:
                    code = child.wait(timeout=poll_seconds())
                except subprocess.TimeoutExpired:
                    pass
            if code is not None and not tree.members():
                break
            if code is not None:
                time.sleep(poll_seconds())
            conflict = conflicts(cores)
            if conflict != suspended:
                tree.set_suspended(conflict)
                suspended = conflict
                _set_state(claim, "suspended" if conflict else "running")
        return code
    finally:
        if suspended:
            tree.set_suspended(False)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


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
    keep = ("id", "lane", "work_id", "pid", "cores", "priority", "state", "acquired_at")
    return {
        "host": host(), "root": str(root_dir()), "logical_cpus": cpu_total(),
        "config": {**config, "cores": format_cores(config["cores"])},
        "timed": {k: v for k, v in timed.items() if k != "token_sha256"},
        "claims": [{k: c.get(k) for k in keep} for c in claims],
        "queue": [{k: t.get(k) for k in ("id", "lane", "work_id", "pid", "cores_wanted", "enqueued_at")} for t in tickets],
        "free": format_cores(available(config, timed, claims)) or "",
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
    seen = set()
    for cpu in range(cpu_total()):
        siblings = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology/thread_siblings_list")
        group = parse_cores(siblings.read_text().strip()) if siblings.exists() else [cpu]
        if tuple(group) in seen:
            continue
        seen.add(tuple(group))
        rows.append({"cpus": format_cores(group), "efficiency_class": hybrid.get(cpu), "smt": len(group) > 1})
    return rows


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    command: list[str] = []
    if "--" in argv:
        split = argv.index("--")
        argv, command = argv[:split], argv[split + 1:]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="op", required=True)
    for op in ("run", "submit"):
        p = sub.add_parser(op)
        p.add_argument("--lane", required=True)
        p.add_argument("--work-id", required=True)
        p.add_argument("--cores", type=int, required=True)
        p.add_argument("--priority", choices=PRIORITIES)
        p.add_argument("--wait-timeout", type=float)
        p.add_argument("--cwd")
        if op == "run":
            p.add_argument("--wait", action="store_true")
            p.add_argument("--id")
        else:
            p.add_argument("--log", required=True)
    p = sub.add_parser("timed")
    p.add_argument("--cores", required=True)
    p.add_argument("--cwd")
    sub.add_parser("status")
    sub.add_parser("topology")
    args = parser.parse_args(argv)
    try:
        if args.op in ("run", "submit", "timed") and not command:
            parser.error(f"{args.op} needs -- COMMAND...")
        if args.op == "run":
            def announce(claimed):
                print(json.dumps({"claimed": claimed["id"], "cores": format_cores(claimed["cores"])}), flush=True)
            code = run(args.lane, args.work_id, args.cores, command, wait=args.wait, wait_timeout=args.wait_timeout,
                       priority=args.priority, claim_id=args.id, cwd=args.cwd, on_claim=announce)
            print(json.dumps({"exit_code": code}), flush=True)
            return code
        if args.op == "submit":
            options = ["--lane", args.lane, "--work-id", args.work_id, "--cores", str(args.cores)]
            for flag, value in (("--priority", args.priority), ("--wait-timeout", args.wait_timeout),
                                ("--cwd", args.cwd)):
                if value is not None:
                    options += [flag, str(value)]
            print(json.dumps(submit(options, command, args.log)))
            return EXIT_OK
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
