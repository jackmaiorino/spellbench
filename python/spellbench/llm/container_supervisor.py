"""Trusted PID 1: isolate the bot's UID and expire its host-owned input lease."""

from __future__ import annotations

import argparse
import ctypes
import os
import signal
import subprocess
import sys
import threading
import time

from .. import wire


def child_identity() -> None:
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)
    os.umask(0o077)
    # Setting the UID clears permitted/effective capabilities. no-new-privileges
    # is inherited from Docker, so setuid files cannot restore them.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        os._exit(125)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--idle-timeout", type=int, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if os.getpid() != 1 or os.getuid() != 0 or not command or not 3 <= args.idle_timeout <= 120:
        return 125
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE: child cannot reopen controller pipes
        return 125
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "TMPDIR": "/tmp",
           "PYTHONPATH": "/app", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
    child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=None, env=env, preexec_fn=child_identity, start_new_session=True, cwd="/tmp")
    deadline = time.monotonic() + args.idle_timeout
    deadline_lock = threading.Lock()
    forwarded = threading.Event()

    def watch() -> None:
        while True:
            result = child.poll()
            if result is not None:
                forwarded.wait(1)
                os._exit(result if result >= 0 else 128 - result)
            with deadline_lock:
                expired = time.monotonic() >= deadline
            if expired:
                os._exit(124)  # PID 1 exit kills every process in this namespace
            time.sleep(0.1)

    def forward() -> None:
        try:
            while True:
                data = child.stdout.read1(64 * 1024)
                if not data:
                    return
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
        except OSError:
            os._exit(125)
        finally:
            forwarded.set()

    threading.Thread(target=watch, daemon=True).start()
    threading.Thread(target=forward, daemon=True).start()
    try:
        while True:
            line = wire.read_line(sys.stdin.buffer)
            if line is None:
                os._exit(0)
            frame = wire.strict_json_loads(line)
            if frame == {"channel": "heartbeat"}:
                pass
            elif set(frame) == {"channel", "payload"} and frame["channel"] == "protocol":
                payload = frame["payload"]
                if not isinstance(payload, str) or "\n" in payload or "\r" in payload:
                    os._exit(125)
                child.stdin.write(payload.encode("utf-8") + b"\n")
                child.stdin.flush()
            else:
                os._exit(125)
            with deadline_lock:
                deadline = time.monotonic() + args.idle_timeout
    except Exception:
        os._exit(125)


if __name__ == "__main__":
    raise SystemExit(main())
