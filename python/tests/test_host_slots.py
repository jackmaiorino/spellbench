"""Core slots beside the v1 host reservation: claims, queue, suspension under timed work, declarations."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock, patch

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import host_slots_v1 as slots

TOKEN = "0123456789abcdef0123456789abcdef"
CPUS = slots.current_affinity()
needs_two = pytest.mark.skipif(len(CPUS) < 2, reason="needs at least two usable CPUs")
needs_two_ut = unittest.skipIf(len(CPUS) < 2, "needs at least two usable CPUs")
needs_three = unittest.skipIf(len(CPUS) < 3, "needs at least three usable CPUs")


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


def lock(root, token=TOKEN, cores=None):
    record = {"schema": slots.LOCK_SCHEMA, "token": token, "lane": "board", "work_id": "run-1",
              "acquired_at": "2026-10-07T00:00:00Z"}
    if cores is not None:
        record["cores"] = cores
    (root / "TESTHOST.lock").write_text(json.dumps(record), encoding="utf-8")


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


def test_cores_recorded_at_acquire_count_before_and_after_the_timed_declaration(host):
    lock(host, cores=[0, 1])
    state = slots.timed_state()
    assert state["held"] and state["cores"] == [0, 1] and "acquired" in state["why"]
    assert slots.conflicts([1]) and not slots.conflicts([2])
    config = {"cores": [3, 2, 1, 0], "keep_free": 0, "priority": "below_normal"}
    assert slots.available(config, state, []) == [3, 2]
    declare(host, [1])  # a live declaration by timed wins while it lasts
    assert slots.timed_state()["cores"] == [1]
    (host / f"TESTHOST.slots/share-{slots.token_hash(TOKEN)[:16]}.json").unlink()
    assert slots.timed_state()["cores"] == [0, 1]  # after timed ends: the recorded cores, not the whole host
    for bad in ([], [-1], [0, 0], ["0"], [True], "0-1"):
        lock(host, cores=bad)
        assert slots.timed_state()["cores"] is None, bad


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
            # Each waiter wants every core, so b cannot start until a ends and the
            # file order is the admission order rather than a race between them.
            waiters.append(cli("run", "--wait", "--lane", "l", "--work-id", name, "--cores", str(len(CPUS)), "--",
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
    ticker_info = tmp_path / "ticker.json"
    ticker = script(
        tmp_path, "tick.py",
        "from pathlib import Path\n"
        "pid, creation = h.self_identity()\n"
        "h.write_json(Path(sys.argv[2]), {'pid': pid, 'creation_time': creation})\n"
        "n = 0\nwhile True:\n    n += 1\n    open(sys.argv[1], 'w').write(str(n))\n"
        "    time.sleep(0.02)\n",
    )
    runner = cli("run", "--lane", "l", "--work-id", "tick", "--cores", "1", "--priority", "normal", "--",
                 sys.executable, ticker, str(count), str(ticker_info))
    claim_owner = None
    child_owner = None

    def claim_record():
        claims, _ = slots._peek()
        return claims[0] if claims else None

    try:
        assert wait_for(lambda: counter(count) > 5)
        assert wait_for(lambda: claim_record() is not None and slots.read_json(ticker_info) is not None)
        initial = claim_record()
        child_record = slots.read_json(ticker_info)
        assert initial is not None and child_record is not None
        claim_owner = (initial["pid"], initial["creation_time"])
        child_owner = (child_record["pid"], child_record["creation_time"])
        lock(host)  # no declaration: the whole host
        assert wait_for(lambda: (claim_record() or {}).get("state") == "suspended")
        time.sleep(0.5)
        frozen = counter(count)
        time.sleep(1.0)
        assert counter(count) == frozen
        claimed = initial["cores"]
        others = [cpu for cpu in CPUS if cpu not in claimed]
        if others:  # a declaration that leaves the claim's core free lets it resume
            declare(host, others[:1])
            assert wait_for(lambda: counter(count) > frozen + 5)
            declare(host, claimed)  # an overlapping one suspends it again
            assert wait_for(lambda: (claim_record() or {}).get("state") == "suspended")
            time.sleep(0.5)
            frozen = counter(count)
        (host / "TESTHOST.lock").unlink()
        assert wait_for(lambda: counter(count) > frozen + 5)
    finally:
        runner.terminate()
        runner.wait(timeout=60)
        if claim_owner is not None:
            wait_for(lambda: slots.process_state(*claim_owner) == "absent", timeout=60)
        if child_owner is not None:
            wait_for(lambda: slots.process_state(*child_owner) == "absent", timeout=60)
    assert claim_owner is not None and slots.process_state(*claim_owner) == "absent"
    assert child_owner is not None and slots.process_state(*child_owner) == "absent"
    assert slots._peek()[0] == []
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


# Backfill policy (mirrors mtg-kernel python/tests/test_host_slots_v1.py BackfillPolicyTests)

def config8(keep_free=0):
    return {"cores": [7, 6, 5, 4, 3, 2, 1, 0], "keep_free": keep_free, "priority": "below_normal"}


FREE = {"held": False, "cores": []}


def ticket(name, wanted, max_seconds=60.0, **extra):
    record = {"id": name, "cores_wanted": wanted, "background": False, **extra}
    if max_seconds is not None:
        record["max_seconds"] = max_seconds
    return record


def admits(config, timed, claims, tickets, claim_id):
    """backfill_admits with the head queued under this config, as run() records it."""
    tickets = [{**tickets[0], "config_sha256": slots.config_digest(config)}, *tickets[1:]]
    return slots.backfill_admits(config, timed, claims, tickets, claim_id)


def test_head_with_room_is_never_backfilled_around():
    # the head fits now: a backfill that takes its room is refused (the empty release set)
    claims = [{"cores": [7, 6, 5, 4]}]
    assert admits(config8(), FREE, claims, [ticket("head", 4, None), ticket("t", 2)], "t") is None
    assert admits(config8(), FREE, [], [ticket("head", 4, None)], "head") is None


def test_request_without_declared_limit_never_backfills():
    claims = [{"cores": [7, 6, 5, 4, 3, 2]}]
    tickets = [ticket("head", 4, None), ticket("t", 2, None)]
    assert admits(config8(), FREE, claims, tickets, "t") is None
    for bad in (0, -1, True, float("inf"), float("nan"), "60", 1e300, slots.BACKFILL_MAX_SECONDS + 1):
        assert slots._backfill_cores(config8(), FREE, claims, tickets[0], ticket("t", 2, bad)) is None


def test_one_releasing_claim_admits_a_backfill_into_free_cores():
    # the 18:17 case scaled down: one large claim, two free cores, the head wants four
    claims = [{"cores": [7, 6, 5, 4, 3, 2]}]
    tickets = [ticket("head", 4, None), ticket("t", 2)]
    assert admits(config8(), FREE, claims, tickets, "t") == [0, 1]


def test_a_release_subset_that_the_backfill_would_delay_refuses():
    # releasing either claim alone lets the head start (5 >= 4) without the backfill, not with it (3 < 4)
    claims = [{"cores": [7, 6, 5]}, {"cores": [4, 3, 2]}]
    tickets = [ticket("head", 4, None), ticket("t", 2)]
    assert admits(config8(), FREE, claims, tickets, "t") is None
    assert admits(config8(), FREE, claims, [tickets[0], ticket("t", 1)], "t") == [1]


def test_existing_backfills_count_cumulatively():
    claims = [{"cores": [7, 6, 5, 4, 3]}, {"cores": [2], "backfill": True}]
    head = ticket("head", 6, None)
    assert admits(config8(), FREE, claims, [head, ticket("t", 2)], "t") is None
    assert admits(config8(), FREE, claims, [head, ticket("t", 1)], "t") == [1]


def test_only_ordinary_requests_backfill_behind_an_ordinary_head():
    claims = [{"cores": [7, 6, 5, 4, 3, 2]}]
    head = ticket("head", 4, None)
    assert admits(config8(), FREE, claims, [head, ticket("t", 2)], "t") == [0, 1]
    assert admits(config8(), FREE, claims, [head, ticket("t", 2, background=True)], "t") is None
    # review r3: later ordinary requests overtake a background head, so it is never backfilled around
    background_head = ticket("head", 4, None, background=True)
    assert admits(config8(), FREE, claims, [background_head, ticket("t", 2, background=True)], "t") is None
    # an ordinary head ignores background claims, exactly as its own admission does, but a backfill
    # never takes their cores (it would suspend them)
    claims = [{"cores": [7, 6, 5, 4, 3, 2]}, {"cores": [1], "background": True}]
    assert admits(config8(), FREE, claims, [head, ticket("t", 1)], "t") == [0]
    assert admits(config8(), FREE, claims, [head, ticket("t", 2)], "t") is None


def test_no_backfill_while_a_timed_reservation_is_held():
    # review r1: the reservation may end before the claim does, and the head would then need core 1
    timed = {"held": True, "cores": [0]}
    config = {"cores": [3, 2, 1, 0], "keep_free": 0, "priority": "below_normal"}
    claims = [{"cores": [3, 2]}]
    assert admits(config, timed, claims, [ticket("head", 2, None), ticket("t", 1)], "t") is None
    assert admits(config, FREE, claims, [ticket("head", 2, None), ticket("t", 1)], "t") is None
    assert admits(config, FREE, [{"cores": [3, 2, 1]}], [ticket("head", 3, None),
                                                                       ticket("t", 1)], "t") == [0]


def test_core_pools_count_exactly():
    # a head restricted to cores 0-3 never uses 7 and 6, so a backfill there cannot delay it
    claims = [{"cores": [3, 2]}, {"cores": [5, 4]}]
    head = ticket("head", 4, None, core_pool=[0, 1, 2, 3])
    assert admits(config8(), FREE, claims, [head, ticket("t", 2)], "t") == [6, 7]
    assert admits(config8(), FREE, claims, [head, ticket("t", 2, core_pool=[0, 1])], "t") is None


def test_keep_free_counts_exactly():
    claims = [{"cores": [7, 6, 5, 4]}]
    # keep_free 2: two cores hand out now; releasing the claim leaves room for six, so 2 + 3 fit
    assert admits(config8(2), FREE, claims, [ticket("head", 3, None), ticket("t", 2)], "t") == [2, 3]
    assert admits(config8(2), FREE, claims, [ticket("head", 5, None), ticket("t", 2)], "t") is None


def test_only_the_first_eligible_request_behind_the_head_starts():
    claims = [{"cores": [7, 6, 5, 4, 3, 2]}]
    tickets = [ticket("head", 4, None), ticket("big", 3), ticket("a", 1), ticket("b", 1)]
    assert admits(config8(), FREE, claims, tickets, "big") is None  # does not fit
    assert admits(config8(), FREE, claims, tickets, "a") == [1]
    assert admits(config8(), FREE, claims, tickets, "b") is None


def test_more_live_claims_than_the_cap_refuses():
    claims = [{"cores": [7, 6, 5]}, {"cores": [4, 3, 2]}]
    tickets = [ticket("head", 2, None, core_pool=[7, 6, 5, 4, 3, 2]), ticket("t", 1)]
    assert admits(config8(), FREE, claims, tickets, "t") == [1]
    with patch.object(slots, "BACKFILL_MAX_RUNNING", 1):
        assert admits(config8(), FREE, claims, tickets, "t") is None
    # every live claim counts toward the cap: backfills and background claims too
    with patch.object(slots, "BACKFILL_MAX_RUNNING", 2):
        assert admits(config8(), FREE, claims, tickets, "t") == [1]
        for extra in ({"cores": [0], "backfill": True}, {"cores": [0], "background": True}):
            assert admits(config8(), FREE, claims + [extra], tickets, "t") is None


def test_only_a_head_queued_under_the_current_config_is_backfilled_around():
    # review r2: the head admits with the config it read before queueing
    claims = [{"cores": [7, 6, 5, 4, 3, 2]}]
    head, small = ticket("head", 4, None), ticket("t", 2)
    assert slots.backfill_admits(config8(), FREE, claims, [{**head, "config_sha256": slots.config_digest(
        config8())}, small], "t") == [0, 1]
    assert slots.backfill_admits(config8(), FREE, claims, [{**head, "config_sha256": slots.config_digest(
        config8(1))}, small], "t") is None
    # review r1: a ticket from an older launcher (no background field, no config) is never jumped
    assert slots.backfill_admits(config8(), FREE, claims, [{"id": "head", "cores_wanted": 4}, small], "t") is None


def test_a_backfill_never_takes_or_moves_the_head_onto_background_cores():
    # review r2: preference 0 to 4, ordinary C on 0, 1 and 4, background G on 3, a three-core head
    config = {"cores": [0, 1, 2, 3, 4], "keep_free": 0, "priority": "below_normal"}
    claims = [{"cores": [0, 1, 4]}, {"cores": [3], "background": True}]
    head = ticket("head", 3, None)
    assert admits(config, FREE, claims, [head, ticket("a", 1, core_pool=[3])], "a") is None  # G's core
    # after C ends the head takes 0 to 2 alone, but 0, 1 and 3 beside a backfill on 2: it would wait for G
    assert admits(config, FREE, claims, [head, ticket("b", 1, core_pool=[2])], "b") is None


def test_a_backfill_never_moves_an_ordinary_head_onto_background_cores():
    # review r1: an ordinary head admitted onto a background claim's cores waits for it to suspend.
    # Without the backfill the head takes 3, 2 and 1 at once; with it, it would need core 0.
    config = {"cores": [3, 2, 1, 0], "keep_free": 0, "priority": "below_normal"}
    claims = [{"cores": [0], "background": True, "state": "running"}]
    assert admits(config, FREE, claims, [ticket("head", 3, None), ticket("t", 1)], "t") is None
    # after the ordinary claim ends, the head takes 5 to 1 alone but would need core 0 beside the
    # backfill; a four-core head fits on 5 to 2 either way
    config6 = {"cores": [5, 4, 3, 2, 1, 0], "keep_free": 0, "priority": "below_normal"}
    claims = [{"cores": [0], "background": True}, {"cores": [5, 4, 3, 2]}]
    assert admits(config6, FREE, claims, [ticket("head", 5, None), ticket("t", 1)], "t") is None
    assert admits(config6, FREE, claims, [ticket("head", 4, None), ticket("t", 1)], "t") == [1]


# Upstream host_slots_v1 tests (ported from mtg-kernel python/tests/test_host_slots_v1.py)


class SlotMutexDeletionTests(unittest.TestCase):
    def test_transient_windows_denial_waits_for_atomic_acquisition(self):
        denied = PermissionError("transient directory acquisition denial")
        denied.winerror = 5
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(slots, "slots_dir", return_value=Path(temp)):
            mutex = slots.Mutex()
            mkdir = Path.mkdir
            attempts = []

            def acquire(path, *args, **kwargs):
                if path == mutex.path:
                    attempts.append(path)
                    self.assertFalse((path / "owner.json").exists())
                    if len(attempts) < 3:
                        raise denied
                return mkdir(path, *args, **kwargs)

            with patch.object(slots, "os", wraps=os) as platform, \
                    patch.object(slots, "self_identity", return_value=(os.getpid(), "creation")), \
                    patch.object(Path, "mkdir", acquire), \
                    patch.object(slots.time, "sleep") as sleep:
                platform.name = "nt"
                with mutex:
                    self.assertEqual(len(attempts), 3)
                    owner = slots.read_json(mutex.path / "owner.json")
                    self.assertEqual(owner["pid"], os.getpid())
                self.assertEqual(sleep.call_count, 2)
            self.assertFalse(mutex.path.exists())

    def test_live_holder_excludes_a_second_holder_until_release(self):
        import threading
        acquired, release, done = (threading.Event() for _ in range(3))
        failures = []
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(slots, "slots_dir", return_value=Path(temp)), \
                patch.object(slots, "MUTEX_TIMEOUT_SECONDS", 2):
            old = slots.Mutex().__enter__()
            thread = None
            try:
                def contender():
                    try:
                        with slots.Mutex():
                            acquired.set()
                            release.wait(2)
                    except BaseException as error:
                        failures.append(error)
                    finally:
                        done.set()

                thread = threading.Thread(target=contender, daemon=True)
                thread.start()
                self.assertFalse(acquired.wait(0.1), "a live holder must exclude the contender")
                self.assertFalse(done.is_set(), f"contender failed rather than waited: {failures}")
                old.__exit__()
                old = None
                self.assertTrue(acquired.wait(2), f"contender did not acquire after deletion: {failures}")
            finally:
                if old is not None:
                    old.__exit__()
                release.set()
                if thread is not None:
                    thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(failures, [])

    def test_persistent_windows_denial_expires_without_writing_an_owner(self):
        denied = PermissionError("persistent permission denial")
        denied.winerror = 5
        mutex = object.__new__(slots.Mutex)
        mutex.path = MagicMock()
        mutex.path.mkdir.side_effect = denied
        with patch.object(slots, "os") as platform, \
                patch.object(slots, "self_identity", return_value=(123, "creation")), \
                patch.object(slots, "MUTEX_TIMEOUT_SECONDS", 0.01), \
                patch.object(slots.time, "monotonic", side_effect=[0, 0.02]), \
                patch.object(slots, "write_json") as write:
            platform.name = "nt"
            with self.assertRaises(PermissionError) as failure:
                mutex.__enter__()
            self.assertIs(failure.exception, denied)
            write.assert_not_called()

    def test_stale_directory_rename_denial_cannot_spin_past_deadline(self):
        mutex = object.__new__(slots.Mutex)
        mutex.path = MagicMock()
        mutex.path.mkdir.side_effect = FileExistsError("stale directory")
        with patch.object(slots, "os") as platform, \
                patch.object(slots, "self_identity", return_value=(123, "creation")), \
                patch.object(slots, "MUTEX_TIMEOUT_SECONDS", 0.01), \
                patch.object(mutex, "_stale", return_value=True), \
                patch.object(slots.time, "monotonic", side_effect=[0, 0, 0.02]), \
                patch.object(slots.time, "sleep"), \
                patch.object(slots, "write_json") as write:
            platform.name = "nt"
            platform.rename.side_effect = PermissionError("stale rename denied")
            with self.assertRaises(TimeoutError):
                mutex.__enter__()
            platform.rename.assert_called_once()
            write.assert_not_called()

    def test_other_permission_errors_do_not_retry_or_write_an_owner(self):
        for platform_name, winerror in [("posix", 5), ("nt", 87)]:
            with self.subTest(platform=platform_name, winerror=winerror):
                denied = PermissionError("different refusal")
                denied.winerror = winerror
                mutex = object.__new__(slots.Mutex)
                mutex.path = MagicMock()
                mutex.path.mkdir.side_effect = denied
                with patch.object(slots, "os") as platform, \
                        patch.object(slots, "self_identity", return_value=(123, "creation")), \
                        patch.object(slots, "write_json") as write, \
                        patch.object(slots.time, "sleep") as sleep:
                    platform.name = platform_name
                    with self.assertRaises(PermissionError):
                        mutex.__enter__()
                    write.assert_not_called()
                    sleep.assert_not_called()


class SuspensionHandshakeTests(unittest.TestCase):
    def test_failed_windows_suspend_never_acknowledges_vacated_cores(self):
        tree = object.__new__(slots.Tree)
        tree.suspended = set()
        tree.members = MagicMock(return_value=[11, 12])
        with patch.object(slots, "os", name="nt") as fake_os, \
                patch.object(slots, "_suspend_pid", side_effect=lambda pid, suspend: pid == 11, create=True):
            fake_os.name = "nt"
            self.assertFalse(tree.set_suspended(True))
            self.assertEqual(tree.suspended, {11})
        with patch.object(slots, "os") as fake_os, \
                patch.object(slots, "_suspend_pid", return_value=True, create=True):
            fake_os.name = "nt"
            self.assertTrue(tree.set_suspended(True))
            self.assertEqual(tree.suspended, {11, 12})

    def test_failed_resume_remains_tracked_for_the_next_attempt(self):
        tree = object.__new__(slots.Tree)
        tree.suspended = {11, 12}
        tree.members = MagicMock(return_value=[11, 12])
        with patch.object(slots, "os") as fake_os, \
                patch.object(slots, "_suspend_pid", side_effect=lambda pid, suspend: pid == 11, create=True):
            fake_os.name = "nt"
            self.assertFalse(tree.set_suspended(False))
            self.assertEqual(tree.suspended, {12})
        with patch.object(slots, "os") as fake_os, \
                patch.object(slots, "_suspend_pid", return_value=True, create=True):
            fake_os.name = "nt"
            self.assertTrue(tree.set_suspended(False))
            self.assertEqual(tree.suspended, set())

    def test_start_resume_and_acknowledgement_share_the_admission_mutex(self):
        claim = Path("unused-claim.json")
        for suspend_succeeds in (False, True):
            with self.subTest(suspend_succeeds=suspend_succeeds):
                locked = [False]
                states = []
                class TestMutex:
                    def __enter__(inner):
                        self.assertFalse(locked[0])
                        locked[0] = True
                    def __exit__(inner, *_):
                        locked[0] = False
                child = MagicMock()
                child.wait.side_effect = [subprocess.TimeoutExpired("probe", 0), 0]
                tree = MagicMock()
                tree.cores, tree.suspended = [0], set()
                tree.members.side_effect = [[11], []]
                def start(*_):
                    self.assertTrue(locked[0])
                    return child
                def transition(suspend):
                    self.assertTrue(locked[0])
                    tree.suspended = {11} if suspend and suspend_succeeds else set()
                    return not suspend or suspend_succeeds
                def publish(_claim, state):
                    self.assertTrue(locked[0])
                    states.append(state)
                    return True
                tree.start.side_effect = start
                tree.set_suspended.side_effect = transition
                with patch.object(slots, "Tree", return_value=tree), \
                        patch.object(slots, "Mutex", TestMutex), \
                        patch.object(slots, "conflicts", side_effect=[False, True, False]), \
                        patch.object(slots, "_set_state_locked", side_effect=publish), \
                        patch.object(slots, "background_busy", return_value=False), \
                        patch.object(slots, "_budget_wait", return_value=False), \
                        patch.object(slots, "_event"), \
                        patch.object(slots.time, "sleep"), \
                        patch.object(slots.signal, "signal"):
                    self.assertEqual(slots._run_claimed(claim, [0], "normal", ["probe"], None, "x"), 0)
                self.assertEqual(states, ["running", "suspended", "resuming", "running"] if suspend_succeeds
                                 else ["running", "running"])
                tree.kill.assert_not_called()


class ChildCommandTests(unittest.TestCase):
    GIT = os.path.normpath("C:/Program Files/Git/bin/bash.exe")

    def resolve(self, command, path, files):
        env = {"PATH": os.pathsep.join(path), "ProgramFiles": "C:/Program Files"}
        with patch.dict(os.environ, env, clear=True),                 patch.object(slots.os.path, "isfile", lambda name: os.path.normpath(name) in files):
            return slots.child_command(command, windows=True)

    def test_bare_bash_skips_wsl_and_runs_git_bash_from_path(self):
        wsl = os.path.normpath("C:/Windows/System32/bash.exe")
        got = self.resolve(["bash", "run.sh"], ["C:/Windows/System32", "C:/Program Files/Git/bin"], {wsl, self.GIT})
        self.assertEqual([os.path.normpath(got[0]), got[1]], [self.GIT, "run.sh"])

    def test_bare_bash_falls_back_to_the_default_git_install(self):
        got = self.resolve(["bash.exe", "-c", "true"], ["C:/Windows/System32"], {self.GIT})
        self.assertEqual(os.path.normpath(got[0]), self.GIT)
        self.assertEqual(got[1:], ["-c", "true"])

    def test_bare_bash_without_git_bash_is_refused(self):
        with self.assertRaisesRegex(slots.Refused, "WSL"):
            self.resolve(["bash", "run.sh"], ["C:/Windows/System32"], {os.path.normpath("C:/Windows/System32/bash.exe")})

    def test_explicit_wsl_bash_is_refused(self):
        for program in ("C:/Windows/System32/bash.exe", r"c:\windows\sysnative\BASH",
                        "C:/Users/u/AppData/Local/Microsoft/WindowsApps/bash.exe"):
            with self.subTest(program=program), self.assertRaisesRegex(slots.Refused, "WSL"):
                self.resolve([program, "run.sh"], [], set())

    def test_other_commands_and_other_platforms_are_unchanged(self):
        self.assertEqual(self.resolve(["python", "x.py"], [], set()), ["python", "x.py"])
        self.assertEqual(self.resolve([self.GIT, "x.sh"], [], set()), [self.GIT, "x.sh"])
        self.assertEqual(slots.child_command(["bash", "x.sh"], windows=False), ["bash", "x.sh"])

    def test_cli_refuses_before_any_ticket(self):
        with tempfile.TemporaryDirectory() as root,                 patch.dict(os.environ, {"HOST_SLOTS_ROOT": root, "HOST_SLOTS_HOST": "TESTHOST"}),                 patch.object(slots, "child_command", side_effect=slots.Refused("WSL's bash")),                 patch.object(slots, "run") as run:
            code = slots.main(["run", "--lane", "l", "--work-id", "w", "--cores", "1", "--", "bash", "x.sh"])
            self.assertEqual(code, slots.EXIT_REFUSED)
            run.assert_not_called()
            self.assertEqual(list(Path(root).rglob("*")), [])




class HostSlotsTests(unittest.TestCase):
    def setUp(self):
        tmp_path = Path(tempfile.mkdtemp(prefix="host-slots-"))
        self.addCleanup(shutil.rmtree, tmp_path, ignore_errors=True)
        root = tmp_path / "host-lock"
        root.mkdir()
        env = patch.dict(os.environ, {slots.ROOT_ENV: str(root), slots.HOST_ENV: "TESTHOST", slots.POLL_ENV: "0.1"})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(slots.TOKEN_ENV, None)
        (root / "TESTHOST.slots").mkdir()
        slots.write_json(root / "TESTHOST.slots/config.json", {"cores": ",".join(map(str, reversed(CPUS))),
                                                                "lending": True})
        self.host, self.tmp_path = root, tmp_path

    def test_already_admitted_ordinary_claim_waits_past_startup_vacate_deadline(self):
        self.check_draining_admission(timed=False)

    def test_timed_release_lets_the_drainer_resume_ahead_of_the_ordinary_queue(self):
        self.check_draining_admission(timed=True)

    @unittest.skipUnless(sys.platform == "linux", "Linux process groups")
    def test_linux_drainer_resumes_ahead_of_queued_ordinary_work_after_timed_release(self):
        core = min(CPUS)
        claim_id = "a" * 32
        ordinary_id = "b" * 32
        claim = slots.slots_dir() / f"claim-{claim_id}.json"
        ordinary_claim = slots.slots_dir() / f"claim-{ordinary_id}.json"
        lock_path = self.host / "TESTHOST.lock"
        helper_pid_file, finish = self.tmp_path / "helper.pid", self.tmp_path / "finish"
        helper_done, ordinary_polled = self.tmp_path / "helper.done", self.tmp_path / "ordinary.polled"
        slots.write_json(slots.slots_dir() / "config.json", {"cores": str(core)})
        helper = script(self.tmp_path, "helper.py", (
            "from pathlib import Path\n"
            "Path(sys.argv[1]).write_text(str(os.getpid()))\n"
            "while not Path(sys.argv[2]).exists(): time.sleep(0.01)\n"
            "Path(sys.argv[3]).touch()\n"))
        parent = script(self.tmp_path, "parent.py", (
            "import subprocess\n"
            "subprocess.Popen([sys.executable, *sys.argv[1:]])\n"
            "sys.exit(23)\n"))
        runner = script(self.tmp_path, "runner.py", (
            "import ctypes\n"
            "# Reap the orphan locally even on test hosts whose PID 1 does not reap.\n"
            "assert ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) == 0\n"
            "members = h.Tree.members\n"
            "def reap_then_list(tree):\n"
            "    if tree.child is not None and tree.child.returncode is not None:\n"
            "        try: os.waitpid(-tree.child.pid, os.WNOHANG)\n"
            "        except ChildProcessError: pass\n"
            "    return members(tree)\n"
            "h.Tree.members = reap_then_list\n"
            f"sys.exit(h.run('linux', 'drain', 1, [sys.executable, *sys.argv[1:]], "
            f"background=True, claim_id={claim_id!r}))\n"))
        ordinary_runner = script(self.tmp_path, "ordinary.py", (
            "from pathlib import Path\n"
            "helper_done, polled = map(Path, sys.argv[1:])\n"
            "timed_state = h.timed_state\n"
            "def observe_timed_state():\n"
            "    state = timed_state()\n"
            "    if not state['held']: polled.touch()\n"
            "    return state\n"
            "h.timed_state = observe_timed_state\n"
            "def admitted(_claim):\n"
            "    assert helper_done.exists(), 'ordinary work admitted while the helper was still draining'\n"
            f"sys.exit(h.run('linux', 'ordinary', 1, [sys.executable, '-c', 'pass'], wait=True, "
            f"wait_timeout=15, claim_id={ordinary_id!r}, on_claim=admitted))\n"))
        proc = subprocess.Popen([sys.executable, runner, parent, helper, str(helper_pid_file), str(finish),
                                 str(helper_done)])
        ordinary = None
        try:
            self.assertTrue(wait_for(lambda: counter(helper_pid_file) and
                                     (slots.read_json(claim) or {}).get("draining"), timeout=5))
            with slots.Mutex():
                lock(self.host, cores=[core])
            self.assertTrue(wait_for(lambda: (slots.read_json(claim) or {}).get("state") == "suspended", timeout=5))
            stat = Path(f"/proc/{counter(helper_pid_file)}/stat").read_text()
            self.assertEqual(stat.rsplit(")", 1)[1].split()[0], "T")
            ordinary = subprocess.Popen([sys.executable, ordinary_runner, str(helper_done), str(ordinary_polled)],
                                        stderr=subprocess.PIPE, text=True)
            self.assertTrue(wait_for(lambda: list(slots.slots_dir().glob(f"queue-*-{ordinary_id}.json")), timeout=5))
            with slots.Mutex():
                lock_path.unlink()
            self.assertTrue(wait_for(lambda: ordinary_polled.exists() and
                                     (slots.read_json(claim) or {}).get("state") == "running", timeout=5))
            with slots.Mutex():
                self.assertFalse(ordinary_claim.exists())
                self.assertTrue(list(slots.slots_dir().glob(f"queue-*-{ordinary_id}.json")))
                self.assertFalse(helper_done.exists())
            finish.touch()
            self.assertEqual(proc.wait(timeout=5), 23)
            self.assertFalse(claim.exists())
            _, err = ordinary.communicate(timeout=5)
            self.assertEqual(ordinary.returncode, 0, err)
        finally:
            if ordinary is not None:
                if ordinary.poll() is None:
                    ordinary.terminate()
                ordinary.communicate(timeout=5)
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)

    def check_draining_admission(self, *, timed):
        core = max(CPUS)
        slots.write_json(slots.slots_dir() / "config.json", {"cores": str(core)})
        ids = {name: digit * 32 for name, digit in zip(("drain", "first", "second"), "abc")}
        lock_path = self.host / "TESTHOST.lock"
        polls, advances, trees = {}, {}, {}
        finished = threading.Event()
        helper_alive = True
        real_monotonic = time.monotonic
        now = real_monotonic()

        def record(name):
            return slots.read_json(slots.slots_dir() / f"claim-{ids[name]}.json")

        def pause():
            name = threading.current_thread().name
            polls[name].put("poll")
            advances[name].get(timeout=10)
            if finished.is_set():
                raise RuntimeError("test finished")

        def launch(name):
            polls[name], advances[name] = Queue(), Queue()
            tree = trees[name] = MagicMock()
            tree.cores, tree.suspended = [core], set()
            tree.members.side_effect = lambda: [120] if name == "drain" and helper_alive else []

            def suspend(stop):
                tree.suspended = {120} if stop else set()
                return True

            tree.set_suspended.side_effect = suspend
            if name == "drain":
                def wait_for_child(timeout):
                    pause()
                    return 23
                tree.start.return_value.wait.side_effect = wait_for_child
            else:
                tree.start.return_value.wait.return_value = 0

            def runner():
                try:
                    polls[name].put(slots.run("lane", name, 1, ["probe"], wait=True,
                                              claim_id=ids[name], background=name == "drain"))
                except BaseException as exc:
                    polls[name].put(exc)

            thread = threading.Thread(target=runner, name=name, daemon=True)
            thread.start()
            stack.callback(thread.join, 11)
            stack.callback(advances[name].put, None)
            stack.callback(finished.set)
            expect(name, "poll")

        def expect(name, expected, *, advance=False):
            if advance:
                advances[name].put(None)
            result = polls[name].get(timeout=10)
            if isinstance(result, BaseException):
                raise result
            self.assertEqual(result, expected, name)

        with ExitStack() as stack:
            stack.enter_context(patch.object(slots, "Tree", side_effect=lambda *_: trees[threading.current_thread().name]))
            stack.enter_context(patch.object(slots, "poll_seconds", return_value=0))
            stack.enter_context(patch.object(slots.signal, "signal"))
            clock = stack.enter_context(patch.object(slots, "time", wraps=time))
            clock.sleep.side_effect = lambda delay: pause() if delay == 0 else time.sleep(delay)
            clock.monotonic.side_effect = lambda: now
            launch("drain")
            if timed:
                lock(self.host, cores=[core])
            launch("first")
            if timed:
                launch("second")
                self.assertIsNone(record("first"))
            else:
                self.assertEqual(record("first")["state"], "suspended")
            expect("drain", "poll", advance=True)
            self.assertEqual(record("drain")["state"], "suspended" if timed else "running")
            self.assertEqual(bool(trees["drain"].suspended), timed)
            if timed:
                lock_path.unlink()
                for name in ("first", "second"):
                    expect(name, "poll", advance=True)
                    self.assertIsNone(record(name), "an ordinary claim took the drainer's acknowledged CPUs")
                expect("drain", "poll", advance=True)
                self.assertFalse(trees["drain"].suspended)
            else:
                now += slots.TIMED_VACATE_SECONDS + 1
                expect("first", "poll", advance=True)
                trees["first"].start.assert_not_called()
            self.assertTrue(record("drain")["draining"])
            helper_alive = False
            expect("drain", 23, advance=True)
            self.assertIsNone(record("drain"))
            expect("first", 0, advance=True)
            if timed:
                expect("second", 0, advance=True)

    def test_start_waits_for_busy_publication_before_launching(self):
        core = max(CPUS)
        claim_id = "a" * 32
        claim = slots.slots_dir() / f"claim-{claim_id}.json"
        tree = MagicMock()
        tree.cores = [core]
        tree.start.return_value.wait.return_value = 23
        tree.members.return_value = []
        write = slots.write_json
        polls = 0

        def publish(path, record):
            if path == claim and polls == 1 and record["state"] == "running":
                raise PermissionError("cannot replace the suspended record")
            return write(path, record)

        def pause(_delay):
            nonlocal polls
            self.assertEqual(slots.read_json(claim)["state"], "suspended")
            tree.start.assert_not_called()
            polls += 1
            self.assertLessEqual(polls, 2)
            if polls == 1:
                (self.host / "TESTHOST.lock").unlink()

        with patch.object(slots, "Tree", return_value=tree), patch.object(slots, "write_json", side_effect=publish), \
                patch.object(slots, "time", wraps=time) as clock:
            clock.sleep.side_effect = pause
            code = slots.run("lane", "probe", 1, ["probe"], wait=True, claim_id=claim_id,
                             on_claim=lambda _: lock(self.host, cores=[core]))
        self.assertEqual((code, polls), (23, 2))

    @unittest.skipUnless(os.name == "nt", "Windows job suspension")
    def test_drain_requires_complete_suspend_and_busy_publication_before_retrying_resume(self):
        core = max(CPUS)
        claim_id = "c" * 32
        claim = slots.slots_dir() / f"claim-{claim_id}.json"
        lock_path = self.host / "TESTHOST.lock"
        tree = slots.Tree.__new__(slots.Tree)
        tree.cores, tree.suspended, tree.job = [core], set(), object()
        tree.start, tree.kill = MagicMock(), MagicMock()
        group = {110, 120}
        write = slots.write_json
        phase = 0

        def wait_for_main(timeout):
            lock(self.host, cores=[core])
            return 23

        def suspend(pid, stop):
            if not stop:
                self.assertEqual(slots.read_json(claim)["state"], "resuming")
                self.assertGreaterEqual(phase, 3, "resumed without a confirmed busy record")
            return not ((phase == 0 and stop or phase == 3 and not stop) and pid == 120)

        def publish(path, record):
            if path == claim and phase == 2 and record["state"] != "suspended":
                raise PermissionError("cannot replace the suspended record")
            return write(path, record)

        def pause(_delay):
            nonlocal phase
            states = ["running", "suspended", "suspended", "resuming", "running"]
            stopped = [{110}, group, group, {120}, set()]
            self.assertLess(phase, len(states))
            self.assertEqual(slots.read_json(claim)["state"], states[phase])
            self.assertEqual(tree.suspended, stopped[phase])
            if phase == 1:
                lock_path.unlink()
            if phase == 4:
                group.clear()
            phase += 1

        tree.start.return_value.wait.side_effect = wait_for_main
        with patch.object(slots, "Tree", return_value=tree), patch.object(slots, "write_json", side_effect=publish), \
                patch.object(slots, "_job_members", side_effect=lambda _: [os.getpid(), *group]), \
                patch.object(slots, "_suspend_pid", side_effect=suspend), patch.object(slots, "time", wraps=time) as clock:
            clock.sleep.side_effect = pause
            self.assertEqual(slots.run("lane", "probe", 1, ["probe"], claim_id=claim_id, background=True), 23)
        self.assertEqual(phase, 5)
        self.assertFalse(claim.exists())

    @unittest.skipUnless(os.name == "nt", "Windows worker adoption")
    def test_adopted_worker_exit_during_suspend_drains_its_helper_before_handoff(self):
        core = max(CPUS)
        slots.write_json(slots.slots_dir() / "config.json", {"cores": str(core)})
        claim_id = "d" * 32
        claim = slots.slots_dir() / f"claim-{claim_id}.json"
        ordinary = slots.slots_dir() / "claim-ordinary.json"
        ready = self.tmp_path / "worker-ready.json"
        worker = os.getpid() + 1
        tree = MagicMock()
        tree.cores, tree.suspended, tree.job = [core], {worker, 120}, None
        process_state = slots.process_state
        phase = 0
        worker_exited = False

        def suspend(stop):
            nonlocal worker_exited
            if stop:
                worker_exited = True
            tree.suspended = {120} if stop else set()
            return True

        def pause(_delay):
            nonlocal phase
            self.assertTrue(ready.exists())
            self.assertEqual(slots.read_json(claim)["state"], "running")
            self.assertFalse(tree.suspended)
            if phase == 0:
                pid, creation = slots.self_identity()
                slots.write_json(ordinary, {"id": "ordinary", "pid": pid, "creation_time": creation,
                                            "cores": [core], "state": "running"})
            else:
                self.assertEqual(phase, 1)
                self.assertTrue(slots.read_json(claim)["draining"])
            phase += 1

        tree.set_suspended.side_effect = suspend
        tree.members.side_effect = lambda: [120] if phase < 2 else []
        with patch.object(slots, "Tree", return_value=tree), patch.object(slots, "time", wraps=time) as clock, \
                patch.object(slots, "process_state", side_effect=lambda pid, creation: (
                    ("absent" if worker_exited else "alive") if pid == worker else process_state(pid, creation))):
            clock.sleep.side_effect = pause
            self.assertEqual(slots.run("lane", "adopt", 1, ["probe"], claim_id=claim_id, background=True,
                                       adopted={"pid": worker, "creation": 42, "ready": str(ready)}), 0)
        self.assertEqual(phase, 2)
        self.assertFalse(claim.exists())
        self.assertFalse(ready.exists())

    @needs_two_ut
    def test_exited_shared_child_drains_when_its_helper_cannot_narrow(self):
        guarantee, extra = sorted(CPUS, reverse=True)[:2]
        claim_id = "e" * 32
        claim = slots.slots_dir() / f"claim-{claim_id}.json"
        ordinary = slots.slots_dir() / "claim-ordinary.json"
        lock_path = self.host / "TESTHOST.lock"
        tree = MagicMock()
        tree.cores = tree.applied = sorted([guarantee, extra])
        tree.suspended = set()
        tree.set_cores.return_value = False
        phase = 0
        exited_in_suspend = False

        def wait_for_main(timeout):
            if exited_in_suspend:
                return 23
            pid, creation = slots.self_identity()
            slots.write_json(ordinary, {"id": "ordinary", "pid": pid, "creation_time": creation,
                                        "cores": [extra], "state": "suspended"})
            raise subprocess.TimeoutExpired("probe", timeout)

        def suspend(stop):
            nonlocal exited_in_suspend
            tree.suspended = {120} if stop else set()
            exited_in_suspend |= stop
            return True

        def pause(_delay):
            nonlocal phase
            record = slots.read_json(claim)
            self.assertTrue(record["draining"])
            self.assertEqual(slots.held(record), tree.cores)
            self.assertLess(phase, 4)
            must_yield = phase in (1, 2)
            self.assertEqual(record["state"], "suspended" if must_yield else "running")
            self.assertEqual(bool(tree.suspended), must_yield)
            if phase == 0:
                lock(self.host, cores=[extra])
            elif phase == 1:
                lock_path.unlink()
                slots.write_json(ordinary, {**slots.read_json(ordinary), "state": "running", "background": True,
                                            "draining": False})
                self.assertFalse(slots.claim_conflicts([extra], True), "the admitted borrower must be able to start")
            elif phase == 2:
                ordinary.unlink()
            phase += 1

        child = tree.start.return_value
        child.wait.side_effect = wait_for_main
        child.poll.side_effect = lambda: 23 if exited_in_suspend else None
        tree.set_suspended.side_effect = suspend
        tree.members.side_effect = lambda: [120] if phase < 4 else []
        with patch.object(slots, "Tree", return_value=tree), patch.object(slots, "time", wraps=time) as clock:
            clock.sleep.side_effect = pause
            self.assertEqual(slots.run("lane", "shared", 2, ["probe"], claim_id=claim_id, shared=True), 23)
        self.assertTrue(tree.set_cores.called)
        for call in tree.set_cores.call_args_list:
            self.assertEqual(call.args, ([guarantee],))
        self.assertEqual(phase, 4)
        self.assertFalse(claim.exists())

    def test_draining_shared_claim_preserves_the_keep_free_budget(self):
        guarantee, extra, other, spare = range(4)
        slots.write_json(slots.slots_dir() / "config.json", {"cores": "0-3", "keep_free": 1})
        claim, borrower = (slots.slots_dir() / f"claim-{name}.json" for name in ("shared", "borrower"))
        tree = MagicMock()
        tree.cores = sorted([guarantee, extra])
        pid, creation = slots.self_identity()
        identity = {"pid": pid, "creation_time": creation, "state": "running"}
        with slots.Mutex(), patch.object(slots, "cpu_total", return_value=4):
            slots.write_json(claim, {**identity, "id": "shared", "shared": True,
                                    "cores": tree.cores, "guaranteed": [guarantee]})
            slots.write_json(borrower, {**identity, "id": "borrower", "cores": [other, spare]})
            self.assertFalse(slots._drain_conflict(tree, claim, "shared", [guarantee], False, True, False))
            self.assertTrue(slots._budget_wait("borrower"))
            slots._set_state_locked(claim, "suspended")
            self.assertFalse(slots._budget_wait("borrower"))
            self.assertTrue(slots._drain_conflict(tree, claim, "shared", [guarantee], False, True, True))
            slots.write_json(borrower, {**slots.read_json(borrower), "state": "suspended",
                                        "shared": True, "guaranteed": [other], "draining": True})
            self.assertFalse(slots._drain_conflict(tree, claim, "shared", [guarantee], False, True, True))
            borrower.unlink()
            self.assertFalse(slots._drain_conflict(tree, claim, "shared", [guarantee], False, True, True))

    def test_admitted_ordinary_claim_waits_past_deadline_for_a_disjoint_draining_lender(self):
        slots.write_json(slots.slots_dir() / "config.json", {"cores": "3,2,1,0", "keep_free": 1})
        drainer, other, borrower = (slots.slots_dir() / f"claim-{name}.json"
                                   for name in ("drainer", "other", "a" * 32))
        pid, creation = slots.self_identity()
        shared = {"pid": pid, "creation_time": creation, "state": "running", "shared": True, "draining": False}
        slots.write_json(drainer, {**shared, "id": "drainer", "guaranteed": [1], "cores": [0, 1]})
        slots.write_json(other, {**shared, "id": "other", "guaranteed": [3], "cores": [3]})
        tree = MagicMock(cores=[2])
        tree.start.return_value.wait.return_value = 23
        tree.members.return_value = []
        now, polls = time.monotonic(), 0

        def after_admission(info):
            self.assertEqual(info["cores"], [2])
            with slots.Mutex():
                self.assertFalse(slots._drain_conflict(MagicMock(cores=[0, 1]), drainer, "drainer",
                                                       [1], False, True, False))

        def pause(_delay):
            nonlocal now, polls
            self.assertEqual(slots.read_json(borrower)["state"], "suspended")
            self.assertTrue(slots._budget_wait("a" * 32))
            self.assertFalse(slots.background_busy([2], "a" * 32))
            tree.start.assert_not_called()
            polls += 1
            now += slots.TIMED_VACATE_SECONDS + 1
            if polls == 2:
                drainer.unlink()

        with patch.object(slots, "cpu_total", return_value=4), patch.object(slots, "Tree", return_value=tree), \
                patch.object(slots, "time", wraps=time) as clock:
            clock.monotonic.side_effect = lambda: now
            clock.sleep.side_effect = pause
            code = slots.run("lane", "borrower", 1, ["probe"], wait=True, claim_id="a" * 32,
                             on_claim=after_admission)
        self.assertEqual((code, polls), (23, 2))
        tree.start.assert_called_once()

    @needs_two_ut
    def test_exited_shared_child_narrows_a_live_helper_without_a_queued_request(self):
        guarantee, extra = sorted(CPUS, reverse=True)[:2]
        tree = MagicMock(cores=sorted([guarantee, extra]), suspended=set())
        tree.applied = tree.cores
        tree.start.return_value.wait.return_value = 23
        tree.members.side_effect = [[120], []]
        claim_id = "a" * 32
        claim = slots.slots_dir() / f"claim-{claim_id}.json"

        def narrow(cores):
            self.assertEqual(slots.read_json(claim)["cores"], sorted([guarantee, extra]))
            tree.cores = tree.applied = cores
            return True

        def pause(_delay):
            report = slots.status()
            self.assertFalse(report["queue"])
            self.assertTrue(report["claims"][0]["draining"])
            self.assertEqual(report["claims"][0]["cores"], [guarantee])
            self.assertIn(extra, slots.parse_cores(report["foreground_available"]))
            self.assertFalse(slots._marker_path(claim_id).exists())

        tree.set_cores.side_effect = narrow
        with patch.object(slots, "Tree", return_value=tree), patch.object(slots, "time", wraps=time) as clock:
            clock.sleep.side_effect = pause
            self.assertEqual(slots.run("lane", "shared", 2, ["probe"], claim_id=claim_id, shared=True), 23)
        tree.set_cores.assert_called_once_with([guarantee])
        self.assertNotIn(True, [call.args[0] for call in tree.set_suspended.call_args_list])

    def test_drainer_checks_timed_conflicts_on_published_and_tree_cores(self):
        claim = slots.slots_dir() / "claim-shared.json"
        slots.write_json(claim, {"cores": [0, 1], "guaranteed": [0], "shared": True})
        tree = MagicMock(cores=[0])
        lock(self.host, cores=[1])
        with slots.Mutex():
            self.assertTrue(slots._drain_conflict(tree, claim, "shared", [0], False, True, False))
        self.assertEqual(slots.read_json(claim)["cores"], [0, 1])

    def test_background_drainer_can_resume_on_a_suspended_shared_claims_lent_core(self):
        claim, shared = (slots.slots_dir() / f"claim-{name}.json" for name in ("background", "shared"))
        pid, creation = slots.self_identity()
        suspended = {"pid": pid, "creation_time": creation, "state": "suspended", "draining": True}
        slots.write_json(claim, {**suspended, "id": "background", "cores": [1], "background": True})
        slots.write_json(shared, {**suspended, "id": "shared", "cores": [0, 1], "shared": True, "guaranteed": [0]})
        with slots.Mutex():
            self.assertFalse(slots._drain_conflict(MagicMock(cores=[1]), claim, "background", [1],
                                                   True, False, True))

    def test_failed_draining_publish_keeps_a_vacated_tree_suspended_until_retry(self):
        claim = slots.slots_dir() / "claim-background.json"
        tree = MagicMock(cores=[0])
        pid, creation = slots.self_identity()
        slots.write_json(claim, {"id": "background", "pid": pid, "creation_time": creation, "cores": [0],
                                 "background": True, "draining": False, "state": "suspended"})
        with slots.Mutex():
            with patch.object(slots, "write_json", side_effect=PermissionError("cannot publish draining")):
                self.assertTrue(slots._drain_conflict(tree, claim, "background", [0], True, False, True))
            self.assertEqual(slots.read_json(claim)["state"], "suspended")
            self.assertFalse(slots.read_json(claim)["draining"])
            self.assertFalse(slots._drain_conflict(tree, claim, "background", [0], True, False, True))
            self.assertTrue(slots.read_json(claim)["draining"])

    def test_launchers_refuse_legacy_background_and_shared_claims(self):
        pid, creation = slots.self_identity()
        claim = slots.slots_dir() / "claim-legacy.json"
        core = max(CPUS)
        command = ("--", sys.executable, "-c", "raise SystemExit(99)")
        options = ("--lane", "test", "--work-id", "rollout", "--cores", "1")
        log = self.tmp_path / "submit.log"
        lock(self.host, cores=[core])
        with patch.dict(os.environ, {slots.TOKEN_ENV: TOKEN}):
            for kind, state in (("background", "running"), ("shared", "suspended")):
                slots.write_json(claim, {"pid": pid, "creation_time": creation, "id": "legacy",
                                         "cores": [core], "state": state, kind: True})
                for args in (("run", *options), ("submit", "--log", str(log), *options),
                             ("timed", "--cores", str(core))):
                    with self.subTest(kind=kind, op=args[0]), cli(*args, *command) as proc:
                        _, err = proc.communicate(timeout=10)
                        self.assertEqual(proc.returncode, slots.EXIT_REFUSED, err)
                        self.assertIn("legacy background or shared claim legacy lacks the draining field", err)
                self.assertTrue(claim.exists())
                self.assertFalse(log.exists())
                self.assertFalse(list(slots.slots_dir().glob("queue-*.json")))
                self.assertFalse(list(slots.slots_dir().glob("share-*.json")))

    @unittest.skipUnless(os.name == "nt", "Windows job suspension")
    def test_exited_background_child_drains_helpers_without_handing_off(self):
        for exit_during_suspend in (False, True):
            with self.subTest(exit_during_suspend=exit_during_suspend):
                self.check_background_helper(exit_during_suspend=exit_during_suspend)

    @unittest.skipUnless(os.name == "nt", "Windows job suspension")
    def test_exited_background_child_respects_prior_handoffs_and_timed_reservations(self):
        for timed in (False, True):
            with self.subTest(timed=timed):
                self.check_background_helper(timed=timed, handed_off=not timed)
        self.check_background_helper(handed_off=True, uncertain_ack=True)

    def check_background_helper(self, *, exit_during_suspend=False, timed=False, handed_off=False,
                                uncertain_ack=False):
        claim_id = "a" * 32
        claim = slots.slots_dir() / f"claim-{claim_id}.json"
        ordinary = slots.slots_dir() / "claim-ordinary.json"
        core = max(CPUS)
        slots.write_json(slots.slots_dir() / "config.json", {"cores": str(core)})
        child_pid, helper_pid = 110, 120
        child = MagicMock()
        tree = slots.Tree.__new__(slots.Tree)
        tree.cores, tree.suspended, tree.job = [core], set(), object()
        tree.start = MagicMock(return_value=child)
        tree.kill = MagicMock()
        main_exited, helper_ticks = False, 0
        must_yield = timed or handed_off
        released = False
        publish_state = slots._set_state_locked

        def publish(path, state):
            result = publish_state(path, state)
            return result and not (uncertain_ack and state == "suspended")

        def wait_for_main(timeout):
            nonlocal main_exited
            if child.wait.call_count == 1:
                if timed:
                    lock(self.host, cores=[core])
                else:
                    pid, creation = slots.self_identity()
                    slots.write_json(ordinary, {"id": "ordinary", "pid": pid, "creation_time": creation,
                                                "cores": [core], "state": "running"})
                if exit_during_suspend or handed_off:
                    raise subprocess.TimeoutExpired("probe", timeout)
            if handed_off and not released:
                self.assertEqual(slots.read_json(claim)["state"], "suspended")
                self.assertIn(helper_pid, tree.suspended)
            main_exited = True
            return 23

        def members(_job):
            pids = [os.getpid()]
            if not main_exited:
                pids.append(child_pid)
            if helper_ticks < 2:
                pids.append(helper_pid)
            return pids

        def suspend(pid, suspend):
            nonlocal main_exited
            if exit_during_suspend and pid == child_pid and suspend:
                main_exited = True
            return True

        def tick(delay):
            nonlocal helper_ticks, released
            if delay:
                time.sleep(delay)
                return
            record = slots.read_json(claim)
            self.assertEqual(record["cores"], [core])
            self.assertTrue(slots.claim_conflicts([core], True) or released)
            if must_yield and not released:
                self.assertEqual(record["state"], "suspended")
                self.assertIn(helper_pid, tree.suspended)
                (self.host / "TESTHOST.lock" if timed else ordinary).unlink()
                released = True
                return
            self.assertNotIn(helper_pid, tree.suspended, "the exited child's helper is still suspended")
            self.assertEqual(record["state"], "running")
            self.assertEqual(released, must_yield)
            self.assertLess(helper_ticks, 2, "the empty job did not release its claim")
            helper_ticks += 1

        child.wait.side_effect = wait_for_main
        child.poll.side_effect = lambda: 23 if main_exited else None
        try:
            with patch.object(slots, "Tree", return_value=tree), \
                    patch.object(slots, "_job_members", side_effect=members), \
                    patch.object(slots, "_set_state_locked", side_effect=publish), \
                    patch.object(slots, "_suspend_pid", side_effect=suspend) as suspend_pid, \
                    patch.object(slots, "poll_seconds", return_value=0), patch.object(slots, "time", wraps=time) as clock:
                clock.sleep.side_effect = tick
                code = slots.run("lane", "probe", 1, ["probe"], wait=True, claim_id=claim_id, background=True)
            self.assertEqual(helper_ticks, 2)
            self.assertEqual(code, 23)
            self.assertFalse(claim.exists())
            tree.kill.assert_not_called()
            if not exit_during_suspend and not must_yield:
                suspend_pid.assert_not_called()
            events = [json.loads(line) for path in slots.util_dir().glob("events-*.jsonl")
                      for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any(event["event"] == "end" and event["id"] == claim_id
                                and event["exit_code"] == 23 for event in events))
        finally:
            ordinary.unlink(missing_ok=True)
            (self.host / "TESTHOST.lock").unlink(missing_ok=True)

    @unittest.skipUnless(os.name == "nt", "Windows job membership")
    def test_job_snapshot_cannot_release_while_a_grandchild_is_live(self):
        claim_id = "b" * 32
        claim = slots.slots_dir() / f"claim-{claim_id}.json"
        parent_pid, grandchild_pid = 110, 120
        tree = slots.Tree.__new__(slots.Tree)
        tree.cores, tree.suspended, tree.job = [max(CPUS)], set(), object()
        tree.start = MagicMock()
        tree.start.return_value.wait.return_value = 23
        tree.kill = MagicMock()
        parent_handle = object()
        open_process, wait, close = slots._OpenProcess, slots._WaitForSingleObject, slots._CloseHandle
        parent_exited = False
        ticks = 0

        def snapshot(_job):
            nonlocal parent_exited
            if not parent_exited:
                # The parent spawns its successor and exits just after this snapshot.
                parent_exited = True
                return [os.getpid(), parent_pid]
            return [os.getpid()] if ticks == 2 else [os.getpid(), grandchild_pid]

        def tick(delay):
            nonlocal ticks
            if delay:
                time.sleep(delay)
                return
            self.assertTrue(claim.exists())
            self.assertLess(ticks, 2)
            ticks += 1

        with patch.object(slots, "Tree", return_value=tree), \
                patch.object(slots, "_job_members", side_effect=snapshot), \
                patch.object(slots, "_OpenProcess", side_effect=lambda access, inherit, pid: (
                    parent_handle if pid == parent_pid else open_process(access, inherit, pid))), \
                patch.object(slots, "_WaitForSingleObject", side_effect=lambda handle, timeout: (
                    slots.WAIT_OBJECT_0 if handle is parent_handle else wait(handle, timeout))), \
                patch.object(slots, "_CloseHandle", side_effect=lambda handle: (
                    True if handle is parent_handle else close(handle))), \
                patch.object(slots, "poll_seconds", return_value=0), patch.object(slots, "time", wraps=time) as clock:
            clock.sleep.side_effect = tick
            self.assertEqual(slots.run("lane", "probe", 1, ["probe"], claim_id=claim_id), 23)
        self.assertEqual(ticks, 2, "the claim released while a grandchild was still live")
        self.assertFalse(claim.exists())
        tree.kill.assert_not_called()

    @needs_two_ut
    def test_request_core_pool_is_contained_and_cannot_borrow_timed_cores(self):
        chosen = CPUS[0]
        slots.write_json(self.host / "TESTHOST.slots/config.json",
                         {"cores": ",".join(map(str, reversed(CPUS))), "keep_free": 1})
        probe = script(self.tmp_path, "pool.py", "print(json.dumps({'affinity': h.current_affinity()}))\n")
        arguments = ["run", "--lane", "pool", "--work-id", "bounded", "--cores", "1",
                     "--core-pool", str(chosen), "--pool-reason", "isolation", "--", sys.executable, probe]
        proc = cli(*arguments)
        out, err = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 0, err)
        rows = [json.loads(line) for line in out.splitlines()]
        self.assertEqual(rows[0]["cores"], str(chosen))
        self.assertEqual(rows[1]["affinity"], [chosen])
        lock(self.host)
        declare(self.host, [chosen])
        proc = cli(*arguments)
        _, err = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, slots.EXIT_HELD, err)
        self.assertFalse(list((self.host / "TESTHOST.slots").glob("claim-*.json")))
        self.assertFalse(list((self.host / "TESTHOST.slots").glob("queue-*.json")))


    def test_ordinary_admission_bypasses_background_and_preserves_ordinary_fifo(self):
        claim_id = "a" * 32
        background = {"id": "b" * 32, "background": True}
        earlier = {"id": "c" * 32}
        own = {"id": claim_id}
        with patch.object(slots, "_snapshot", side_effect=[
                snapshot_of([background, earlier, own]), snapshot_of([background, own])]), \
                patch.object(slots, "_run_claimed", return_value=0) as launch, \
                patch.object(slots.time, "sleep") as sleep:
            result = slots.run("probe", "ordinary", 1, ["unused"], wait=True, claim_id=claim_id)
        self.assertEqual(result, 0)
        self.assertEqual(sleep.call_count, 1, "the earlier ordinary request must enter first")
        launch.assert_called_once()
        self.assertEqual(launch.call_args.args[-1], claim_id)
        self.assertFalse(list((self.host / "TESTHOST.slots").glob("claim-*.json")))
        self.assertFalse(list((self.host / "TESTHOST.slots").glob("queue-*.json")))

    def test_background_queue_does_not_deadlock_a_legacy_fifo_launcher(self):
        host, tmp_path = self.host, self.tmp_path
        lock(host)
        mark = script(tmp_path, "mixed-mark.py", "open(sys.argv[1], 'a').write(sys.argv[2] + '\\n')\n")
        legacy = script(tmp_path, "legacy-fifo.py", "class FilenameFIFO(list):\n"
                        "    def sort(self, *args, **kwargs): pass\n"
                        "read_snapshot = h._snapshot\n"
                        "def legacy_snapshot():\n"
                        "    snap = read_snapshot()\n"
                        "    if snap is not None:\n"
                        "        snap['tickets'] = FilenameFIFO(snap['tickets'])\n"
                        "    return snap\n"
                        "h._snapshot = legacy_snapshot\n"
                        "raise SystemExit(h.main())\n")
        order = tmp_path / "mixed-order"
        ci = cli("run", "--wait", "--background", "--priority", "idle", "--lane", "ci",
                 "--work-id", "older-ci", "--cores", str(len(CPUS)), "--",
                 sys.executable, mark, str(order), "ci")
        foreground = None
        try:
            self.assertTrue(wait_for(lambda: len(slots.status()["queue"]) == 1))
            foreground = subprocess.Popen([sys.executable, legacy, "run", "--wait", "--lane", "build",
                          "--work-id", "legacy-build", "--cores", str(len(CPUS)), "--",
                          sys.executable, mark, str(order), "build"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertTrue(wait_for(lambda: len(slots.status()["queue"]) == 2))
            (host / "TESTHOST.lock").unlink()
            foreground.communicate(timeout=30)
            ci.communicate(timeout=30)
            self.assertEqual(foreground.returncode, 0)
            self.assertEqual(ci.returncode, 0)
            self.assertEqual(order.read_text().split(), ["build", "ci"])
        finally:
            (host / "TESTHOST.lock").unlink(missing_ok=True)
            for process in (foreground, ci):
                if process and process.poll() is None:
                    process.terminate()
                    process.communicate(timeout=30)



class BackgroundPolicyTests(unittest.TestCase):
    def test_ordinary_claims_can_reclaim_background_cores(self):
        config = {"cores": [0, 1, 2, 3], "keep_free": 0}
        timed = {"held": True, "cores": [0]}
        claims = [{"cores": [1, 2], "background": True}, {"cores": [3]}]
        self.assertEqual(slots.available(config, timed, claims), [])
        self.assertEqual(slots.available(config, timed, claims, background=False), [1, 2])

    def test_background_requests_take_cores_from_the_far_end_of_the_order(self):
        room = slots.available(config8(), FREE, [])
        self.assertEqual(slots.background_order(config8(), room), [0, 1, 2, 3, 4, 5, 6, 7])
        # the CI floor is still taken first; the other cores then come from the far end
        self.assertEqual(slots.background_order(FLOOR8, slots.available(FLOOR8, FREE, [])), [1, 0, 2, 3, 4, 5, 6, 7])
        claims = [{"cores": [7, 6]}, {"cores": [0], "background": True}]
        self.assertEqual(slots.background_order(config8(), slots.available(config8(), FREE, claims)), [1, 2, 3, 4, 5])

    def test_background_placement_preserves_the_reserve_with_an_ordinary_core_pool(self):
        room = slots.available(CONFIG4, FREE, [])
        background_cores = slots.background_order(CONFIG4, room)[:1]
        claims = [{"cores": background_cores, "background": True}]
        head = ticket("head", 3, None, core_pool=[0, 1, 3])
        self.assertEqual(slots._head_start(CONFIG4, FREE, claims, head), ({0, 1, 3}, {0}))

    def test_review_states_keep_mains_outcome_for_ordinary_requests_and_predictions(self):
        # review round 1, state 1: preference 0 to 4, ordinary C on 0, 1, 4, background G on 3, a three-core head
        config = {"cores": [0, 1, 2, 3, 4], "keep_free": 0, "priority": "below_normal"}
        claims = [{"cores": [0, 1, 4]}, {"cores": [3], "background": True}]
        head = ticket("head", 3, None)
        self.assertIsNone(admits(config, FREE, claims, [head, ticket("b", 1, core_pool=[2])], "b"))
        # state 2: preference 0 to 3, ordinary on 1, 3, background on 2, a three-core head, a backfill on 0
        config4 = {"cores": [0, 1, 2, 3], "keep_free": 0, "priority": "below_normal"}
        claims2 = [{"cores": [1, 3]}, {"cores": [2], "background": True}]
        self.assertEqual(admits(config4, FREE, claims2, [head, ticket("b", 1, core_pool=[0])], "b"), [0])
        # after the ordinary claim ends, the head's prediction is the cores it really takes, with and without the
        # backfill, and the handoffs (background core 2) are the same either way: no unbudgeted suspension
        for rest in ([{"cores": [2], "background": True}],
                     [{"cores": [2], "background": True}, {"cores": [0], "backfill": True}]):
            chosen, handoffs = slots._head_start(config4, FREE, rest, head)
            actual = slots.available(config4, FREE, rest, background=False)[:3]   # run()'s ordinary choice
            self.assertEqual(chosen, set(actual))
            self.assertEqual(handoffs, {2})

    def test_old_and_new_copies_agree_whichever_placed_the_background_claims(self):
        """A background claim placed by an old copy (front of the order) or a new one (far end): every copy's
        prediction of an ordinary head is the cores that head's admission really takes, because both read the
        live claims and choose ordinary cores the same way; only where background work sits differs."""
        old_choice = lambda config, room: room                                    # noqa: E731  main's background choice
        new_choice = slots.background_order
        for config in (config8(), config8(1), FLOOR8):
            for background_cores, ordinary in ((1, [{"cores": [7]}]), (2, []), (3, [{"cores": [5, 4]}])):
                for place in (old_choice, new_choice):
                    room = slots.available(config, FREE, ordinary)
                    bg = {"cores": sorted(place(config, room)[:background_cores]), "background": True}
                    claims = ordinary + [bg]
                    for wanted in range(1, 8):
                        with self.subTest(config=config["cores"], bg=bg["cores"], wanted=wanted, new=place is new_choice):
                            head = ticket("head", wanted, None)
                            predicted = slots._head_start(config, FREE, claims, head)
                            room_o = slots.available(config, FREE, claims, background=False)
                            if len(room_o) < wanted:
                                self.assertIsNone(predicted)
                                continue
                            self.assertEqual(predicted[0], set(room_o[:wanted]))
                            self.assertEqual(predicted[1], set(room_o[:wanted]) & set(bg["cores"]))

    def test_a_lone_shared_request_starts_as_on_main(self):
        # review round 1, finding 2: preference 0 to 3, keep_free 1, background on 0, a lone shared request (1 to 3)
        claims = [{"cores": [0], "background": True}]
        room = slots.available(CONFIG4, FREE, claims, background=False)
        guarantee = sorted(room[:1])                                             # run()'s ordinary choice
        base = {"id": "s", "lane": "l", "work_id": "w", "shared": True, "max_cores": 3, "background": False}
        record = slots._claim_record(base, guarantee, "below_normal", "t", "t", 0.0, CONFIG4, FREE, claims, None, True)
        self.assertEqual((record["guaranteed"], record["cores"]), ([0], [0, 1, 2]))

    def test_background_placement_changes_only_where_background_work_sits(self):
        """For a table of states: an admitted background request gets the same number of cores from the same room,
        the CI floor first, and the cores latest in the preference order when no reserve applies. In that case an
        ordinary request admitted next that fits in the cores no claim holds does not meet it at that admission
        (later ones still can, once other claims end). Ordinary choices, shared expansion and every admit-or-wait
        outcome are computed by main's code (available(), _claim_record) on the same claims."""
        bg = lambda *c: {"cores": list(c), "background": True}                   # noqa: E731
        no_play = {"cores": [7, 6, 5, 4, 1, 0], "keep_free": 0, "priority": "below_normal"}   # 2 and 3 reserved
        states = [(config8(), FREE, []), (config8(1), FREE, [{"cores": [7]}]), (FLOOR8, FREE, []),
                  (FLOOR8, FREE, [bg(1)]), (no_play, FREE, [{"cores": [7, 6]}]),
                  (config8(), {"held": True, "cores": [0, 1]}, [{"cores": [7]}]),
                  (config8(), FREE, [shared("s", [7], [7, 6, 5])]), (CONFIG4, FREE, [])]
        for config, timed, claims in states:
            room = slots.available(config, timed, claims)
            floor = set(slots.ci_floor_cores(config))
            for wanted in range(1, 7):
                if len(room) < wanted:
                    continue
                with self.subTest(config=config["cores"], timed=timed, claims=claims, wanted=wanted):
                    chosen = slots.background_order(config, room)[:wanted]
                    self.assertEqual(len(chosen), wanted)
                    self.assertLessEqual(set(chosen), set(room))
                    self.assertLessEqual(set(chosen), set(config["cores"]) - set(timed["cores"] if timed["held"] else []))
                    taken_floor = [c for c in chosen if c in floor]
                    self.assertEqual(taken_floor, [c for c in room if c in floor][:len(taken_floor)])
                    order = config["cores"]
                    rest = [c for c in chosen if c not in floor]
                    skipped = [c for c in room if c not in floor and c not in rest]
                    if config["keep_free"]:
                        self.assertEqual(chosen, room[:wanted])
                    elif rest and skipped:
                        self.assertGreater(min(order.index(c) for c in rest), max(order.index(c) for c in skipped))
                    after = claims + [{"cores": sorted(chosen), "background": True}]
                    ordinary_room = slots.available(config, timed, after, background=False)
                    if not config["keep_free"] and not floor and not any(c.get("background") for c in claims):
                        # ordinary work fills the front first and reaches this claim only when nothing else is left
                        for size in range(1, len(ordinary_room) - wanted + 1):
                            self.assertFalse(set(ordinary_room[:size]) & set(chosen))
                    for shared_max in (2, 3):
                        base = {"id": "s", "lane": "l", "work_id": "w", "shared": True, "max_cores": shared_max,
                                "background": False}
                        guarantee = sorted(ordinary_room[:1])
                        record = slots._claim_record(base, guarantee, "below_normal", "t", "t", 0.0, config, timed,
                                                     after, None, True)
                        self.assertEqual(record["guaranteed"], guarantee)
                        self.assertLessEqual(len(record["cores"]), shared_max)
                        self.assertLessEqual(set(record["cores"]) - set(guarantee),
                                             set(slots.unclaimed(config, timed, after + [{"cores": guarantee}])))

    def test_background_conflicts_with_live_ordinary_claims_even_before_start(self):
        with patch.object(slots, "conflicts", return_value=False), \
                patch.object(slots, "live_claims", return_value=[{"cores": [1], "state": "suspended"}]):
            self.assertTrue(slots.claim_conflicts([1], True))
            self.assertFalse(slots.claim_conflicts([2], True))
            self.assertFalse(slots.claim_conflicts([1], False))

    def test_partial_suspension_cannot_admit_foreground_work(self):
        with patch.object(slots, "live_claims", return_value=[
                {"id": "ci", "cores": [1], "background": True, "state": "running"}]):
            self.assertTrue(slots.background_busy([1], "build"))
        with patch.object(slots, "live_claims", return_value=[
                {"id": "ci", "cores": [1], "background": True, "state": "suspended"}]):
            self.assertFalse(slots.background_busy([1], "build"))


