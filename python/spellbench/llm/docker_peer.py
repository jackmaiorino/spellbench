"""A confined Docker child for the host-owned inference broker.

Only an immutable, already built image is accepted. No host paths, environment,
credentials or Docker socket are mounted into the container. This binding does
not change the arena's admission allowlist.
"""

from __future__ import annotations

import re
import subprocess
import threading
import uuid
from typing import Sequence

from .. import wire
from ..errors import TransportError


class DockerPeer:
    def __init__(self, image: str, command: Sequence[str], *, docker: str = "docker",
                 timeout_s: float = 20, idle_timeout_s: int = 30) -> None:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
            raise ValueError("an immutable local Docker image ID is required")
        if not command or any(not isinstance(arg, str) or not arg for arg in command):
            raise ValueError("a nonempty child argv is required")
        if type(idle_timeout_s) is not int or not 3 <= idle_timeout_s <= 120:
            raise ValueError("idle timeout must be 3-120 seconds")
        self.docker = docker
        self.name = "spellbench-llm-" + uuid.uuid4().hex
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._closed = False
        argv = [docker, "run", "--pull", "never", "--rm", "--interactive", "--name", self.name,
                "--label", "spellbench.role=llm-child", "--network", "none", "--read-only",
                "--cap-drop", "ALL", "--cap-add", "SETUID", "--cap-add", "SETGID",
                "--security-opt", "no-new-privileges", "--pids-limit", "64", "--memory", "512m",
                "--memory-swap", "512m", "--cpus", "1", "--ulimit", "nofile=128:128",
                "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777", "--workdir", "/tmp",
                "--entrypoint", "python", image, "-m", "spellbench.llm.container_supervisor",
                "--idle-timeout", str(idle_timeout_s), "--", *command]
        # Docker's own CLI can use its host configuration. None of that
        # environment is forwarded to the container (there are no -e flags).
        self._peer = wire.SubprocessPeer(argv, timeout_s=timeout_s)
        self._heartbeat = threading.Thread(target=self._heartbeats, args=(idle_timeout_s / 3,), daemon=True)
        self._heartbeat.start()

    def _send(self, value: dict) -> None:
        with self._lock:
            self._peer.write_line(wire.canonical_json_dumps(value))

    def _heartbeats(self, interval: float) -> None:
        while not self._stopped.wait(interval):
            try:
                self._send({"channel": "heartbeat"})
            except (TransportError, OSError):
                return

    def write_line(self, payload: bytes) -> None:
        self._send({"channel": "protocol", "payload": payload.decode("utf-8")})

    def read_line(self) -> bytes:
        return self._peer.read_line()

    def set_timeout(self, timeout_s: float | None) -> None:
        self._peer.set_timeout(timeout_s)

    def stderr_text(self) -> str:
        return self._peer.stderr_text()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stopped.set()
        # Removing this named container first also releases a blocked Docker
        # stdin writer. Host death is covered independently by the in-container
        # lease; killing a Docker CLI alone is not assumed to remove a container.
        try:
            subprocess.run([self.docker, "container", "rm", "--force", self.name],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
        finally:
            self._peer.close()
            self._heartbeat.join(timeout=2)

