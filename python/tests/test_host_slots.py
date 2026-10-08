"""Core slots beside the v1 host reservation: claims, queue, suspension under timed work, declarations."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

TOOLS = Path(__file__).parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import host_slots_v1 as slots

TOKEN = "0123456789abcdef0123456789abcdef"
CPUS = slots.current_affinity()
needs_two = pytest.mark.skipif(len(CPUS) < 2, reason="needs at least two usable CPUs")


@pytest.fixture
def host(tmp_path, monkeypatch):
    root = tmp_path / "host-lock"
    root.mkdir()
    monkeypatch.setenv(slots.ROOT_ENV, str(root))
    monkeypatch.setenv(slots.HOST_ENV, "TESTHOST")
    monkeypatch.setenv(slots.POLL_ENV, "0.1")
    monkeypatch.delenv(slots.TOKEN_ENV, raising=False)
    (root / "TESTHOST.slots").mkdir()
    slots.write_json(root / "TESTHOST.slots/config.json", {"cores": ",".join(map(str, reversed(CPUS)))})
    return root


def lock(root, token=TOKEN):
    (root / "TESTHOST.lock").write_text(json.dumps({
        "schema": slots.LOCK_SCHEMA, "token": token, "lane": "board", "work_id": "run-1",
        "acquired_at": "2026-10-07T00:00:00Z"}), encoding="utf-8")


def declare(root, cores, token=TOKEN):
    pid, creation = slots.self_identity()
    digest = slots.token_hash(token)
    slots.write_json(root / f"TESTHOST.slots/share-{digest[:16]}.json", {
        "schema": slots.SCHEMA, "token_sha256": digest, "cores": cores, "pid": pid, "creation_time": creation})


def script(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(f"import json, os, sys, time\nsys.path.insert(0, {str(TOOLS)!r})\nimport host_slots_v1 as h\n"
                    + body, encoding="utf-8")
    return str(path)


def cli(*args, **kwargs):
    return subprocess.Popen([sys.executable, str(TOOLS / "host_slots_v1.py"), *args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, **kwargs)


def wait_for(predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def counter(path):
    try:
        return int(Path(path).read_text() or 0)
    except (OSError, ValueError):
        return 0


def test_core_lists_round_trip():
    assert slots.parse_cores("0-3,8,11-10") == [0, 1, 2, 3, 8, 11, 10]
    assert slots.format_cores([8, 0, 1, 2, 5, 7]) == "0-2,5,7-8"
    with pytest.raises(ValueError):
        slots.parse_cores("a-b")


def test_available_respects_timed_declarations_claims_and_keep_free():
    config = {"cores": [7, 6, 5, 4, 3, 2, 1, 0], "keep_free": 2, "priority": "below_normal"}
    free = {"held": False, "cores": []}
    assert slots.available(config, free, []) == [7, 6, 5, 4, 3, 2]
    assert slots.available(config, {"held": True, "cores": None}, []) == []
    assert slots.available(config, {"held": True, "cores": [0, 1, 2, 3]}, []) == [7, 6, 5, 4]
    claims = [{"cores": [7, 6]}]
    assert slots.available(config, {"held": True, "cores": [0, 1, 2, 3]}, claims) == [5, 4]


def test_timed_state_is_the_whole_host_unless_a_live_declaration_says_otherwise(host):
    assert slots.timed_state()["held"] is False
    lock(host)
    state = slots.timed_state()
    assert state["held"] and state["cores"] is None and state["lane"] == "board"
    declare(host, [0])
    assert slots.timed_state()["cores"] == [0]
    declare(host, [0], token="f" * 32)  # a declaration for another reservation counts for nothing
    (host / f"TESTHOST.slots/share-{slots.token_hash(TOKEN)[:16]}.json").unlink()
    assert slots.timed_state()["cores"] is None
    (host / "TESTHOST.lock").write_text("not json")
    assert slots.timed_state() == {"held": True, "cores": None, "why": "lock record unreadable or incomplete"}


def test_declaration_whose_declarer_exited_reserves_the_whole_host(host, tmp_path):
    lock(host)
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    digest = slots.token_hash(TOKEN)
    slots.write_json(host / f"TESTHOST.slots/share-{digest[:16]}.json", {
        "token_sha256": digest, "cores": [0], "pid": gone.pid, "creation_time": 1})
    assert slots.timed_state()["cores"] is None


def test_run_pins_the_command_and_frees_its_claim(host, tmp_path):
    probe = script(tmp_path, "probe.py", "print(json.dumps({'affinity': h.current_affinity(), "
                                         "'claim': os.environ.get('HOST_SLOTS_CLAIM'), "
                                         "'cores': os.environ.get('HOST_SLOTS_CORES')}))\n")
    proc = cli("run", "--lane", "smoke", "--work-id", "w1", "--cores", "1", "--", sys.executable, probe)
    out, err = proc.communicate(timeout=60)
    assert proc.returncode == 0, err
    lines = [json.loads(line) for line in out.splitlines()]
    claimed, seen = lines[0], lines[1]
    assert seen["affinity"] == [int(claimed["cores"])] == [CPUS[-1]]  # highest-numbered first
    assert seen["claim"] == claimed["claimed"] and seen["cores"] == claimed["cores"]
    assert not list((host / "TESTHOST.slots").glob("claim-*.json"))


@pytest.mark.skipif(os.name == "nt", reason="nice values are POSIX")
def test_run_lowers_priority(host, tmp_path):
    probe = script(tmp_path, "nice.py", "print(os.getpriority(os.PRIO_PROCESS, 0))\n")
    out = subprocess.run([sys.executable, str(TOOLS / "host_slots_v1.py"), "run", "--lane", "l", "--work-id", "w",
                          "--cores", "1", "--", sys.executable, probe], capture_output=True, text=True, timeout=60)
    assert int(out.stdout.splitlines()[1]) >= 10


def test_no_room_without_wait_and_fifo_queue_with_wait(host, tmp_path):
    hold = script(tmp_path, "hold.py", "Path = __import__('pathlib').Path\nPath(sys.argv[1]).write_text('up')\n"
                                       "while not Path(sys.argv[2]).exists(): time.sleep(0.05)\n")
    up, release = tmp_path / "up", tmp_path / "release"
    first = cli("run", "--lane", "l", "--work-id", "first", "--cores", str(len(CPUS)), "--",
                sys.executable, hold, str(up), str(release))
    try:
        assert wait_for(up.exists)
        refused = subprocess.run([sys.executable, str(TOOLS / "host_slots_v1.py"), "run", "--lane", "l",
                                  "--work-id", "second", "--cores", "1", "--", sys.executable, "-c", "pass"],
                                 capture_output=True, text=True, timeout=60)
        assert refused.returncode == slots.EXIT_HELD
        mark = script(tmp_path, "mark.py", "open(sys.argv[1], 'a').write(sys.argv[2] + '\\n')\n")
        order = tmp_path / "order"
        waiters = []
        for name in ("a", "b"):
            waiters.append(cli("run", "--wait", "--lane", "l", "--work-id", name, "--cores", "1", "--",
                               sys.executable, mark, str(order), name))
            assert wait_for(lambda n=len(waiters): len(list((host / "TESTHOST.slots").glob("queue-*.json"))) == n)
        status = slots.status()
        assert [t["work_id"] for t in status["queue"]] == ["a", "b"] and status["free"] == ""
        release.write_text("go")
        for waiter in waiters:
            assert waiter.wait(timeout=60) == 0
        assert order.read_text().split() == ["a", "b"]
    finally:
        release.write_text("go")
        first.wait(timeout=60)


def test_claims_suspend_while_timed_work_leaves_no_room(host, tmp_path):
    count = tmp_path / "count"
    ticker = script(tmp_path, "tick.py", "n = 0\nwhile True:\n    n += 1\n    open(sys.argv[1], 'w').write(str(n))\n"
                                         "    time.sleep(0.02)\n")
    runner = cli("run", "--lane", "l", "--work-id", "tick", "--cores", "1", "--", sys.executable, ticker, str(count))
    try:
        assert wait_for(lambda: counter(count) > 5)
        lock(host)  # no declaration: the whole host
        assert wait_for(lambda: slots.status()["claims"][0]["state"] == "suspended")
        time.sleep(0.5)
        frozen = counter(count)
        time.sleep(1.0)
        assert counter(count) == frozen
        claimed = slots.status()["claims"][0]["cores"]
        others = [cpu for cpu in CPUS if cpu not in claimed]
        if others:  # a declaration that leaves the claim's core free lets it resume
            declare(host, others[:1])
            assert wait_for(lambda: counter(count) > frozen + 5)
            declare(host, claimed)  # an overlapping one suspends it again
            assert wait_for(lambda: slots.status()["claims"][0]["state"] == "suspended")
            time.sleep(0.5)
            frozen = counter(count)
        (host / "TESTHOST.lock").unlink()
        assert wait_for(lambda: counter(count) > frozen + 5)
    finally:
        runner.terminate()
        runner.wait(timeout=60)
    assert wait_for(lambda: not list((host / "TESTHOST.slots").glob("claim-*.json")) or slots.status()["claims"] == [])
    settled = counter(count)
    time.sleep(0.5)
    assert counter(count) == settled  # stopping the runner ended its whole tree


@needs_two
def test_timed_declares_pins_and_waits_for_overlapping_claims(host, tmp_path, monkeypatch):
    lock(host)
    probe = script(tmp_path, "probe.py", "print(json.dumps({'affinity': h.current_affinity(), "
                                         "'timed': h.timed_state()['cores']}))\n")
    env = dict(os.environ, **{slots.TOKEN_ENV: TOKEN})
    proc = cli("timed", "--cores", str(CPUS[0]), "--", sys.executable, probe, env=env)
    out, err = proc.communicate(timeout=60)
    assert proc.returncode == 0, err
    seen = json.loads(out)
    assert seen == {"affinity": [CPUS[0]], "timed": [CPUS[0]]}
    assert slots.timed_state()["cores"] is None  # the declaration ends with the command
    wrong = cli("timed", "--cores", str(CPUS[0]), "--", sys.executable, "-c", "pass",
                env=dict(os.environ, **{slots.TOKEN_ENV: "f" * 32}))
    assert wrong.wait(timeout=60) == slots.EXIT_REFUSED


def test_dead_claims_and_tickets_are_reaped(host):
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    for name in ("claim-" + "a" * 32, "queue-00000000000000000001-" + "b" * 32):
        slots.write_json(host / f"TESTHOST.slots/{name}.json", {
            "id": name[-32:], "pid": gone.pid, "creation_time": 1, "cores": [CPUS[0]], "cores_wanted": 1})
    status = slots.status()
    assert status["claims"] == [] and status["queue"] == []
    assert len(slots.parse_cores(status["free"])) == len(CPUS)


def test_topology_lists_every_cpu_once():
    rows = slots.topology()
    listed = [cpu for row in rows for cpu in slots.parse_cores(row["cpus"])]
    assert sorted(listed) == list(range(slots.cpu_total()))


@pytest.mark.skipif(os.name != "nt", reason="Windows affinity")
def test_windows_usable_cpus_follow_a_claims_affinity(host, tmp_path):
    probe = script(tmp_path, "cpus.py", f"sys.path.insert(0, {str(Path(__file__).parents[1])!r})\n"
                                        "from spellbench.arena.machine import usable_cpus\nprint(usable_cpus())\n")
    out = subprocess.run([sys.executable, str(TOOLS / "host_slots_v1.py"), "run", "--lane", "l", "--work-id", "w",
                          "--cores", "1", "--", sys.executable, probe], capture_output=True, text=True, timeout=60)
    assert out.stdout.splitlines()[1] == "1", out.stderr