class BackgroundProcessTests(unittest.TestCase):
    setUp = HostSlotsTests.setUp
    tearDown = HostSlotsTests.tearDown
    def test_ci_suspends_for_ordinary_work_and_resumes_after_release(self):
        count = self.tmp_path / "background-count"
        release = self.tmp_path / "foreground-release"
        active = self.tmp_path / "foreground-active"
        ticker = script(self.tmp_path, "background-tick.py", "n = 0\nwhile True:\n    n += 1\n"
                        "    open(sys.argv[1], 'w').write(str(n))\n    time.sleep(0.02)\n")
        hold = script(self.tmp_path, "foreground-hold.py", "from pathlib import Path\n"
                      "Path(sys.argv[1]).write_text('up')\n"
                      "while not Path(sys.argv[2]).exists(): time.sleep(0.02)\n")
        ci = cli("run", "--background", "--priority", "idle", "--lane", "ci", "--work-id", "ci",
                 "--cores", "1", "--", sys.executable, ticker, str(count))
        foreground = None
        try:
            self.assertTrue(wait_for(lambda: counter(count) > 5))
            foreground = cli("run", "--lane", "build", "--work-id", "build", "--cores", str(len(CPUS)),
                             "--", sys.executable, hold, str(active), str(release))
            self.assertTrue(wait_for(active.exists))
            ci_claim = next(c for c in slots.status()["claims"] if c["lane"] == "ci")
            self.assertEqual(ci_claim["state"], "suspended")
            frozen = counter(count)
            time.sleep(0.2)
            self.assertEqual(counter(count), frozen)
            release.write_text("go")
            self.assertEqual(foreground.wait(timeout=30), 0)
            self.assertTrue(wait_for(lambda: counter(count) > frozen + 5))
        finally:
            release.write_text("go")
            if foreground:
                foreground.wait(timeout=30)
            ci.terminate()
            ci.wait(timeout=30)

    @needs_two_ut
    def test_background_work_sits_where_ordinary_work_comes_last(self):
        count = self.tmp_path / "background-count"
        release = self.tmp_path / "foreground-release"
        active = self.tmp_path / "foreground-active"
        ticker = script(self.tmp_path, "background-tick.py", "n = 0\nwhile True:\n    n += 1\n"
                        "    open(sys.argv[1], 'w').write(str(n))\n    time.sleep(0.02)\n")
        hold = script(self.tmp_path, "foreground-hold.py", "from pathlib import Path\n"
                      "Path(sys.argv[1]).write_text('up')\n"
                      "while not Path(sys.argv[2]).exists(): time.sleep(0.02)\n")
        ci = cli("run", "--background", "--priority", "idle", "--lane", "ci", "--work-id", "ci",
                 "--cores", "1", "--", sys.executable, ticker, str(count))
        foreground = None
        try:
            self.assertTrue(wait_for(lambda: counter(count) > 5))
            order = slots.load_config()["cores"]
            ci_cores = next(c for c in slots.status()["claims"] if c["lane"] == "ci")["cores"]
            self.assertEqual(ci_cores, [order[-1]])                  # the last core in the preference order
            foreground = cli("run", "--lane", "build", "--work-id", "build", "--cores", "1",
                             "--", sys.executable, hold, str(active), str(release))
            self.assertTrue(wait_for(active.exists))
            claims = {c["lane"]: c for c in slots.status()["claims"]}
            self.assertEqual(claims["build"]["cores"], [order[0]])  # ordinary work: the front, as on main
            self.assertEqual(claims["ci"]["state"], "running")
            moving = counter(count)
            self.assertTrue(wait_for(lambda: counter(count) > moving + 5))
            release.write_text("go")
            self.assertEqual(foreground.wait(timeout=30), 0)
        finally:
            release.write_text("go")
            if foreground:
                foreground.wait(timeout=30)
            ci.terminate()
            ci.wait(timeout=30)

    @unittest.skipUnless(os.name == "nt", "existing process adoption uses Windows jobs")
    def test_existing_worker_is_pinned_idle_and_claim_releases_at_exit(self):
        from ctypes import wintypes
        started, release, ready = (self.tmp_path / name for name in ("worker-started", "worker-release", "adopt-ready"))
        body = script(self.tmp_path, "existing-worker.py", "from pathlib import Path\n"
                      "Path(sys.argv[1]).write_text('up')\n"
                      "while not Path(sys.argv[2]).exists(): time.sleep(0.02)\n")
        # The fixture is an existing native worker, not the Windows venv
        # redirector and its separately contained interpreter descendant.
        worker_command = [getattr(sys, "_base_executable", sys.executable), body, str(started), str(release)]
        worker = None
        controller = None
        try:
            for _ in range(3):
                before = slots.process_table()
                worker = subprocess.Popen(worker_command)
                self.assertTrue(wait_for(lambda: started.exists() or worker.poll() is not None))
                self.assertTrue(started.exists(), "adoption fixture exited before signaling readiness")
                self.assertIsNone(worker.poll(), "adoption fixture exited before inspection")
                stamp = slots.creation_time(worker.pid)
                self.assertIsNotNone(stamp, "could not verify adoption fixture creation time")
                apparent_children = {pid: row for pid, row in slots.process_table().items()
                                     if row[0] == worker.pid}
                if not apparent_children:
                    break
                # The script is childless. Only replace a worker when every apparent
                # child was already linked to that PID and predates this worker.
                for pid, row in apparent_children.items():
                    self.assertEqual(before.get(pid), row, f"unexpected adoption fixture child {pid}")
                    child_stamp = slots.creation_time(pid)
                    self.assertIsNotNone(child_stamp, f"could not verify apparent child {pid}")
                    self.assertLess(child_stamp, stamp, f"unexpected adoption fixture child {pid}")
                release.write_text("go")
                self.assertEqual(worker.wait(timeout=30), 0)
                worker = None
                started.unlink()
                release.unlink()
            else:
                self.fail("could not start a childless adoption fixture in three attempts")

            identity = self.tmp_path / "worker.json"
            slots.write_json(identity, {"pid": worker.pid, "creation": stamp, "descendants": []})
            controller = cli("adopt", "--background", "--priority", "idle", "--lane", "ci", "--work-id", "adopt",
                             "--cores", "1", "--worker", str(identity), "--ready", str(ready))
            wait_for(lambda: ready.exists() or controller.poll() is not None)
            if not ready.exists():
                if controller.poll() is None:
                    controller.terminate()
                out, err = controller.communicate(timeout=30)
                self.fail(f"adoption did not become ready; exit={controller.returncode}; stdout={out}; stderr={err}")
            admitted = slots.read_json(ready)
            self.assertEqual(admitted["worker_creation"], stamp)
            handle = slots._OpenProcess(slots.PROCESS_QUERY_LIMITED_INFORMATION, False, worker.pid)
            try:
                affinity, system = slots.ctypes.c_size_t(0), slots.ctypes.c_size_t(0)
                self.assertTrue(slots._GetProcessAffinityMask(handle, slots.ctypes.byref(affinity), slots.ctypes.byref(system)))
                self.assertEqual(affinity.value, 1 << CPUS[0])   # background work: the last core in the order
                get_priority = slots._fn(slots._k32, "GetPriorityClass", wintypes.DWORD, wintypes.HANDLE)
                self.assertEqual(get_priority(handle), slots.PRIORITY_CLASS["idle"])
            finally:
                slots._CloseHandle(handle)
            release.write_text("go")
            self.assertEqual(worker.wait(timeout=30), 0)
            out, err = controller.communicate(timeout=30)
            self.assertEqual(controller.returncode, 0, f"stdout={out}; stderr={err}")
            self.assertEqual(slots.status()["claims"], [])
            self.assertFalse(ready.exists())
        finally:
            try:
                if worker is not None and worker.poll() is None:
                    release.write_text("go")
                    try:
                        worker.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        worker.kill()
                        worker.wait(timeout=30)
                        raise
            finally:
                if controller and controller.poll() is None:
                    controller.terminate()
                    controller.wait(timeout=30)


