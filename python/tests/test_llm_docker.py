"""Actual containers: authority boundaries, broker routing and every cleanup path."""

from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import time

import pytest

from spellbench import wire
from spellbench.arena.config import BotSpec
from spellbench.arena.drivers import SubprocessDriver
from spellbench.errors import TransportError
from spellbench.host.agent_process import AgentProcess
from spellbench.host.game import play_game
from spellbench.llm.agent import AgentConfig
from spellbench.llm.broker import BrokerLimits, BrokerPeer, BrokerSession, serve_broker
from spellbench.llm.docker_peer import DockerPeer
from spellbench.llm.provider import ChatCompletionsProvider, ProviderConfig
from spellbench.llm.run_budget import RunBudget

from test_host_game import Seat, real_engine, setup
from test_llm_http import endpoint  # actual loopback HTTP fixture

pytestmark = pytest.mark.skipif(os.environ.get("SPELLBENCH_RUN_DOCKER_TESTS") != "1",
                                reason="requires an explicitly enabled Docker runtime")


@pytest.fixture
def image():
    value = os.environ.get("SPELLBENCH_LLM_DOCKER_IMAGE")
    assert value, "enabled container checks require a built, immutable image"
    assert subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    return value


def removed(name: str, timeout: float = 12) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(["docker", "container", "inspect", name], capture_output=True, text=True)
        if result.returncode != 0 and "No such" in result.stderr:
            return
        time.sleep(0.2)
    pytest.fail("the owned container survived teardown")


def test_hosted_arena_entry_hello_needs_no_credentials_or_inference(image, tmp_path):
    budget_path = tmp_path / "run.sqlite3"
    RunBudget.create(budget_path, model="test-model", requests=2, tokens=10000, wall_seconds=60)
    logs = tmp_path / "logs"
    command = [sys.executable, "-m", "spellbench.llm.hosted", "--model", "test-model", "--image", image,
               "--run-budget", str(budget_path), "--log-dir", str(logs),
               "--credentials", str(tmp_path / "does-not-exist.credentials"), "--renew-profile-before-game",
               "--max-run-requests", "2", "--max-run-tokens", "10000", "--max-run-wall-seconds", "60"]
    agent = AgentProcess(command, startup_timeout_s=30)
    try:
        assert agent.hello().bot.name == "llm-test-model"
    finally:
        agent.close()
    metadata = json.loads(next(logs.glob("broker-*.jsonl")).read_text().splitlines()[0])
    removed(metadata["provider"]["container_name"], timeout=40)
    assert RunBudget(budget_path, model="test-model").summary()["requests"] == 0


def test_real_child_cannot_reach_host_network_credentials_files_or_controller(image, tmp_path, monkeypatch):
    secret = tmp_path / "host.credentials"
    secret.write_text("host-only-probe")
    monkeypatch.setenv("SPELLBENCH_SECRET_PROBE", "host-only-probe")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    # A positive control: this endpoint and file exist on the host.
    with socket.create_connection(("127.0.0.1", port), timeout=1):
        pass
    code = r'''
import errno, json, os, socket, sys, time
def denied(address):
    try:
        with socket.create_connection(address, timeout=1):
            return False
    except OSError:
        return True
def protected(path):
    try:
        with open(path, 'rb'):
            return False
    except (PermissionError, FileNotFoundError):
        return True
status = dict(line.split(':', 1) for line in open('/proc/self/status') if ':' in line)
print(json.dumps({'uid': os.getuid(), 'caps': int(status['CapEff'].strip(), 16),
                  'no_new_privileges': status['NoNewPrivs'].strip(),
                  'secret_env': os.environ.get('SPELLBENCH_SECRET_PROBE'),
                  'host_file_denied': protected(sys.argv[1]),
                  'controller_denied': protected('/proc/1/fd/0'),
                  'docker_socket_absent': not os.path.exists('/var/run/docker.sock'),
                  'host_listener_denied': denied(('127.0.0.1', int(sys.argv[2]))),
                  'external_network_denied': denied(('1.1.1.1', 443)),
                  'root_readonly': bool(os.statvfs('/').f_flag & os.ST_RDONLY)}), flush=True)
time.sleep(60)
'''
    peer = DockerPeer(image, ["python", "-c", code, str(secret), str(port)], timeout_s=10)
    try:
        result = wire.strict_json_loads(peer.read_line())
        assert result == {"uid": 65534, "caps": 0, "no_new_privileges": "1", "secret_env": None,
                          "host_file_denied": True, "controller_denied": True, "docker_socket_absent": True,
                          "host_listener_denied": True, "external_network_denied": True, "root_readonly": True}
    finally:
        listener.close()
        peer.close()
    removed(peer.name)