class OrdinaryAdmissionPathTests(unittest.TestCase):
    """review round 2 (P3): the real ordinary admission in run(), beside background claims placed by both the old
    rule (front of the order) and the new one (far end), publishes exactly the cores the backfill engine predicts
    for that head (_head_start), and a shared request's guarantee and expansion follow main's code. A change to
    run()'s ordinary core choice makes this fail."""
    setUp = HostSlotsTests.setUp
    tearDown = HostSlotsTests.tearDown

    def write(self, cid, cores, background):
        pid, creation = slots.self_identity()
        slots.write_json(self.host / f"TESTHOST.slots/claim-{cid}.json", {
            "schema": slots.SCHEMA, "id": cid, "pid": pid, "creation_time": creation, "lane": "l",
            "work_id": f"w-{cid[:4]}", "cores": cores, "background": background, "priority": "below_normal",
            "state": "running", "acquired_at": slots.now_utc(), **({"draining": False} if background else {})})

    def admit(self, wanted, **kwargs):
        seen = []
        with patch.object(slots, "_run_claimed",
                          side_effect=lambda claim, *a, **k: seen.append(slots.read_json(claim)) or 0):
            slots.run("l", "probe", wanted, ["unused"], **kwargs)
        self.assertEqual(len(seen), 1)
        return seen[0]

    def test_ordinary_admission_matches_the_prediction_beside_old_and_new_background_placements(self):
        slots.write_json(self.host / "TESTHOST.slots/config.json", {"cores": "7-0", "lending": True})
        with patch.object(slots, "cpu_total", return_value=8):
            config = slots.load_config()
            self.write("1" * 32, [7], False)                                   # an ordinary claim on the first core
            room = slots.available(config, FREE, slots.live_claims())
            old_placed = sorted(room[:1])                                        # main's background choice
            new_placed = sorted(slots.background_order(config, room)[:1])        # this change's choice
            self.assertEqual((old_placed, new_placed), ([6], [0]))
            self.write("2" * 32, old_placed, True)
            self.write("3" * 32, new_placed, True)
            claims = slots.live_claims()
            self.assertEqual(len(claims), 3)
            for wanted in (1, 3, 5):
                with self.subTest(wanted=wanted):
                    predicted, handoffs = slots._head_start(config, FREE, claims, {"id": "h", "cores_wanted": wanted})
                    record = self.admit(wanted)
                    self.assertEqual(record["cores"], sorted(predicted))
                    self.assertEqual(handoffs, set(record["cores"]) & {6, 0})
                    self.assertEqual(len(slots.live_claims()), 3)                # the probe's claim was released
            # main's order: the first free cores in preference order, the old-placed background core included
            self.assertEqual(sorted(slots._head_start(config, FREE, claims, {"id": "h", "cores_wanted": 3})[0]),
                             [4, 5, 6])
            # a shared request (1 to 3): its guarantee is the predicted ordinary choice, its expansion main's
            predicted, _ = slots._head_start(config, FREE, claims, {"id": "h", "cores_wanted": 1})
            record = self.admit(3, shared=True, min_cores=1)
            self.assertEqual(record["guaranteed"], sorted(predicted))
            self.assertEqual(record["guaranteed"], [6])
            extra = slots.unclaimed(config, FREE, claims + [{"id": "x", "cores": record["guaranteed"]}])[:2]
            self.assertEqual(record["cores"], sorted(record["guaranteed"] + extra))
            self.assertEqual(record["cores"], [4, 5, 6])


def snapshot_of(tickets, claims=()):
    """A `_snapshot` result with these live tickets and claims and nothing unreadable."""
    return {"tickets": list(tickets), "claims": list(claims), "unreadable": set(), "names": set(), "records": {}}




class BackfillAdmissionTests(unittest.TestCase):
    setUp = HostSlotsTests.setUp

    @needs_three
    def test_run_records_the_backfill_and_the_head_it_jumped(self):
        own = "a" * 32
        head = {"id": "b" * 32, "cores_wanted": len(CPUS), "background": False,
                "config_sha256": slots.config_digest(slots.load_config())}
        tickets = [head, {"id": own, "cores_wanted": 1, "background": False, "max_seconds": 30.0}]
        holder = {"id": "c" * 32, "cores": CPUS[1:], "background": False}
        seen, announced = [], []
        with patch.object(slots, "_snapshot", side_effect=lambda: snapshot_of(tickets, [holder])), \
                patch.object(slots, "_run_claimed", side_effect=lambda claim, *a, **k: seen.append(
                    slots.read_json(claim)) or 0):
            # the head wants every CPU: with the backfill still running it could never start, so no backfill
            with self.assertRaises(slots.NoRoom):
                slots.run("probe", "small", 1, ["unused"], claim_id=own, max_seconds=30.0)
            head["cores_wanted"] = len(CPUS) - 1
            self.assertEqual(slots.run("probe", "small", 1, ["unused"], claim_id=own, max_seconds=30.0,
                                       on_claim=announced.append), 0)
        record = seen[0]
        self.assertTrue(record["backfill"])
        self.assertEqual((record["head_id"], record["max_seconds"], record["cores"]), ("b" * 32, 30.0, [CPUS[0]]))
        self.assertTrue(announced[0]["backfill"])
        self.assertFalse(list((self.host / "TESTHOST.slots").glob("claim-*.json")))

    def test_an_invalid_limit_is_refused_before_queueing_or_launching(self):
        for bad in (0, -1, float("nan"), slots.BACKFILL_MAX_SECONDS * 2):
            with self.assertRaises(ValueError):
                slots.run("probe", "bad", 1, ["unused"], max_seconds=bad)
        self.assertFalse(list((self.host / "TESTHOST.slots").glob("queue-*.json")))
        log = self.tmp_path / "submit.log"
        out = subprocess.run([sys.executable, str(TOOLS / "host_slots_v1.py"), "submit", "--log", str(log),
                              "--max-seconds", "0", "--lane", "l", "--work-id", "w", "--cores", "1", "--",
                              sys.executable, "-c", "pass"], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, slots.EXIT_USAGE, out.stderr)
        self.assertFalse(log.exists())

    def test_a_new_ticket_always_queues_after_every_published_ticket(self):
        # review r4: the name is chosen under the mutex at publication, never earlier
        ahead = f"queue-{time.time_ns() + 10**12:020d}-{'e' * 32}.json"
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()  # its ticket is reaped when read, so the new request can then enter
        slots.write_json(self.host / "TESTHOST.slots" / ahead, {"id": "e" * 32, "pid": gone.pid, "creation_time": 1,
                                                                "cores_wanted": 1})
        background = f"queue-z-{time.time_ns() + 2 * 10**12:020d}-{'d' * 32}.json"
        slots.write_json(self.host / "TESTHOST.slots" / background, {"id": "d" * 32, "pid": gone.pid,
                                                                     "creation_time": 1, "cores_wanted": 1})
        for queue_class in ("", "z-"):  # after every ticket, ordinary or background
            stamp = slots._ticket_path(queue_class, "f" * 32).name.removeprefix("queue-").removeprefix("z-")
            self.assertGreater(stamp, background.removeprefix("queue-z-"))
        seen = []
        real_path, real_write = slots._ticket_path, slots.write_json

        def named_under_the_mutex(*args):
            seen.append((self.host / "TESTHOST.slots" / ".mutex").is_dir())
            return real_path(*args)
        published = []
        with patch.object(slots, "_ticket_path", side_effect=named_under_the_mutex), \
                patch.object(slots, "write_json", side_effect=lambda path, value: (
                    published.append(Path(path).name), real_write(path, value))[1]), \
                patch.object(slots, "_run_claimed", return_value=0):
            slots.run("probe", "late", 1, ["unused"], claim_id="f" * 32, wait=True)
        self.assertEqual(seen, [True])
        ticket = [name for name in published if name.startswith("queue-")][0]
        self.assertGreater(ticket.removeprefix("queue-"), background.removeprefix("queue-z-"))

    def test_ordinary_claim_records_are_unchanged(self):
        seen = []
        with patch.object(slots, "_run_claimed", side_effect=lambda claim, *a, **k: seen.append(
                slots.read_json(claim)) or 0):
            slots.run("probe", "plain", 1, ["unused"], claim_id="d" * 32)
        # Additive only: when it queued and how long (no backfill, shared or pool fields).
        self.assertEqual(set(seen[0]), {"schema", "id", "lane", "work_id", "pid", "creation_time", "background",
                                        "cores", "priority", "state", "acquired_at", "enqueued_at",
                                        "queued_seconds"})

    def test_run_records_the_bounded_terms_and_the_window(self):
        # review r1: through run(), not only the admission function
        pid, creation = slots.self_identity()
        head_id = "a" * 32
        config = slots.load_config()
        slots.write_json(self.host / f"TESTHOST.slots/queue-{1:020d}-{head_id}.json", {
            "schema": slots.SCHEMA, "id": head_id, "lane": "l", "work_id": "head", "pid": pid,
            "creation_time": creation, "background": False, "cores_wanted": 1, "max_seconds": 3600.0,
            "enqueued_at": slots.now_utc(), "config_sha256": slots.config_digest(config)})
        terms = {"delays_head": head_id, "delay_bound_seconds": 60.0, "delay_limit_seconds": 360.0,
                 "deadline_mono": 1060.0, "delay_window": {"head_id": head_id, "start_mono": 1000.0,
                                                           "end_mono": 1060.0}}
        seen, given = [], []

        def admission(*args):
            given.append(args)
            return [CPUS[-1]], terms
        with patch.object(slots, "backfill_admission", side_effect=admission), \
                patch.object(slots, "_run_claimed", side_effect=lambda claim, *a, **k: seen.append(
                    slots.read_json(claim)) or 0):
            slots.run("probe", "bf", 1, ["unused"], claim_id="b" * 32, wait=True, max_seconds=60.0,
                      on_overdue="demote")   # a bounded delay needs an enforced limit
        claim = seen[0]
        self.assertEqual((claim["head_id"], claim["delays_head"], claim["delay_bound_seconds"],
                          claim["delay_limit_seconds"], claim["deadline_mono"]), (head_id, head_id, 60.0, 360.0, 1060.0))
        self.assertNotIn("delay_window", claim)
        self.assertEqual(slots.read_json(self.host / f"TESTHOST.slots/delay-{head_id}.json"), terms["delay_window"])
        self.assertIsNone(given[0][6])                       # no window was persisted before this admission
        own = [t for t in given[0][3] if t["id"] == "b" * 32][0]
        self.assertEqual(own["backfill_policy"], slots.BACKFILL_POLICY)

    def test_windows_of_heads_that_left_are_pruned(self):
        d = self.host / "TESTHOST.slots"
        slots.write_json(d / f"delay-{'c' * 32}.json", {"head_id": "c" * 32})
        slots.write_json(d / f"delay-{'d' * 32}.json", {"head_id": "d" * 32})
        (d / f"queue-{1:020d}-{'d' * 32}.json").write_text("{ unreadable")   # review r2: still present
        snap = slots._snapshot()
        self.assertEqual(snap["unreadable"], {f"queue-{1:020d}-{'d' * 32}.json"})
        slots._prune_delay_windows(snap)
        self.assertFalse((d / f"delay-{'c' * 32}.json").exists())
        self.assertTrue((d / f"delay-{'d' * 32}.json").exists())

    def test_a_failed_folder_scan_admits_nothing(self):
        # review r4: Path.glob returns nothing on a listing error; the scan must fail instead
        with patch.object(slots.os, "scandir", side_effect=PermissionError("denied")):
            self.assertIsNone(slots._snapshot())
            with self.assertRaises(slots.NoRoom):
                slots.run("probe", "head", 1, ["unused"], claim_id="b" * 32, wait=True, wait_timeout=0.3)

    def test_no_request_starts_behind_an_unreadable_queue_file(self):
        # review r4: an unreadable true head must not let the next request start as head
        (self.host / f"TESTHOST.slots/queue-{1:020d}-{'9' * 32}.json").write_text("{ torn")
        with patch.object(slots, "_run_claimed", return_value=0) as ran:
            with self.assertRaises(slots.NoRoom):
                slots.run("probe", "next", 1, ["unused"], claim_id="b" * 32, wait=True, wait_timeout=0.3)
        ran.assert_not_called()

    def test_nothing_backfills_while_a_claim_file_is_unreadable(self):
        # review r4: an unreadable delaying backfill's claim would escape the overdue guard
        (self.host / f"TESTHOST.slots/claim-{'8' * 32}.json").write_text("{ torn")
        self.write_head("a" * 32)
        with patch.object(slots, "backfill_admission") as admission, \
                patch.object(slots, "available", return_value=[]):
            with self.assertRaises(slots.NoRoom):
                slots.run("probe", "bf", 1, ["unused"], claim_id="b" * 32, wait=True, wait_timeout=0.3,
                          max_seconds=60.0)
        admission.assert_not_called()

    def test_an_unreadable_window_refuses_every_delaying_backfill(self):
        # review r2: a failed read must not start a fresh window
        d = self.host / "TESTHOST.slots"
        self.assertIsNone(slots._snapshot_window(slots._snapshot(), "e" * 32))
        (d / f"delay-{'e' * 32}.json").write_text("{ torn")
        window = slots._snapshot_window(slots._snapshot(), "e" * 32)
        self.assertEqual(window, {"unreadable": True})
        head = {**ticket("e" * 32, 4, 3600.0), "config_sha256": slots.config_digest(config8())}
        self.assertIsNone(slots.backfill_admission(config8(), FREE, BoundedDelayBackfillTests.CLAIMS,
                                                   [head, bounded("t", 2, 60.0)], "t", 1000.0, window))

    def test_a_window_whose_metadata_cannot_be_read_refuses(self):
        # review r3: Path.exists() is False on a permission error; only a confirmed absence is "no window"
        slots.write_json(self.host / f"TESTHOST.slots/delay-{'e' * 32}.json", {"head_id": "e" * 32})
        real_stat, real_read = slots.os.stat, slots.read_json

        def denied(path, *a, **k):
            if str(path).endswith(f"delay-{'e' * 32}.json"):
                raise PermissionError("denied")
            return real_stat(path, *a, **k)
        with patch.object(slots.os, "stat", side_effect=denied), \
                patch.object(slots, "read_json", side_effect=lambda path: None if str(path).endswith(
                    f"delay-{'e' * 32}.json") else real_read(path)):
            self.assertEqual(slots._snapshot_window(slots._snapshot(), "e" * 32), {"unreadable": True})

    def test_a_read_that_fails_once_never_drops_a_record_from_the_decision(self):
        # review r5: every file is read once per poll, so a transient failure is seen as unreadable, never as
        # an absent head ticket or an absent claim
        self.write_head("a" * 32, stamp=1)
        head_name = f"queue-{1:020d}-{'a' * 32}.json"
        real_read, failed = slots.read_json, []

        def once(path):
            if Path(path).name == head_name and not failed:
                failed.append(path)
                return None
            return real_read(path)
        with patch.object(slots, "read_json", side_effect=once):
            snap = slots._snapshot()
        self.assertIn(head_name, snap["unreadable"])
        self.assertEqual([t["id"] for t in snap["tickets"]], [])
        self.assertEqual(len(failed), 1)

    def write_head(self, head_id, stamp=2):
        pid, creation = slots.self_identity()
        slots.write_json(self.host / f"TESTHOST.slots/queue-{stamp:020d}-{head_id}.json", {
            "schema": slots.SCHEMA, "id": head_id, "lane": "l", "work_id": "head", "pid": pid,
            "creation_time": creation, "background": False, "cores_wanted": 1, "max_seconds": 3600.0,
            "enqueued_at": slots.now_utc(), "config_sha256": slots.config_digest(slots.load_config())})

    def test_nothing_backfills_while_a_queue_file_is_unreadable(self):
        # review r3: an unreadable head ticket would hand admission to the next ticket's fresh budget
        (self.host / f"TESTHOST.slots/queue-{1:020d}-{'9' * 32}.json").write_text("{ torn")
        self.write_head("a" * 32)
        with patch.object(slots, "backfill_admission") as admission, \
                patch.object(slots, "available", return_value=[]):
            with self.assertRaises(slots.NoRoom):
                slots.run("probe", "bf", 1, ["unused"], claim_id="b" * 32, wait=True, wait_timeout=0.3,
                          max_seconds=60.0)
        admission.assert_not_called()

    def test_every_new_backfill_records_a_monotonic_deadline(self):
        # review r3: zero-delay backfills too, so status can flag them overdue after a wall-clock change
        self.write_head("a" * 32)
        seen = []
        before = slots.time.monotonic()
        with patch.object(slots, "backfill_admission", return_value=([CPUS[-1]], None)), \
                patch.object(slots, "_run_claimed", side_effect=lambda claim, *a, **k: seen.append(
                    slots.read_json(claim)) or 0):
            slots.run("probe", "bf", 1, ["unused"], claim_id="b" * 32, wait=True, max_seconds=60.0)
        self.assertNotIn("delays_head", seen[0])
        self.assertGreaterEqual(seen[0]["deadline_mono"], before + 60.0)
        self.assertLessEqual(seen[0]["deadline_mono"], slots.time.monotonic() + 60.0)

    def test_status_uses_the_monotonic_deadline(self):
        # review r2: a wall-clock rollback must not hide an overdue backfill
        pid, creation = slots.self_identity()
        base = {"schema": slots.SCHEMA, "pid": pid, "creation_time": creation, "lane": "l", "work_id": "w",
                "background": False, "priority": "below_normal", "state": "running", "acquired_at": slots.now_utc(),
                "backfill": True, "max_seconds": 60.0, "head_id": "f" * 32,
                "deadline_at": "9999-01-01T00:00:00.000+00:00"}
        slots.write_json(self.host / f"TESTHOST.slots/claim-{'5' * 32}.json", {
            **base, "id": "5" * 32, "cores": [CPUS[-1]], "deadline_mono": slots.time.monotonic() - 1.0})
        rows = {b["id"]: b["overdue"] for b in slots.status()["backfill"]}
        self.assertEqual(rows, {"5" * 32: True})

    def test_status_shows_each_backfills_delay_bound(self):
        pid, creation = slots.self_identity()
        base = {"schema": slots.SCHEMA, "pid": pid, "creation_time": creation, "lane": "l", "work_id": "w",
                "background": False, "priority": "below_normal", "state": "running", "acquired_at": slots.now_utc(),
                "backfill": True, "max_seconds": 300.0, "head_id": "f" * 32,
                "deadline_at": "9999-01-01T00:00:00.000+00:00"}
        slots.write_json(self.host / f"TESTHOST.slots/claim-{'3' * 32}.json", {**base, "id": "3" * 32,
                         "cores": [CPUS[-1]], "delays_head": "f" * 32, "delay_bound_seconds": 300.0,
                         "delay_limit_seconds": 360.0})
        slots.write_json(self.host / f"TESTHOST.slots/claim-{'4' * 32}.json", {**base, "id": "4" * 32,
                         "cores": [CPUS[0]]})
        rows = {b["id"]: (b["delay_bound_seconds"], b["delay_limit_seconds"]) for b in slots.status()["backfill"]}
        self.assertEqual(rows, {"3" * 32: (300.0, 360.0), "4" * 32: (0.0, None)})

    def test_status_flags_an_overdue_backfill_and_keeps_it(self):
        pid, creation = slots.self_identity()
        base = {"schema": slots.SCHEMA, "pid": pid, "creation_time": creation, "lane": "l", "work_id": "w",
                "background": False, "priority": "below_normal", "state": "running", "acquired_at": slots.now_utc()}
        slots.write_json(self.host / f"TESTHOST.slots/claim-{'e' * 32}.json", {
            **base, "id": "e" * 32, "cores": [CPUS[-1]], "backfill": True, "max_seconds": 1.0,
            "head_id": "f" * 32, "deadline_at": "2026-01-01T00:00:00.000+00:00"})
        slots.write_json(self.host / f"TESTHOST.slots/claim-{'1' * 32}.json", {
            **base, "id": "1" * 32, "cores": [CPUS[0]]})  # a record from before backfill: not a backfill
        slots.write_json(self.host / f"TESTHOST.slots/claim-{'2' * 32}.json", {
            **base, "id": "2" * 32, "cores": [CPUS[0]], "backfill": True, "max_seconds": 600.0,
            "head_id": "f" * 32, "deadline_at": "9999-01-01T00:00:00.000+00:00"})
        status = slots.status()
        self.assertEqual(sorted((b["id"], b["overdue"], b["head_id"]) for b in status["backfill"]),
                         [("2" * 32, False, "f" * 32), ("e" * 32, True, "f" * 32)])
        self.assertEqual(len(status["claims"]), 3)  # flagged, never removed or stopped