def test_complete_v2_host_game_routes_inference_outside_container(image, endpoint):
    settings = ProviderConfig(model="test-model", base_url=endpoint.url + "/v1", api_key="host-only-secret")
    log = io.StringIO()
    owned = []

    def factory():
        peer = DockerPeer(image, ["python", "-m", "spellbench.llm", "--broker-stdio", "--model", "test-model",
                                 "--history-decisions", "1", "--max-calls-per-game", "2", "--log-dir", "/tmp/llm"],
                          timeout_s=10)
        owned.append(peer.name)
        session = BrokerSession(peer, ChatCompletionsProvider(settings), settings=settings.public_settings(),
                                max_completion_tokens=1024, log=log, config=AgentConfig(max_calls_per_game=2),
                                limits=BrokerLimits(max_calls_total=2, max_tokens_total=50000))
        return AgentProcess(peer=BrokerPeer(session), startup_timeout_s=10)

    engine = real_engine()
    seat = SubprocessDriver(BotSpec(name="llm-test-model", version="0.1.0", type="subprocess",
                                   command=("unused-injected-peer",)), startup_ms=10000, agent_factory=factory)
    try:
        result = play_game(setup(), engine=engine, seats={"p0": seat, "p1": Seat()})
        assert result.classification == "natural"
        assert result.decisions_checked == 4
    finally:
        seat.close()
        engine.close()
    assert len(endpoint.received) == 2
    assert all(call["authorization"] == "Bearer host-only-secret" for call in endpoint.received)
    assert "host-only-secret" not in log.getvalue()
    assert len([event for line in log.getvalue().splitlines()
                if (event := json.loads(line)).get("event") == "inference"]) == 2
    for name in owned:
        removed(name)


def test_child_crash_removes_container(image):
    peer = DockerPeer(image, ["python", "-c", "import os; os._exit(7)"], timeout_s=5)
    try:
        with pytest.raises(TransportError):
            peer.read_line()
        removed(peer.name)
    finally:
        peer.close()


def test_broker_timeout_removes_container(image):
    peer = DockerPeer(image, ["python", "-c", "import time; time.sleep(60)"], timeout_s=5)
    session = BrokerSession(peer, None, settings={"model": "unused"}, max_completion_tokens=32,
                            log=io.StringIO(), limits=BrokerLimits(startup_ms=500))
    incoming = io.BytesIO(wire.canonical_json_line({"protocol": "spellbench/v2", "request_id": "h",
                                                   "request_type": "hello", "protocol_minor": 0}))
    assert serve_broker(session, stdin=incoming, stdout=io.BytesIO()) == 1
    removed(peer.name)


def test_stopped_heartbeat_removes_container_even_with_stdin_open(image):
    peer = DockerPeer(image, ["python", "-c", "import time; print('ready', flush=True); time.sleep(60)"],
                      timeout_s=10, idle_timeout_s=3)
    try:
        assert peer.read_line().strip() == b"ready"
        peer._stopped.set()
        peer._heartbeat.join(timeout=2)
        removed(peer.name)
    finally:
        peer.close()


def test_killed_host_does_not_leave_container_or_child_descendants(image):
    code = '''
import sys, time
from spellbench.llm.docker_peer import DockerPeer
peer = DockerPeer(sys.argv[1], ['python', '-c',
    "import subprocess, time; subprocess.Popen(['sleep', '60']); print('ready', flush=True); time.sleep(60)"],
    timeout_s=10, idle_timeout_s=3)
assert peer.read_line().strip() == b'ready'
print(peer.name, flush=True)
time.sleep(60)
'''
    host = subprocess.Popen([sys.executable, "-c", code, image], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        name = host.stdout.readline().strip()
        assert name.startswith("spellbench-llm-")
        host.kill()  # simulate a hard arena kill; no Python finally block runs
        host.wait(timeout=5)
        removed(name)
    finally:
        if host.poll() is None:
            host.kill()
            host.wait(timeout=5)