def bounded(name, wanted, max_seconds=60.0, **extra):
    """A request from a launcher that applies the bounded-delay rule."""
    return ticket(name, wanted, max_seconds, backfill_policy=slots.BACKFILL_POLICY, **extra)


class BoundedDelayBackfillTests(unittest.TestCase):
    """A backfill that could delay the head starts only when every delaying backfill for that head fits in one
    persisted window, on the monotonic clock, of at most min(15 minutes, 10% of the head's declared limit)."""
    # Releasing either claim alone lets a 4-core head start without the backfill (5 free) but not with it.
    CLAIMS = [{"cores": [7, 6, 5]}, {"cores": [4, 3, 2]}]

    def admit(self, claims, head, small, now=1000.0, window=None, tickets=None):
        tickets = tickets or [head, small]
        tickets = [{**tickets[0], "config_sha256": slots.config_digest(config8())}, *tickets[1:]]
        return slots.backfill_admission(config8(), FREE, claims, tickets, small["id"], now, window)

    def test_a_delay_within_the_bound_is_admitted_with_its_terms(self):
        head = ticket("head", 4, 3600.0)                   # limit min(900, 360) = 360 s
        cores, terms = self.admit(self.CLAIMS, head, bounded("t", 2, 300.0))
        self.assertEqual(cores, [0, 1])
        self.assertEqual(terms, {"delays_head": "head", "delay_bound_seconds": 300.0, "delay_limit_seconds": 360.0,
                                 "deadline_mono": 1300.0,
                                 "delay_window": {"head_id": "head", "start_mono": 1000.0, "end_mono": 1300.0}})
        self.assertIsNone(self.admit(self.CLAIMS, head, bounded("t", 2, 361.0)))
        long_head = ticket("head", 4, 36000.0)             # limit min(900, 3600) = 900 s
        self.assertEqual(self.admit(self.CLAIMS, long_head, bounded("t", 2, 900.0))[1]["delay_limit_seconds"], 900.0)
        self.assertIsNone(self.admit(self.CLAIMS, long_head, bounded("t", 2, 901.0)))

    def test_the_window_persists_after_its_backfills_end(self):
        # review r1: windows rebuilt from live claims slid forward as backfills ended (the head waited 661 s
        # under a 360 s limit). A 2-core backfill here delays the head.
        head = ticket("head", 4, 3600.0)
        window = self.admit(self.CLAIMS, head, bounded("a", 2, 300.0), now=0.0)[1]["delay_window"]
        self.assertEqual((window["start_mono"], window["end_mono"]), (0.0, 300.0))
        # a has ended; the persisted window still starts at 0
        self.assertIsNone(self.admit(self.CLAIMS, head, bounded("b", 2, 60.0), now=301.0, window=window))
        terms = self.admit(self.CLAIMS, head, bounded("b", 2, 59.0), now=301.0, window=window)[1]
        self.assertEqual((terms["delay_bound_seconds"], terms["delay_window"]["start_mono"]), (360.0, 0.0))

    def test_a_window_from_before_a_restart_or_another_head_refuses(self):
        head = ticket("head", 4, 36000.0)
        for window in ({"head_id": "head", "start_mono": 5000.0, "end_mono": 5100.0},   # monotonic clock reset
                       {"head_id": "other", "start_mono": 900.0, "end_mono": 950.0},
                       {"head_id": "head", "start_mono": "x", "end_mono": 950.0},
                       {"head_id": "head", "start_mono": 990.0, "end_mono": 980.0}):
            with self.subTest(window=window):
                self.assertIsNone(self.admit(self.CLAIMS, head, bounded("t", 2, 60.0), window=window))
        # the same request with no persisted window starts under fresh terms
        self.assertIsNotNone(self.admit(self.CLAIMS, head, bounded("t", 2, 60.0))[1])

    def test_a_head_without_a_declared_limit_gets_no_delaying_backfill(self):
        self.assertIsNone(self.admit(self.CLAIMS, ticket("head", 4, None), bounded("t", 2, 60.0)))

    def test_a_backfill_that_cannot_delay_carries_no_terms(self):
        claims = [{"cores": [7, 6, 5, 4, 3, 2]}]
        self.assertEqual(self.admit(claims, ticket("head", 4, 3600.0), bounded("t", 2, 60.0)), ([0, 1], None))

    def test_a_live_delaying_backfill_that_is_overdue_or_unreadable_refuses(self):
        head = ticket("head", 4, 36000.0)
        window = {"head_id": "head", "start_mono": 900.0, "end_mono": 990.0}
        for deadline in (999.0, None, "soon", True):
            claims = [*self.CLAIMS, {"cores": [1], "backfill": True, "delays_head": "head", "deadline_mono": deadline}]
            with self.subTest(deadline=deadline):
                self.assertIsNone(self.admit(claims, head, bounded("t", 1, 60.0), window=window))
        claims = [*self.CLAIMS, {"cores": [1], "backfill": True, "delays_head": "head", "deadline_mono": 1050.0}]
        self.assertEqual(self.admit(claims, head, bounded("t", 1, 60.0), window=window)[1]["delay_bound_seconds"],
                         160.0)

    def test_a_head_that_can_start_now_is_never_jumped(self):
        # review r1: also by a backfill that would leave it room
        head = ticket("head", 4, 36000.0)
        self.assertIsNone(self.admit([{"cores": [7, 6, 5, 4]}], head, bounded("t", 2, 60.0)))
        self.assertIsNone(self.admit([], head, bounded("t", 2, 60.0)))

    def test_an_older_launchers_ticket_is_judged_by_its_own_rule(self):
        # review r1: eight cores, two 3-core claims, a 4-core head; the old launcher's delaying request must not
        # be treated as eligible, or the 1-core request behind it would wait too
        head, old, new = ticket("head", 4, 3600.0), ticket("old", 2, 300.0), bounded("new", 1, 60.0)
        self.assertIsNone(self.admit(self.CLAIMS, head, old, tickets=[head, old, new]))
        self.assertEqual(self.admit(self.CLAIMS, head, new, tickets=[head, old, new]), ([1], None))

    def test_timed_reservations_still_stop_every_backfill(self):
        head = {**ticket("head", 4, 36000.0), "config_sha256": slots.config_digest(config8())}
        self.assertIsNone(slots.backfill_admission(config8(), {"held": True, "cores": [0]}, self.CLAIMS,
                                                   [head, bounded("t", 2, 60.0)], "t", 1000.0))


class BackfillProcessTests(unittest.TestCase):
    setUp = HostSlotsTests.setUp

    @needs_three
    def test_small_job_runs_while_the_head_waits_and_the_head_still_starts(self):
        host, tmp_path = self.host, self.tmp_path
        hold = script(tmp_path, "bf-hold.py", "Path = __import__('pathlib').Path\nPath(sys.argv[1]).write_text('up')\n"
                                              "while not Path(sys.argv[2]).exists(): time.sleep(0.05)\n")
        up, release = tmp_path / "up", tmp_path / "release"
        small_up, small_release = tmp_path / "small-up", tmp_path / "small-release"
        holder = cli("run", "--lane", "l", "--work-id", "holder", "--cores", str(len(CPUS) - 1), "--",
                     sys.executable, hold, str(up), str(release))
        waiters = []
        try:
            assert wait_for(up.exists)
            head = cli("run", "--wait", "--lane", "l", "--work-id", "head", "--cores", str(len(CPUS) - 1),
                       "--", sys.executable, "-c", "pass")
            waiters.append(head)
            assert wait_for(lambda: len(list((host / "TESTHOST.slots").glob("queue-*.json"))) == 1)
            plain = cli("run", "--wait", "--lane", "l", "--work-id", "plain", "--cores", "1", "--",
                        sys.executable, "-c", "pass")
            waiters.append(plain)
            assert wait_for(lambda: len(list((host / "TESTHOST.slots").glob("queue-*.json"))) == 2)
            small = cli("run", "--wait", "--max-seconds", "120", "--lane", "l", "--work-id", "small", "--cores", "1",
                        "--", sys.executable, hold, str(small_up), str(small_release))
            waiters.append(small)
            assert wait_for(small_up.exists)
            self.assertTrue(json.loads(small.stdout.readline())["backfill"])
            status = slots.status()
            self.assertEqual([b["work_id"] for b in status["backfill"]], ["small"])
            # the request without a declared limit is still queued behind the head
            self.assertEqual([t["work_id"] for t in status["queue"]], ["head", "plain"])
            # the holder ends while the backfill still runs: the head must start at once
            release.write_text("go")
            self.assertEqual(head.wait(timeout=60), 0)
            self.assertIsNone(small.poll())
            small_release.write_text("go")
            for waiter in waiters:
                self.assertEqual(waiter.wait(timeout=60), 0)
        finally:
            release.write_text("go")
            small_release.write_text("go")
            holder.wait(timeout=60)
            for waiter in waiters:
                if waiter.poll() is None:
                    waiter.kill()
                    waiter.wait(timeout=30)


# ---------------------------------------------------------------- shared claims, pool reasons, watcher


def shared(cid, guaranteed, cores, state="running", **extra):
    return {"id": cid, "shared": True, "guaranteed": guaranteed, "cores": cores, "state": state,
            "background": False, **extra}


CONFIG4 = {"cores": [0, 1, 2, 3], "keep_free": 1, "priority": "below_normal"}


class SharedPolicyTests(unittest.TestCase):
    """A shared claim holds its guarantee and lends the rest of its current cores."""

    def test_lent_cores_are_free_to_ordinary_and_background_requests(self):
        claim = shared("s", [7], [7, 6, 5, 4])
        assert slots.held(claim) == [7] and slots.lent(claim) == [6, 5, 4]
        assert slots.available(config8(), FREE, [claim], background=False) == [6, 5, 4, 3, 2, 1, 0]
        assert slots.available(config8(), FREE, [claim]) == [6, 5, 4, 3, 2, 1, 0]
        # growth sees only cores no claim runs on
        assert slots.unclaimed(config8(), FREE, [claim]) == [3, 2, 1, 0]

    def test_a_malformed_guarantee_holds_every_core(self):
        for bad in (None, [], [9], [7, 7], [True], "7"):
            claim = shared("s", bad, [7, 6])
            assert slots.held(claim) == [7, 6] and slots.lent(claim) == []
        assert slots.held({"cores": [3, 2], "guaranteed": [3]}) == [3, 2]  # only a shared record lends

    def test_give_back_covers_timed_work_and_every_other_claim(self):
        me = shared("s", [7], [7, 6, 5, 4])
        assert slots.give_back(me, {"held": True, "cores": [6]}, [me]) == [6]
        assert slots.give_back(me, {"held": True, "cores": None}, [me]) == [4, 5, 6]
        assert slots.give_back(me, FREE, [me, {"id": "o", "cores": [5]}]) == [5]
        assert slots.give_back(me, FREE, [me, {"id": "b", "cores": [4], "background": True}]) == [4]
        # another shared claim's guarantee takes a lent core; its own lent cores never overlap by construction
        assert slots.give_back(me, FREE, [me, shared("t", [5], [5, 3])]) == [5]
        assert slots.give_back(me, FREE, [me, shared("t", [3], [3, 2])]) == []

    def test_every_lent_core_goes_back_while_anything_is_queued(self):
        me = shared("s", [7], [7, 6, 5])
        assert slots.give_back(me, FREE, [me], config8(), queued=True) == [5, 6]
        assert slots.give_back(me, FREE, [me], config8(), queued=False) == []

    def test_keep_free_is_never_consumed_through_lending(self):
        # review v1 #1: four CPUs, keep_free 1, S guarantees 0 and lends 1 and 2, a request restricted to 3
        lender = shared("s", [0], [0, 1, 2])
        assert slots.available(CONFIG4, FREE, [lender], core_pool=[3]) == [3]
        claims = [lender, {"id": "o", "cores": [3], "state": "suspended"}]
        assert slots.over_budget(CONFIG4, claims) == 1
        assert slots.budget_pending(CONFIG4, claims, "o")      # the new claim waits
        assert slots.give_back(lender, FREE, claims, CONFIG4) == [2]  # least preferred lent core first
        claims[0] = shared("s", [0], [0, 1])
        assert slots.over_budget(CONFIG4, claims) == 0 and not slots.budget_pending(CONFIG4, claims, "o")
        # a lender that gave everything back no longer holds anyone up
        claims[0] = shared("s", [0], [0])
        claims.append({"id": "x", "cores": [1, 2]})
        assert slots.over_budget(CONFIG4, claims) == 1 and not slots.budget_pending(CONFIG4, claims, "o")

    def test_suspended_background_claims_count_against_the_budget(self):
        # review v2 #2: a suspended background claim resumes on its own, so growth leaves it room
        background = {"id": "b", "cores": [2], "background": True, "state": "suspended"}
        assert slots.unclaimed(CONFIG4, FREE, [background, shared("s", [0], [0])]) == [1]
        assert slots.over_budget(CONFIG4, [background, shared("s", [0], [0, 1, 3])]) == 1

    def test_no_backfill_is_proved_while_any_core_is_lent(self):
        # review v1 #2 and v2 #3: lender handoffs never enter a backfill proof
        config = {"cores": [4, 3, 2, 1, 0], "keep_free": 0, "priority": "below_normal"}
        head = ticket("head", 3, None, core_pool=[1, 2, 3, 4])
        claims = [{"id": "c", "cores": [4, 3]}, shared("s", [0], [0, 1])]
        assert admits(config, FREE, claims, [head, ticket("b", 1)], "b") is None
        claims[1] = {"id": "s", "cores": [0]}       # the same host without lending
        assert admits(config, FREE, claims, [head, ticket("b", 1)], "b") == [2]
        claims[1] = shared("s", [0], [0], state="suspended")
        assert admits(config, FREE, claims, [head, ticket("b", 1)], "b") == [2]

    def test_the_head_counts_lent_cores_and_budget_room_as_handoffs(self):
        config = {"cores": [3, 2, 1, 0], "keep_free": 1, "priority": "below_normal"}
        lender = shared("s", [0], [0, 1])
        assert slots._head_start(config, FREE, [lender], ticket("h", 2, None)) == ({3, 2}, {-1})
        assert slots._head_start(config, FREE, [lender], ticket("h", 3, None)) is None
        assert slots._head_start(config8(), FREE, [shared("s", [7], [7, 6])], ticket("h", 2, None)) == ({6, 5}, {6})

    def test_a_shared_request_starts_wide_only_when_nothing_else_is_queued(self):
        base = {"id": "x", "shared": True, "max_cores": 4, "background": False}
        record = slots._claim_record(base, [7], "below_normal", "a", "e", 0.0, config8(), FREE, [], None, True)
        assert record["guaranteed"] == [7] and record["cores"] == [4, 5, 6, 7]
        record = slots._claim_record(base, [7], "below_normal", "a", "e", 0.0, config8(), FREE, [], None, False)
        assert record["guaranteed"] == [7] and record["cores"] == [7]
        record = slots._claim_record({"id": "y", "background": False}, [5], "below_normal", "a", "e", 1.25,
                                     config8(), FREE, [shared("s", [7], [7, 6, 5])], None, True)
        assert record["took_lent"] == [5] and record["queued_seconds"] == 1.25 and "guaranteed" not in record

    def test_old_rules_room_holds_every_core_and_asks_for_the_shared_maximum(self):
        claims = [shared("s", [7], [7, 6, 5, 4, 3, 2])]
        plain = {"background": False}
        assert slots.old_rules_room(config8(), FREE, claims, plain, 2, None)
        assert not slots.old_rules_room(config8(), FREE, claims, plain, 3, None)
        assert not slots.old_rules_room(config8(), FREE, claims, {**plain, "shared": True, "max_cores": 4}, 1, None)



class SharedStepTests(unittest.TestCase):
    """The shared runner's give-back and growth step against real records."""
    setUp = HostSlotsTests.setUp

    class FakeTree:
        def __init__(self, cores, ok=True):
            self.cores, self.ok, self.calls = sorted(cores), ok, []

        def set_cores(self, cores):
            self.calls.append(sorted(cores))
            if self.ok:
                self.cores = sorted(cores)
            return self.ok

    def write(self, name, record):
        pid, creation = slots.self_identity()
        slots.write_json(self.host / f"TESTHOST.slots/{name}.json", {"pid": pid, "creation_time": creation, **record})

    def step(self, tree, grow):
        claim = self.host / "TESTHOST.slots" / f"claim-{'5' * 32}.json"
        with slots.Mutex():
            ok = slots._share_step(tree, claim, "5" * 32, {"guaranteed": [7], "max_cores": 4, "pool": None},
                                   grow=grow)
        return ok, slots.read_json(claim)

    def test_growth_waits_for_an_empty_queue_and_every_lent_core_goes_back_meanwhile(self):
        # review v1 #3: a queued head (of any launcher) never finds lent or newly grown cores
        slots.write_json(self.host / "TESTHOST.slots/config.json", {"cores": "7-0", "lending": True})
        with patch.object(slots, "cpu_total", return_value=8):
            self.write(f"claim-{'5' * 32}", shared("5" * 32, [7], [7, 6]))
            self.write(f"queue-00000000000000000001-{'6' * 32}", {"id": "6" * 32, "cores_wanted": 3})
            tree = self.FakeTree([7, 6])
            ok, record = self.step(tree, grow=True)
            assert ok and tree.cores == [7] and record["cores"] == [7]
            (self.host / f"TESTHOST.slots/queue-00000000000000000001-{'6' * 32}.json").unlink()
            ok, record = self.step(tree, grow=True)
            assert ok and tree.cores == [4, 5, 6, 7] and record["cores"] == [4, 5, 6, 7]
            ok, record = self.step(tree, grow=False)      # nothing taken, nothing given back
            assert tree.calls[-1] == [4, 5, 6, 7] and record["cores"] == [4, 5, 6, 7]

    def test_a_failed_narrowing_publishes_nothing_and_reports_failure(self):
        slots.write_json(self.host / "TESTHOST.slots/config.json", {"cores": "7-0", "lending": True})
        with patch.object(slots, "cpu_total", return_value=8):
            self.write(f"claim-{'5' * 32}", shared("5" * 32, [7], [7, 6]))
            self.write(f"claim-{'7' * 32}", {"id": "7" * 32, "cores": [6], "state": "suspended"})
            tree = self.FakeTree([7, 6], ok=False)
            ok, record = self.step(tree, grow=False)
            assert not ok and record["cores"] == [7, 6]


class PlacementOptionTests(unittest.TestCase):
    setUp = HostSlotsTests.setUp

    def assert_usage(self, *args, needle):
        proc = cli(*args, "--", sys.executable, "-c", "pass")
        _, err = proc.communicate(timeout=60)
        assert proc.returncode == slots.EXIT_USAGE, err
        assert needle in err, err
        assert not list((self.host / "TESTHOST.slots").glob("queue-*.json"))
        assert not list((self.host / "TESTHOST.slots").glob("claim-*.json"))

    def test_options_that_could_leave_cores_idle_or_break_exclusivity_are_refused_before_any_ticket(self):
        base = ("--lane", "p", "--work-id", "w", "--cores", "1")
        # after the pool-reason transition (see PoolReasonTransitionTests for the window itself)
        late = patch.dict(os.environ, {"HOST_SLOTS_TODAY": "2026-12-01"})
        late.start()
        self.addCleanup(late.stop)
        self.assert_usage("run", *base, "--core-pool", str(CPUS[0]), needle="--pool-reason")
        self.assert_usage("submit", "--log", str(self.tmp_path / "s.log"), *base, "--core-pool", str(CPUS[0]),
                          needle="--pool-reason")
        self.assert_usage("run", *base, "--pool-reason", "timing", needle="only with --core-pool")
        self.assert_usage("run", *base, "--min-cores", "1", needle="only with --shared")
        self.assert_usage("run", *base, "--shared", "--background", needle="ordinary claims")
        assert not (self.tmp_path / "s.log").exists()
        with self.assertRaises(ValueError):
            slots.run("p", "w", 1, ["unused"], core_pool=[CPUS[0]])
        with self.assertRaises(ValueError):
            slots.run("p", "w", 1, ["unused"], shared=True, min_cores=2)
        with self.assertRaises(ValueError):
            slots.run("p", "w", 1, ["unused"], adopted={"pid": 1, "creation": 1})

    def test_the_reason_is_recorded(self):
        seen = []
        with patch.object(slots, "_run_claimed", side_effect=lambda claim, *a, **k: seen.append(
                slots.read_json(claim)) or 0):
            slots.run("p", "w", 1, ["unused"], core_pool=[CPUS[0]], pool_reason="timing")
        assert seen[0]["core_pool"] == [CPUS[0]] and seen[0]["core_pool_reason"] == "timing"
        assert seen[0]["cores"] == [CPUS[0]] and "prefer_cores" not in seen[0]
        events = [json.loads(line) for path in (self.host / "TESTHOST.util").glob("events-*.jsonl")
                  for line in path.read_text().splitlines()]
        assert [e["event"] for e in events] == ["admit", "end"] and events[0]["old_rules_room"] is True


def affinity_probe(tmp_path):
    """A script that publishes its pid, then its affinity every 20 ms until its release file exists."""
    return script(tmp_path, "affinity-probe.py",
                  "from pathlib import Path\n"
                  "Path(sys.argv[1] + '.pid').write_text(str(os.getpid()))\n"
                  "while not Path(sys.argv[2]).exists():\n"
                  "    h.write_json(Path(sys.argv[1]), {'affinity': h.current_affinity()})\n"
                  "    time.sleep(0.02)\n")


def other_affinity(tmp_path):
    """A script that records another process's exact affinity at its own start, then holds until released."""
    return script(tmp_path, "other-affinity.py",
                  "from pathlib import Path\n"
                  "pid = int(Path(sys.argv[1]).read_text())\n"
                  "if os.name == 'nt':\n"
                  "    import ctypes\n"
                  "    k = ctypes.WinDLL('kernel32', use_last_error=True)\n"
                  "    k.OpenProcess.restype = ctypes.c_void_p\n"
                  "    hp = k.OpenProcess(0x1000, False, pid)\n"
                  "    a, s = ctypes.c_size_t(0), ctypes.c_size_t(0)\n"
                  "    k.GetProcessAffinityMask(ctypes.c_void_p(hp), ctypes.byref(a), ctypes.byref(s))\n"
                  "    seen = [i for i in range(64) if a.value >> i & 1]\n"
                  "else:\n"
                  "    seen = sorted(os.sched_getaffinity(pid))\n"
                  "h.write_json(Path(sys.argv[2]), {'other': seen, 'mine': h.current_affinity()})\n"
                  "while not Path(sys.argv[3]).exists(): time.sleep(0.02)\n")


class SharedProcessTests(unittest.TestCase):
    setUp = HostSlotsTests.setUp

    def affinity(self, path):
        record = slots.read_json(path)
        return None if record is None else record["affinity"]

    def shared_claim(self):
        return next(c for c in slots.status()["claims"] if c["lane"] == "s")

    @needs_two_ut
    def test_a_shared_claim_lends_narrows_before_the_borrower_starts_and_grows_back(self):
        os.environ[slots.GROW_ENV] = "0.2"
        self.addCleanup(os.environ.pop, slots.GROW_ENV, None)
        seen, release = self.tmp_path / "shared-affinity.json", self.tmp_path / "shared-release"
        report, borrow_release = self.tmp_path / "borrower.json", self.tmp_path / "borrower-release"
        build = cli("run", "--shared", "--cores", str(len(CPUS)), "--lane", "s", "--work-id", "build", "--",
                    sys.executable, affinity_probe(self.tmp_path), str(seen), str(release))
        borrower = None
        try:
            assert wait_for(lambda: self.affinity(seen) == sorted(CPUS)), self.affinity(seen)
            claim = self.shared_claim()
            assert claim["guaranteed"] == [max(CPUS)] and claim["cores"] == sorted(CPUS)
            borrower = cli("run", "--lane", "o", "--work-id", "w", "--cores", str(len(CPUS) - 1), "--",
                           sys.executable, other_affinity(self.tmp_path), str(seen) + ".pid", str(report),
                           str(borrow_release))
            assert wait_for(report.exists, timeout=30)
            at_start = slots.read_json(report)
            # the lender's whole process had narrowed to its guarantee before the borrower's command started
            assert at_start["other"] == [max(CPUS)], at_start
            assert not set(at_start["other"]) & set(at_start["mine"])
            assert self.shared_claim()["cores"] == [max(CPUS)]
            borrow_release.write_text("go")
            assert borrower.wait(timeout=60) == 0
            assert wait_for(lambda: self.affinity(seen) == sorted(CPUS), timeout=30), self.affinity(seen)
        finally:
            borrow_release.write_text("go")
            release.write_text("go")
            if borrower is not None:
                borrower.wait(timeout=60)
            assert build.wait(timeout=60) == 0

    @needs_two_ut
    def test_timed_work_proceeds_once_a_shared_claim_narrows_off_its_cores(self):
        seen, release = self.tmp_path / "shared-affinity.json", self.tmp_path / "shared-release"
        report, timed_release = self.tmp_path / "timed.json", self.tmp_path / "timed-release"
        build = cli("run", "--shared", "--cores", str(len(CPUS)), "--lane", "s", "--work-id", "build", "--",
                    sys.executable, affinity_probe(self.tmp_path), str(seen), str(release))
        try:
            assert wait_for(lambda: self.affinity(seen) == sorted(CPUS))
            lock(self.host)
            timed_release.write_text("go")
            proc = cli("timed", "--cores", str(min(CPUS)), "--", sys.executable, other_affinity(self.tmp_path),
                       str(seen) + ".pid", str(report), str(timed_release),
                       env=dict(os.environ, **{slots.TOKEN_ENV: TOKEN}))
            out, err = proc.communicate(timeout=60)
            assert proc.returncode == 0, err
            at_start = slots.read_json(report)
            assert min(CPUS) not in at_start["other"] and at_start["mine"] == [min(CPUS)], at_start
            # the held lock without a declaration reserves the whole host again
            assert wait_for(lambda: self.shared_claim()["state"] == "suspended")
            (self.host / "TESTHOST.lock").unlink()
            assert wait_for(lambda: self.shared_claim()["state"] == "running")
        finally:
            (self.host / "TESTHOST.lock").unlink(missing_ok=True)
            release.write_text("go")
            assert build.wait(timeout=60) == 0


def sample(state, i, busy, claims=(), tickets=(), config=None, timed=FREE, interval=30.0, mono=None):
    """Watcher sample i (every `interval` seconds) with each CPU busy at a steady fraction since time 0."""
    mono = (i + 1) * interval if mono is None else mono
    counters = {cpu: (int(b * mono * 1000), int(mono * 1000)) for cpu, b in busy.items()}
    wall = (datetime(2026, 10, 31, tzinfo=timezone.utc) + timedelta(seconds=mono)).isoformat(timespec="milliseconds")
    return slots.watch_tick(state, counters, mono, wall, config or config8(), timed, list(claims), list(tickets),
                            interval=interval)


class WatcherTests(unittest.TestCase):
    """The watcher's sample function on synthetic counters."""

    def tick(self, *args, **kwargs):
        return sample(*args, **kwargs)

    def test_a_build_with_one_busy_core_of_eight_is_flagged_once_after_ten_minutes(self):
        # review v1 #7: aggregate busy over the held cores, not every core under the threshold
        claim = {"id": "b", "lane": "L", "work_id": "build", "cores": list(range(8)), "state": "running"}
        busy = {cpu: (1.0 if cpu == 7 else 0.0) for cpu in range(8)}
        state, nudged_at = {}, []
        for i in range(25):
            state, lines, nudges = self.tick(state, i, busy, [claim])
            nudged_at += [i for n in nudges if n["kind"] == "low_use"]
        assert nudged_at == [20], nudged_at       # first measured at 60 s, its run starts at 30 s, 600 s later
        assert state["flags"][0]["busy_cores"] == 1.0 and "--shared" in state["flags"][0]["detail"]
        half = {cpu: 0.5 for cpu in range(8)}
        state = {}
        for i in range(25):
            state, _, nudges = self.tick(state, i, half, [claim])
            assert not nudges

    def test_shared_and_background_claims_are_judged_by_what_they_hold(self):
        lender = shared("s", [7], [7, 6, 5], lane="L", work_id="build")
        background = {"id": "c", "lane": "ci", "work_id": "ci", "cores": [0], "background": True, "state": "running"}
        busy = {cpu: (1.0 if cpu == 7 else 0.0) for cpu in range(8)}
        state = {}
        for i in range(25):
            state, _, nudges = self.tick(state, i, busy, [lender, background])
            assert not nudges   # the guarantee is busy; lent and background cores are never flagged

    def test_a_queued_ticket_beside_unclaimed_cores_is_flagged_with_its_cause(self):
        claims = [{"id": "x", "lane": "o", "work_id": "o", "cores": [0], "state": "running"}]
        pooled = {**ticket("t" * 32, 2, None, core_pool=[0, 1]), "lane": "bench", "work_id": "b",
                  "core_pool_reason": "timing"}
        busy = {cpu: 1.0 for cpu in range(8)}
        state, flagged = {}, []
        for i in range(4):
            state, lines, nudges = self.tick(state, i, busy, claims, [pooled])
            flagged += [(i, n["cause"]) for n in nudges if n["kind"] == "queued_idle"]
        assert flagged == [(2, "pool")], flagged
        assert lines[0]["queue"][0]["cause"] == "pool"
        assert "reason timing" in state["flags"][0]["detail"]

    def test_queue_causes_follow_the_admission_view(self):
        config = config8(keep_free=2)
        claims = [{"cores": [7, 6, 5, 4]}]
        head = ticket("h", 3, None)
        assert slots.queue_cause(config, FREE, claims, [head], head) == "keep_free"
        small, plain = ticket("s", 1), ticket("p", 1, None)
        assert slots.queue_cause(config, FREE, claims, [head, small, plain], small) == "head_of_line"
        assert slots.queue_cause(config, FREE, claims, [head, small, plain], plain) == "no_max_seconds"
        timed = {"held": True, "cores": [3, 2]}
        assert slots.queue_cause(config8(), timed, claims, [head], head) == "timed"
        assert slots.queue_cause(config8(), FREE, [{"cores": list(range(7))}], [head], head) == "too_few_free"
        assert slots.queue_cause(config8(), FREE, [], [head], head) == "starting"

    def test_gaps_and_reboots_measure_nothing_and_restart_low_use_runs(self):
        claim = {"id": "b", "lane": "L", "work_id": "build", "cores": list(range(8)), "state": "running"}
        idle = {cpu: 0.0 for cpu in range(8)}
        state = {}
        for i in range(10):
            state, lines, _ = self.tick(state, i, idle, [claim])
        assert lines[0]["dt"] == 30.0 and "b" in state["low"]
        state, lines, _ = self.tick(state, 0, idle, [claim], mono=10 * 30.0 + 91)   # more than 3 intervals
        assert lines[0]["dt"] is None and "capacity_cs" not in lines[0] and state["low"] == {}
        state, lines, _ = self.tick(state, 0, idle, [claim], mono=5.0)               # monotonic went back
        assert lines[0]["dt"] is None and state["low"] == {}

    def test_holder_kinds_take_the_first_match(self):
        config = {"cores": [3, 2, 1, 0], "keep_free": 0, "priority": "below_normal"}
        claims = [shared("s", [3], [3, 2, 1]), {"cores": [1], "background": True}, {"cores": [0]}]
        assert slots.holders(config, {"held": True, "cores": [0]}, claims) == {
            3: "guaranteed", 2: "lent", 1: "lent", 0: "timed"}
        assert slots.holders(config, FREE, [{"cores": [2]}, {"cores": [2, 1], "background": True}]) == {
            3: "unclaimed", 2: "held", 1: "background", 0: "unclaimed"}

    def test_capacity_and_eligible_idle_match_admission_and_conserve(self):
        # review v2 #7: four CPUs, keep_free 1, one timed CPU: available() hands out three
        config = CONFIG4
        idle = {cpu: 0.0 for cpu in range(4)}
        state, _, _ = self.tick({}, 0, idle, config=config, timed={"held": True, "cores": [3]})
        _, lines, _ = self.tick(state, 1, idle, config=config, timed={"held": True, "cores": [3]})
        assert lines[0]["capacity_cs"] == 90.0
        state, _, _ = self.tick({}, 0, idle, config=config, timed={"held": True, "cores": None})
        _, lines, _ = self.tick(state, 1, idle, config=config, timed={"held": True, "cores": None})
        assert lines[0]["capacity_cs"] == 0.0 and lines[0]["idle_cs"] == 0.0
        # two tickets: a pooled one on CPU 0 and an open one; idle is shared out without double counting
        config = {"cores": [3, 2, 1, 0], "keep_free": 0, "priority": "below_normal"}
        tickets = [ticket("a", 2, None, core_pool=[0]), ticket("b", 2, None)]
        claims = [{"id": "x", "cores": [3, 2, 1, 0], "state": "running"}]
        state, _, _ = self.tick({}, 0, idle, claims, tickets, config=config)
        _, lines, _ = self.tick(state, 1, idle, claims, tickets, config=config)
        line = lines[0]
        assert line["idle_cs"] == 120.0 and line["coincident_idle_cs"] == 120.0
        assert line["eligible_idle_cs"] == 90.0          # a may use CPU 0 only, b takes two more
        assert sum(line["eligible_idle_by_cause"].values()) == line["eligible_idle_cs"]

    def test_claim_ends_are_logged_with_their_busy_cores(self):
        claim = {"id": "b", "lane": "L", "work_id": "build", "cores": [7, 6], "state": "running"}
        busy = {7: 1.0, 6: 0.5, **{cpu: 0.0 for cpu in range(6)}}
        state = {}
        for i in range(3):
            state, _, _ = self.tick(state, i, busy, [claim])
        _, lines, _ = self.tick(state, 3, busy, [])
        end = [line for line in lines if line["event"] == "claim_end"][0]
        assert end["id"] == "b" and end["mean_busy_cores"] == 1.5 and end["mean_held_cores"] == 2.0


class WatcherProcessTests(unittest.TestCase):
    setUp = HostSlotsTests.setUp

    def test_a_bad_config_is_logged_and_never_stops_a_long_watch(self):
        slots.write_json(self.host / "TESTHOST.slots/config.json", {"cores": "999"})
        assert slots.watch(once=True) == slots.EXIT_REFUSED
        rows = [json.loads(line) for path in (self.host / "TESTHOST.util").glob("util-*.jsonl")
                for line in path.read_text().splitlines()]
        assert [row["event"] for row in rows] == ["error"] and "999" in rows[0]["error"]
        with patch.object(slots.time, "sleep", side_effect=[None, StopIteration]):
            with self.assertRaises(StopIteration):
                slots.watch(interval=1.0)

    def test_watch_status_events_and_report(self):
        proc = cli("run", "--shared", "--cores", "1", "--lane", "r", "--work-id", "w", "--",
                   sys.executable, "-c", "pass")
        assert proc.wait(timeout=60) == 0
        for _ in range(2):
            proc = cli("watch", "--once")
            out, err = proc.communicate(timeout=60)
            assert proc.returncode == 0, err
        watch = slots.status()["watch"]
        assert watch is not None and watch["stale"] is False and watch["flags"] == []
        folder = self.host / "TESTHOST.util"
        samples = [json.loads(line) for path in folder.glob("util-*.jsonl") for line in path.read_text().splitlines()]
        assert [s["dt"] is None for s in samples] == [True, False]
        proc = cli("watch-report")
        out, err = proc.communicate(timeout=60)
        assert proc.returncode == 0, err
        report = json.loads(out)
        assert report["admits"] == report["starts"] == report["ends"] == 1 and report["censored_admits"] == 0
        assert report["samples"] == 1 and report["events_are_lower_bounds"] is True
        assert report["handoff_seconds_max"] is not None and report["handoff_seconds_max"] >= 0


def e2657b8c_engine():
    """The deployed backfill engine before shared claims (mtg-kernel e2657b8c), loaded from git, or None when the
    checkout lacks that commit (a shallow CI clone)."""
    try:
        source = subprocess.run(["git", "-C", str(TOOLS), "show", "e2657b8c:python/tools/host_slots_v1.py"],
                                capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if source.returncode != 0:
        return None
    folder = Path(tempfile.mkdtemp(prefix="hs-e2657b8c-"))
    (folder / "host_slots_e2657b8c.py").write_bytes(source.stdout)
    import importlib.util
    spec = importlib.util.spec_from_file_location("host_slots_e2657b8c", folder / "host_slots_e2657b8c.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LendingMarkerTests(unittest.TestCase):
    """While anything is lent, a deliberately unreadable delay file stops every backfill engine."""
    setUp = HostSlotsTests.setUp

    def write(self, name, record):
        pid, creation = slots.self_identity()
        slots.write_json(self.host / f"TESTHOST.slots/{name}.json", {"pid": pid, "creation_time": creation, **record})

    def test_the_marker_is_unreadable_to_older_engines_and_skipped_by_this_one(self):
        self.write(f"claim-{'5' * 32}", shared("5" * 32, [CPUS[-1]], [CPUS[-1]]))
        with slots.Mutex():
            slots._set_lending_marker("5" * 32, True)
            snap = slots._snapshot()
        assert slots.read_json(slots._marker_path("5" * 32)) is None and slots._marker_path("5" * 32).exists()
        assert snap["unreadable"] == set() and not any(n.startswith("delay-") for n in snap["names"])
        (self.host / f"TESTHOST.slots/claim-{'5' * 32}.json").unlink()
        with slots.Mutex():
            slots._snapshot()            # its claim is gone: the marker goes too
        assert not slots._marker_path("5" * 32).exists()

    def test_an_old_head_and_old_backfiller_never_pass_a_new_lender(self):
        # review v3 #1: four CPUs, S guarantees 0 and lends 1 and 2, an old three-core head, an old one-core backfill
        old = e2657b8c_engine()
        if old is None:
            self.skipTest("mtg-kernel e2657b8c is not in this checkout")
        slots.write_json(self.host / "TESTHOST.slots/config.json", {"cores": "0-3", "lending": True})
        with patch.object(slots, "cpu_total", return_value=4), patch.object(old, "cpu_total", return_value=4):
            config = old.load_config()
            self.write(f"claim-{'5' * 32}", shared("5" * 32, [0], [0, 1, 2]))
            with slots.Mutex():
                slots._set_lending_marker("5" * 32, True)
            self.write(f"queue-00000000000000000001-{'6' * 32}", {
                "schema": slots.SCHEMA, "id": "6" * 32, "lane": "l", "work_id": "head", "cores_wanted": 3,
                "background": False, "config_sha256": old.config_digest(config)})
            ran = []
            with patch.object(old, "_run_claimed", side_effect=lambda *a, **k: ran.append(a[1]) or 0):
                with self.assertRaises(old.NoRoom):
                    old.run("l", "small", 1, ["unused"], max_seconds=99999.0)
                assert ran == []
                # the same host without the marker: the old engine proves a zero-delay backfill on 3, which the
                # lender's later give-back would turn into a delay for the head
                slots._marker_path("5" * 32).unlink()
                assert old.run("l", "small", 1, ["unused"], max_seconds=99999.0) == 0
                assert ran == [[3]]

    def test_growth_creates_the_marker_first_and_narrowing_removes_it_last(self):
        slots.write_json(self.host / "TESTHOST.slots/config.json", {"cores": "7-0", "lending": True})
        events = []
        real_marker, real_update = slots._set_lending_marker, slots._update_claim_locked

        def marker(cid, on):
            events.append(("marker", on))
            real_marker(cid, on)

        def update(path, **fields):
            events.append(("publish", fields.get("cores")))
            return real_update(path, **fields)

        with patch.object(slots, "cpu_total", return_value=8), patch.object(slots, "_set_lending_marker", marker), \
                patch.object(slots, "_update_claim_locked", update):
            self.write(f"claim-{'5' * 32}", shared("5" * 32, [7], [7]))
            tree = SharedStepTests.FakeTree([7])
            claim = self.host / "TESTHOST.slots" / f"claim-{'5' * 32}.json"
            share = {"guaranteed": [7], "max_cores": 2, "pool": None}
            with slots.Mutex():
                assert slots._share_step(tree, claim, "5" * 32, share, grow=True)
            assert events == [("publish", [7]), ("marker", True), ("publish", [6, 7])] and slots._marker_path("5" * 32).exists()
            self.write(f"queue-00000000000000000001-{'6' * 32}", {"id": "6" * 32, "cores_wanted": 1})
            events.clear()
            with slots.Mutex():
                assert slots._share_step(tree, claim, "5" * 32, share, grow=True)
            assert events == [("publish", [7]), ("marker", False)] and not slots._marker_path("5" * 32).exists()


class WatcherBoundTests(unittest.TestCase):
    """0 <= eligible idle <= idle <= capacity, whatever the reserve, timed holds and claims."""

    def test_a_fully_busy_reserved_host_reports_no_idle(self):
        # review v3 #3
        state, _, _ = sample({}, 0, {c: 1.0 for c in range(4)}, config=CONFIG4)
        _, lines, _ = sample(state, 1, {c: 1.0 for c in range(4)}, config=CONFIG4)
        assert lines[0]["idle_cs"] == 0.0 and lines[0]["capacity_cs"] == 90.0

    def test_the_bounds_hold_over_many_hosts(self):
        import random
        rng = random.Random(7)
        for _ in range(300):
            n = rng.randint(1, 8)
            config = {"cores": list(range(n)), "keep_free": rng.randint(0, n - 1), "priority": "below_normal"}
            timed = rng.choice([FREE, {"held": True, "cores": None},
                                {"held": True, "cores": rng.sample(range(n), rng.randint(1, n))}])
            claims = []
            for i in range(rng.randint(0, 3)):
                cores = rng.sample(range(n), rng.randint(1, n))
                claims.append(rng.choice([{"id": str(i), "cores": cores, "state": "running"},
                                          {"id": str(i), "cores": cores, "background": True, "state": "running"},
                                          shared(str(i), cores[:1], cores)]))
            tickets = [ticket(f"t{i}", rng.randint(1, n), None) for i in range(rng.randint(0, 2))]
            busy = {c: rng.random() for c in range(n)}
            state, _, _ = sample({}, 0, busy, claims, tickets, config=config, timed=timed)
            _, lines, _ = sample(state, 1, busy, claims, tickets, config=config, timed=timed)
            line = lines[0]
            eps = 1e-6 + 0.002 * n
            assert -eps <= line["eligible_idle_cs"] <= line["idle_cs"] + eps <= line["capacity_cs"] + 2 * eps, line
            assert abs(sum(line["eligible_idle_by_cause"].values()) - line["eligible_idle_cs"]) <= eps


FLOOR8 = {"cores": [7, 6, 5, 4, 3, 2, 1, 0], "keep_free": 0, "priority": "below_normal", "ci_floor": 2}


class CiFloorTests(unittest.TestCase):
    """The CI floor: the last ci_floor cores in preference order, for background (CI) claims only."""

    def test_only_ci_may_take_the_floor_and_ci_tries_it_first(self):
        assert slots.ci_floor_cores(FLOOR8) == [1, 0] and slots.ci_floor_cores(config8()) == []
        assert slots.available(FLOOR8, FREE, [], background=False) == [7, 6, 5, 4, 3, 2]
        assert slots.available(FLOOR8, FREE, [{"cores": [7, 6, 5, 4, 3, 2]}], background=False) == []
        assert slots.available(FLOOR8, FREE, []) == [1, 0, 7, 6, 5, 4, 3, 2]
        # CI may also use other free cores once the floor is taken
        assert slots.available(FLOOR8, FREE, [{"cores": [1, 0], "background": True}]) == [7, 6, 5, 4, 3, 2]
        # ordinary work still reclaims CI cores outside the floor, never inside it
        ci = [{"cores": [1, 0, 7], "background": True}]
        assert slots.available(FLOOR8, FREE, ci, background=False) == [7, 6, 5, 4, 3, 2]

    def test_backfills_and_shared_growth_never_take_the_floor(self):
        assert slots.available(FLOOR8, FREE, [], ci=False) == [7, 6, 5, 4, 3, 2]
        assert slots.unclaimed(FLOOR8, FREE, [{"cores": [7, 6]}]) == [5, 4, 3, 2]
        claims = [{"id": "c", "cores": [7, 6, 5, 4, 3]}]
        head = ticket("head", 3, None)
        assert admits(FLOOR8, FREE, claims, [head, ticket("t", 1)], "t") == [2]
        assert admits(FLOOR8, FREE, claims, [head, ticket("t", 2)], "t") is None

    def test_an_ordinary_request_larger_than_the_rest_is_refused(self):
        root = Path(tempfile.mkdtemp(prefix="hs-floor-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        with patch.dict(os.environ, {slots.ROOT_ENV: str(root), slots.HOST_ENV: "T"}),                 patch.object(slots, "cpu_total", return_value=4):
            (root / "T.slots").mkdir()
            slots.write_json(root / "T.slots/config.json", {"cores": "3-0", "ci_floor": 1})
            with self.assertRaisesRegex(ValueError, "hands out 1 to 3 to work other than CI"):
                slots.run("p", "w", 4, ["unused"])
            with patch.object(slots, "_run_claimed", return_value=0), patch.object(slots, "_run_adopted",
                                                                                     return_value=0):
                assert slots.run("ci", "w", 4, ["unused"], background=True) == 0

    def test_keep_free_stays_separate_from_the_floor(self):
        config = {**FLOOR8, "keep_free": 1}
        assert slots.available(config, FREE, [], background=False) == [7, 6, 5, 4, 3]
        assert slots.available(config, FREE, []) == [1, 0, 7, 6, 5, 4, 3]

    def test_config_digest_is_unchanged_without_a_floor_and_bad_floors_are_refused(self):
        root = Path(tempfile.mkdtemp(prefix="hs-floor-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        with patch.dict(os.environ, {slots.ROOT_ENV: str(root), slots.HOST_ENV: "T"}), \
                patch.object(slots, "cpu_total", return_value=4):
            (root / "T.slots").mkdir()
            for raw, expect in (({"cores": "3-0"}, {"cores": [3, 2, 1, 0], "keep_free": 0, "priority": "below_normal"}),
                                ({"cores": "3-0", "ci_floor": 0}, {"cores": [3, 2, 1, 0], "keep_free": 0,
                                                                   "priority": "below_normal"}),
                                ({"cores": "3-0", "ci_floor": 2}, {"cores": [3, 2, 1, 0], "keep_free": 0,
                                                                   "priority": "below_normal", "ci_floor": 2})):
                slots.write_json(root / "T.slots/config.json", raw)
                assert slots.load_config() == expect
            for bad in ({"ci_floor": 4}, {"ci_floor": 2, "keep_free": 2}, {"ci_floor": -1}):
                slots.write_json(root / "T.slots/config.json", {"cores": "3-0", **bad})
                with self.assertRaises(ValueError):
                    slots.load_config()

    def test_the_watcher_names_the_floor(self):
        assert slots.holders(FLOOR8, FREE, [{"cores": [1], "background": True}])[0] == "ci_floor"
        assert slots.holders(FLOOR8, FREE, [{"cores": [1], "background": True}])[1] == "background"
        claims = [{"cores": [7, 6, 5, 4, 3, 2]}]
        head = ticket("h", 1, None)
        assert slots.queue_cause(FLOOR8, FREE, claims, [head], head) == "ci_floor"
        assert slots.old_rules_room(FLOOR8, FREE, claims, {"background": False}, 2, None)


class OverdueTests(unittest.TestCase):
    setUp = HostSlotsTests.setUp

    def test_the_overdue_action_needs_a_limit_and_is_recorded(self):
        with self.assertRaises(ValueError):
            slots.run("p", "w", 1, ["unused"], on_overdue="kill")
        with self.assertRaises(ValueError):
            slots.run("p", "w", 1, ["unused"], max_seconds=5.0, on_overdue="later")
        proc = cli("run", "--lane", "p", "--work-id", "w", "--cores", "1", "--on-overdue", "flag", "--",
                   sys.executable, "-c", "pass")
        _, err = proc.communicate(timeout=60)
        assert proc.returncode == slots.EXIT_USAGE and "--max-seconds" in err, err
        seen = []
        with patch.object(slots, "_run_claimed", side_effect=lambda claim, *a, **k: seen.append(
                (slots.read_json(claim), k["overdue"])) or 0):
            slots.run("p", "w", 1, ["unused"], max_seconds=30.0)
        record, limit = seen[0]
        assert record["on_overdue"] == "flag" and record["max_seconds"] == 30.0   # enforcement is opt-in
        assert limit == {"deadline_mono": record["deadline_mono"], "action": "flag"}

    def test_a_flagging_request_may_not_delay_a_head(self):
        window = None
        head = {**ticket("h" * 32, 4, 3600.0), "config_sha256": slots.config_digest(config8())}
        for action, admitted in (("demote", True), ("flag", False)):
            claims = [{"id": "c", "cores": [7, 6, 5, 4], "max_seconds": 60.0, "deadline_mono": 1e12},
                      {"id": "d", "cores": [3, 2, 1]}]
            small = {**ticket("s", 1, 120.0, backfill_policy=slots.BACKFILL_POLICY), "on_overdue": action}
            got = slots.backfill_admission(config8(), FREE, claims, [head, small], "s", 1000.0, window)
            assert (got is not None) == admitted, (action, got)

    def overdue_run(self, action, seconds="1"):
        count = self.tmp_path / f"count-{action}"
        ticker = script(self.tmp_path, f"tick-{action}.py", "n = 0\nwhile True:\n    n += 1\n"
                        "    open(sys.argv[1], 'w').write(str(n))\n    time.sleep(0.02)\n")
        args = ["run", "--lane", "o", "--work-id", action, "--cores", "1", "--max-seconds", seconds]
        if action != "flag":           # flag is the default
            args += ["--on-overdue", action]
        return cli(*args, "--", sys.executable, ticker, str(count)), count

    def claim(self, work_id):
        return next((c for c in slots.status()["claims"] if c["work_id"] == work_id), None)

    @needs_two_ut
    def test_an_overdue_claim_demotes_itself_and_yields_like_ci(self):
        proc, count = self.overdue_run("demote")
        foreground = None
        release, active = self.tmp_path / "release", self.tmp_path / "active"
        hold = script(self.tmp_path, "hold.py", "from pathlib import Path\nPath(sys.argv[1]).write_text('up')\n"
                      "while not Path(sys.argv[2]).exists(): time.sleep(0.02)\n")
        try:
            assert wait_for(lambda: (self.claim("demote") or {}).get("overdue") is True, timeout=30)
            claim = self.claim("demote")
            assert claim["background"] is True and claim["overdue_action"] == "demote"
            assert wait_for(lambda: counter(count) > 0)
            foreground = cli("run", "--lane", "b", "--work-id", "b", "--cores", str(len(CPUS)), "--",
                             sys.executable, hold, str(active), str(release))
            assert wait_for(active.exists, timeout=30)
            assert self.claim("demote")["state"] == "suspended"
            frozen = counter(count)
            time.sleep(0.3)
            assert counter(count) == frozen
            release.write_text("go")
            assert foreground.wait(timeout=60) == 0
            assert wait_for(lambda: counter(count) > frozen + 3)
        finally:
            release.write_text("go")
            if foreground is not None:
                foreground.wait(timeout=60)
            proc.terminate()
            proc.wait(timeout=60)

    def test_kill_ends_only_its_own_tree_and_flag_only_marks(self):
        killed, _ = self.overdue_run("kill")
        out, err = killed.communicate(timeout=60)
        assert killed.returncode != 0 and json.loads(out.splitlines()[-1])["exit_code"] != 0, out + err
        events = [json.loads(line) for path in (self.host / "TESTHOST.util").glob("events-*.jsonl")
                  for line in path.read_text().splitlines()]
        assert [e["action"] for e in events if e["event"] == "overdue"] == ["kill"]
        flagged, count = self.overdue_run("flag")
        try:
            assert wait_for(lambda: (self.claim("flag") or {}).get("overdue") is True, timeout=30)
            claim = self.claim("flag")
            assert claim["background"] is False and claim["state"] == "running" and flagged.poll() is None
            before = counter(count)
            assert wait_for(lambda: counter(count) > before + 3)
        finally:
            flagged.terminate()
            flagged.wait(timeout=60)


def engine_at(commit, name):
    """A deployed backfill engine loaded from git, or None when the checkout lacks that commit."""
    try:
        source = subprocess.run(["git", "-C", str(TOOLS), "show", f"{commit}:python/tools/host_slots_v1.py"],
                                capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if source.returncode != 0:
        return None
    folder = Path(tempfile.mkdtemp(prefix=f"hs-{commit}-"))
    (folder / f"{name}.py").write_bytes(source.stdout)
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, folder / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LendingGateTests(unittest.TestCase):
    """review v4 (Fable) #1: the #407 engine ignores the lending marker, so lending is gated per host."""
    setUp = HostSlotsTests.setUp

    def write(self, name, record):
        pid, creation = slots.self_identity()
        slots.write_json(self.host / f"TESTHOST.slots/{name}.json", {"pid": pid, "creation_time": creation, **record})

    def test_the_407_engine_backfills_past_the_marker_so_shared_claims_need_the_host_gate(self):
        old = engine_at("05fd27807", "host_slots_05fd27807")
        if old is None:
            self.skipTest("mtg-kernel 05fd27807 is not in this checkout")
        slots.write_json(self.host / "TESTHOST.slots/config.json", {"cores": "0-3"})
        with patch.object(slots, "cpu_total", return_value=4), patch.object(old, "cpu_total", return_value=4):
            # Without "lending": true, no shared claim can exist on this host, so S below could never be made.
            with self.assertRaisesRegex(ValueError, "shared claims are off"):
                slots.run("l", "build", 3, ["unused"], shared=True)
            proc = cli("run", "--shared", "--lane", "l", "--work-id", "b", "--cores", "2", "--",
                       sys.executable, "-c", "pass")
            _, err = proc.communicate(timeout=60)
            assert proc.returncode == slots.EXIT_USAGE and "lending" in err, err
            assert not list((self.host / "TESTHOST.slots").glob("queue-*.json"))
            # Had it existed: S guarantees 0 and lends 1 and 2 with its marker, an old head wants 3 cores.
            config = old.load_config()
            self.write(f"claim-{'5' * 32}", shared("5" * 32, [0], [0, 1, 2]))
            with slots.Mutex():
                slots._set_lending_marker("5" * 32, True)
            self.write(f"queue-00000000000000000001-{'6' * 32}", {
                "schema": slots.SCHEMA, "id": "6" * 32, "lane": "l", "work_id": "head", "cores_wanted": 3,
                "background": False, "config_sha256": old.config_digest(config)})
            ran = []
            with patch.object(old, "_run_claimed", side_effect=lambda *a, **k: ran.append(a[1]) or 0):
                assert old.run("l", "small", 1, ["unused"], max_seconds=99999.0) == 0
            assert ran == [[3]]   # the #407 engine proves a backfill the lender's give-back turns into a delay

    def test_lenders_close_while_an_older_engine_shows_itself(self):
        slots.write_json(self.host / "TESTHOST.slots/config.json", {"cores": "7-0", "lending": True})
        with patch.object(slots, "cpu_total", return_value=8):
            self.write(f"claim-{'5' * 32}", shared("5" * 32, [7], [7, 6]))
            claim = self.host / "TESTHOST.slots" / f"claim-{'5' * 32}.json"
            share = {"guaranteed": [7], "max_cores": 4, "pool": None}
            # a live #407 backfill (no deadline_mono): give everything back, do not grow, even with no queue
            self.write(f"claim-{'7' * 32}", {"id": "7" * 32, "cores": [0], "backfill": True, "max_seconds": 60.0,
                                             "deadline_at": "2026-10-31T00:00:00+00:00", "state": "running"})
            tree = SharedStepTests.FakeTree([7, 6])
            with slots.Mutex():
                assert slots._share_step(tree, claim, "5" * 32, share, grow=True)
            assert tree.cores == [7] and slots.read_json(claim)["cores"] == [7]
            (self.host / f"TESTHOST.slots/claim-{'7' * 32}.json").unlink()
            with slots.Mutex():
                assert slots._share_step(tree, claim, "5" * 32, share, grow=True)
            assert tree.cores == [4, 5, 6, 7]
            # lending switched off in the config: everything goes back again
            slots.write_json(self.host / "TESTHOST.slots/config.json", {"cores": "7-0"})
            with slots.Mutex():
                assert slots._share_step(tree, claim, "5" * 32, share, grow=True)
            assert tree.cores == [7] and not slots._marker_path("5" * 32).exists()
        assert slots.legacy_backfill_engine([{"max_seconds": 5.0}], [])
        assert not slots.legacy_backfill_engine([{"max_seconds": 5.0, "backfill_policy": 2}, {"cores_wanted": 1}], [])


class PublishFailureTests(unittest.TestCase):
    """review v4 (Fable) #3: a publication that did not reach the disk never widens a job or drops a marker."""
    setUp = HostSlotsTests.setUp

    def write(self, name, record):
        pid, creation = slots.self_identity()
        slots.write_json(self.host / f"TESTHOST.slots/{name}.json", {"pid": pid, "creation_time": creation, **record})

    def test_growth_without_a_confirmed_publish_never_widens(self):
        slots.write_json(self.host / "TESTHOST.slots/config.json", {"cores": "7-0", "lending": True})
        with patch.object(slots, "cpu_total", return_value=8):
            self.write(f"claim-{'5' * 32}", shared("5" * 32, [7], [7]))
            claim = self.host / "TESTHOST.slots" / f"claim-{'5' * 32}.json"
            tree = SharedStepTests.FakeTree([7])
            real_read = slots.read_json
            with slots.Mutex():
                with patch.object(slots, "read_json", side_effect=lambda path: None if path == claim else real_read(path)):
                    assert not slots._share_step(tree, claim, "5" * 32, {"guaranteed": [7], "max_cores": 4, "pool": None},
                                      grow=True)
            assert tree.cores == [7] and tree.calls == [] and real_read(claim)["cores"] == [7]

    def test_a_narrowing_whose_publish_fails_suspends_and_keeps_the_marker(self):
        slots.write_json(self.host / "TESTHOST.slots/config.json", {"cores": "7-0", "lending": True})
        with patch.object(slots, "cpu_total", return_value=8):
            self.write(f"claim-{'5' * 32}", shared("5" * 32, [7], [7, 6, 5]))
            self.write(f"queue-00000000000000000001-{'6' * 32}", {"id": "6" * 32, "cores_wanted": 1})
            claim = self.host / "TESTHOST.slots" / f"claim-{'5' * 32}.json"
            with slots.Mutex():
                slots._set_lending_marker("5" * 32, True)
            tree = SharedStepTests.FakeTree([7, 6, 5])
            with slots.Mutex():
                with patch.object(slots, "write_json", side_effect=OSError("disk full")):
                    ok = slots._share_step(tree, claim, "5" * 32, {"guaranteed": [7], "max_cores": 3, "pool": None},
                                           grow=False)
            assert ok is False                                   # the caller suspends the tree
            assert slots.read_json(claim)["cores"] == [7, 6, 5]  # the record still lends ...
            assert slots._marker_path("5" * 32).exists()         # ... so the marker stays
            with slots.Mutex():                                  # once the publish works, both settle
                assert slots._share_step(tree, claim, "5" * 32, {"guaranteed": [7], "max_cores": 3, "pool": None},
                                         grow=False)
            assert slots.read_json(claim)["cores"] == [7] and not slots._marker_path("5" * 32).exists()

    def test_update_reports_whether_the_fields_reached_the_disk(self):
        claim = self.host / "TESTHOST.slots" / "claim-x.json"
        assert slots._update_claim_locked(claim, cores=[1]) is False          # no record
        slots.write_json(claim, {"cores": [1, 2]})
        assert slots._update_claim_locked(claim, cores=[1]) is True and slots.read_json(claim)["cores"] == [1]
        with patch.object(slots, "write_json", side_effect=OSError("denied")):
            assert slots._update_claim_locked(claim, cores=[2]) is False


class SmallFixTests(unittest.TestCase):
    setUp = HostSlotsTests.setUp

    def test_a_shared_command_sees_only_its_guarantee_and_naive_report_times_are_utc(self):
        out = cli("run", "--shared", "--cores", str(len(CPUS)), "--lane", "s", "--work-id", "env", "--",
                  sys.executable, "-c", "import os; print(os.environ['HOST_SLOTS_CORES'])")
        stdout, err = out.communicate(timeout=60)
        assert out.returncode == 0, err
        assert stdout.splitlines()[1] == str(max(CPUS))
        assert slots.watch_report("2026-10-31T00:00:00")["since"] == "2026-10-31T00:00:00"

    def test_status_removes_a_killed_lenders_marker(self):
        with slots.Mutex():
            slots._set_lending_marker("9" * 32, True)
        slots.status()
        assert not slots._marker_path("9" * 32).exists()


class FlagTicketTests(unittest.TestCase):
    """review v6 (Fable) #6: a flag ticket carries backfill_policy 0, so the #427 engine and this one pick the
    same first eligible candidate."""

    def test_both_engines_agree_on_the_first_eligible_candidate(self):
        old = e2657b8c_engine()
        if old is None:
            self.skipTest("mtg-kernel e2657b8c is not in this checkout")
        config = config8()
        head = {**ticket("h" * 32, 4, 3600.0, backfill_policy=slots.BACKFILL_POLICY),
                "config_sha256": slots.config_digest(config)}
        claims = [{"id": "c", "cores": [7, 6, 5, 4]}, {"id": "d", "cores": [3, 2, 1]}]
        later = ticket("p", 1, 120.0, backfill_policy=slots.BACKFILL_POLICY, on_overdue="demote")
        for policy, agree in ((0, True), (slots.BACKFILL_POLICY, False)):
            flag = ticket("f", 1, 120.0, backfill_policy=policy, on_overdue="flag")
            tickets = [head, flag, later]
            new = slots.backfill_admission(config, FREE, claims, tickets, "p", 1000.0, None)
            before = old.backfill_admission(config, FREE, claims, tickets, "p", 1000.0, None)
            assert (new == before) is agree, (policy, new, before)
        assert new is not None   # with policy 0 both admit the later request; with 2 the old engine picks f

    def test_run_writes_policy_zero_for_flag_tickets(self):
        root = Path(tempfile.mkdtemp(prefix="hs-flag-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        published = []
        real = slots.write_json

        def record(path, value):
            if Path(path).name.startswith("queue-"):
                published.append(value)
            real(path, value)

        with patch.dict(os.environ, {slots.ROOT_ENV: str(root), slots.HOST_ENV: "T"}), \
                patch.object(slots, "write_json", side_effect=record), \
                patch.object(slots, "_run_claimed", return_value=0):
            (root / "T.slots").mkdir()
            for action in ("flag", "demote"):
                slots.run("p", action, 1, ["unused"], max_seconds=60.0, on_overdue=action)
        assert [(t["on_overdue"], t["backfill_policy"]) for t in published] == [("flag", 0), ("demote", 2)]


class PoolReasonTransitionTests(unittest.TestCase):
    setUp = HostSlotsTests.setUp

    def test_a_missing_reason_is_accepted_as_unspecified_until_the_date_and_nudged(self):
        seen = []
        with patch.dict(os.environ, {"HOST_SLOTS_TODAY": "2026-11-16"}), \
                patch.object(slots, "_run_claimed", side_effect=lambda claim, *a, **k: seen.append(
                    slots.read_json(claim)) or 0):
            slots.run("p", "w", 1, ["unused"], core_pool=[CPUS[0]])
        assert seen[0]["core_pool_reason"] == "unspecified"
        with patch.dict(os.environ, {"HOST_SLOTS_TODAY": slots.POOL_REASON_REQUIRED_FROM}):
            with self.assertRaisesRegex(ValueError, "--pool-reason"):
                slots.run("p", "w", 1, ["unused"], core_pool=[CPUS[0]])
        claim = {"id": "u" * 32, "lane": "bignet", "work_id": "q", "cores": [0], "state": "running",
                 "core_pool": [0], "core_pool_reason": "unspecified"}
        _, _, nudges = sample({}, 0, {0: 1.0}, [claim], config={"cores": [0], "keep_free": 0,
                                                                "priority": "below_normal"})
        assert [n["kind"] for n in nudges] == ["pool_unspecified"] and slots.POOL_REASON_REQUIRED_FROM in nudges[0]["detail"]

    def test_the_cli_warns_during_the_window(self):
        with patch.dict(os.environ, {"HOST_SLOTS_TODAY": "2026-11-01"}):
            proc = cli("run", "--lane", "p", "--work-id", "w", "--cores", "1", "--core-pool", str(CPUS[0]), "--",
                       sys.executable, "-c", "pass")
            out, err = proc.communicate(timeout=60)
        assert proc.returncode == 0 and "unspecified" in err and slots.POOL_REASON_REQUIRED_FROM in err, err


class KillOutsideMutexTests(unittest.TestCase):
    """review v6 (Fable) #2: a kill never holds the admission mutex, and a member that refuses to die is bounded."""

    def test_the_kill_runs_with_the_mutex_released_and_a_survivor_is_recorded(self):
        locked = [False]
        events, updates = [], []

        class TestMutex:
            def __enter__(inner):
                assert not locked[0]
                locked[0] = True

            def __exit__(inner, *_):
                locked[0] = False

        child = MagicMock()
        child.wait.side_effect = [subprocess.TimeoutExpired("probe", 0), subprocess.TimeoutExpired("probe", 0), 1]
        tree = MagicMock()
        tree.cores = tree.applied = [0]
        tree.members.return_value = []
        tree.start.return_value = child
        tree.set_suspended.return_value = True

        def kill_members(timeout=30.0):
            assert not locked[0], "kill under the admission mutex"
            return False          # a member refused to die

        tree.kill_members.side_effect = kill_members
        with patch.object(slots, "Tree", return_value=tree), patch.object(slots, "Mutex", TestMutex), \
                patch.object(slots, "conflicts", return_value=False), \
                patch.object(slots, "background_busy", return_value=False), \
                patch.object(slots, "_budget_wait", return_value=False), \
                patch.object(slots, "_set_state_locked"), \
                patch.object(slots, "_update_claim_locked", side_effect=lambda c, **f: updates.append(f) or True), \
                patch.object(slots, "_event", side_effect=lambda kind, rec, **extra: events.append((kind, extra))), \
                patch.object(slots.time, "sleep"), patch.object(slots.signal, "signal"):
            code = slots._run_claimed(Path("unused.json"), [0], "normal", ["probe"], None, "x",
                                      overdue={"deadline_mono": 0.0, "action": "kill"})
        assert code == 1 and tree.kill_members.call_count == 1
        assert ("overdue", {"action": "kill", "ended": False}) in events
        assert {"kill_failed": True} in updates

    @unittest.skipUnless(os.name == "nt", "job members are Windows processes")
    def test_kill_members_gives_up_after_its_timeout(self):
        tree = slots.Tree.__new__(slots.Tree)
        tree.job, tree.suspended = None, set()
        with patch.object(slots.Tree, "members", return_value=[4321]), \
                patch.object(slots, "_OpenProcess", return_value=0):
            started = time.monotonic()
            assert tree.kill_members(timeout=0.3) is False
        assert time.monotonic() - started < 5


class AppliedMaskTests(unittest.TestCase):
    """review v6 (Fable) #5: after a failed growth restore the OS may hold a wider mask; it is re-applied before
    the claim may resume."""
    setUp = HostSlotsTests.setUp

    class ScriptedTree:
        def __init__(self, cores, script):
            self.cores = self.applied = sorted(cores)
            self.script, self.calls = list(script), []

        def set_cores(self, cores):
            cores = sorted(cores)
            self.calls.append(cores)
            accepted, ok = self.script.pop(0) if self.script else (True, True)
            if accepted:
                self.applied = cores
            if ok:
                self.cores = cores
            return ok

    def test_a_wider_mask_left_by_a_failed_restore_is_reapplied_before_resuming(self):
        slots.write_json(self.host / "TESTHOST.slots/config.json", {"cores": "7-0", "lending": True})
        pid, creation = slots.self_identity()
        claim = self.host / "TESTHOST.slots" / f"claim-{'5' * 32}.json"
        slots.write_json(claim, {"pid": pid, "creation_time": creation, **shared("5" * 32, [7], [7])})
        share = {"guaranteed": [7], "max_cores": 2, "pool": None}
        # widening: the OS takes the wider mask but a member disagrees; the restore then fails outright
        tree = self.ScriptedTree([7], [(True, False), (False, False)])
        with patch.object(slots, "cpu_total", return_value=8):
            with slots.Mutex():
                assert slots._share_step(tree, claim, "5" * 32, share, grow=True) is False
            assert tree.applied == [6, 7] and tree.cores == [7]
            with slots.Mutex():
                assert slots._share_step(tree, claim, "5" * 32, share, grow=False) is True
        assert tree.calls[-1] == [7] and tree.applied == tree.cores == [7]
        assert slots.read_json(claim)["cores"] == [7] and not slots._marker_path("5" * 32).exists()
