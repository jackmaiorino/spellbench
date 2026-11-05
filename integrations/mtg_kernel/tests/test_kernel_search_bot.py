"""The W1 search entrant: spending, the order map, and design 7's composition walk."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kernel_flat_bot as flat
import kernel_search_bot as search
from spellbench.bot import Decision, GameOver, GameStart
from spellbench.builtins.uniform import SplitMix64

ENTRANT = {"schema": search.ENTRANT_SCHEMA, "workers": 4, "budget": 4000, "allowance": 100_000,
           "a_units": 300, "group_cap": 2 * (4000 + 300), "seed_model": search.SEED_MODEL}
PAYLOAD = {"schema": "x_kernel_infoset_v1", "sha256": "p" * 64, "own_decision_index": 7,
           "big": 18446744073709551615}


class RecordedScorer:
    ready = {
        "feature_contract_digest": flat.FEATURE_CONTRACT_DIGEST,
        "feature_encoding_digest": flat.FEATURE_ENCODING_DIGEST,
        "sampler_identity": flat.SAMPLER_IDENTITY,
        "float_encoding": flat.FLOAT_ENCODING,
        "selection": flat.SAMPLED,
        "card_db_hash": "064a7c989255ab3c",
        "model_state_sha256": "0" * 64,
    }

    def __init__(self):
        self.requests = []

    def score(self, request):
        self.requests.append(copy.deepcopy(request))
        wire = flat._dumps(request).encode()
        row = request["sample_seed"] % len(request["row_candidate_ids"])
        return wire, {
            "schema": flat.CHOICE_SCHEMA, "request_id": request["request_id"],
            "request_sha256": hashlib.sha256(wire).hexdigest(), "selected_row": row,
            "selected_candidate_id": request["row_candidate_ids"][row],
            "logits_bits": [0, 0], "value_bits": 0,
            **({"mapping": flat.PROPOSAL_MAPPING} if request["schema"] == flat.PROPOSAL_SCHEMA else {}),
        }

    def close(self):
        pass


def point_flat(n):
    tensor = {key: [] for key in flat.TENSOR_KEYS}
    return {"feature_contract_digest": flat.FEATURE_CONTRACT_DIGEST,
            "feature_encoding_digest": flat.FEATURE_ENCODING_DIGEST, "card_db_hash": "064a7c989255ab3c",
            "row_candidate_ids": list(range(n)), "tensor": tensor}


class FakePool:
    """Answers searches with fixed picks and charges, and points from a table
    keyed by path."""

    def __init__(self, picks=None, points=None, units=None):
        self.picks = picks or {}
        self.points = points or {}
        self.units = units or {}
        self.lines = []

    def request_line(self, line):
        self.lines.append(line)
        request = json.loads(line)
        path = tuple(request.get("path", []))
        if request.get("op") == "point":
            point = self.points.get(path)
            if point is None:
                return {"ok": True, "point": {"viewer_decision": False}}
            keys, eligible = point
            return {"ok": True, "point": {"viewer_decision": True, "keys": keys, "eligible": eligible,
                                          "flat": point_flat(len(keys))}}
        units = self.units.get(path, request["budget"])
        pick = self.picks.get(path)
        return {"ok": True, "host": "test", "k": 4, "trees": [{"transitions": units, "cpu_seconds": 0.0}],
                "search": {"root_id": request["root_id"], "budget": request["budget"],
                           "a_units": request["a_units"], "payload_sha256": request["payload"]["sha256"],
                           "units": units, "charge": units + request["a_units"], "merged": [],
                           "pick": pick, "stage": "visits", "excluded": [], "incomplete": pick is None,
                           "tree_digests": ["d"]}}

    def close(self):
        pass


def start(bot):
    bot.on_game_start(GameStart.from_request({"game_id": "g-test", "seat": "p0", "engine": {
        "name": "mtg-kernel", "card_pool_identity": "mtg-kernel-pauper-pool-v1/carddb-064a7c989255ab3c"}}))


def make_bot(pool, entrant=ENTRANT, scorer=None):
    bot = search.KernelSearchBot(scorer or RecordedScorer(), pool, dict(entrant), seed=11, decision_log=None,
                                 name="entrant", version="0", expect_model_state="0" * 64)
    start(bot)
    return bot


def decision(seat_step=0, infoset=None, candidates=3, group=None, proposals=False):
    tensor = {key: [] for key in flat.TENSOR_KEYS}
    extension = {
        "schema": flat.PROPOSAL_SCHEMA if proposals else flat.EXTENSION_SCHEMA,
        "feature_contract_digest": flat.FEATURE_CONTRACT_DIGEST,
        "feature_encoding_digest": flat.FEATURE_ENCODING_DIGEST,
        "card_db_hash": "064a7c989255ab3c", "acting_seat": "p0", "step": seat_step,
        "row_candidate_ids": list(range(candidates)),
    }
    if proposals:
        extension["mapping"] = flat.PROPOSAL_MAPPING
        extension["proposals"] = [[{"tensor": tensor, "selected_row": c}] for c in range(candidates)]
    else:
        extension["tensor"] = tensor
    extensions = {flat.EXTENSION: extension}
    if infoset is not None:
        extensions[search.INFOSET] = infoset
    return Decision.from_request({"game_id": "g-test", "decision": {
        "acting_seat": "p0", "seat_step": seat_step,
        "group": group or {"group_id": seat_step, "substep_index": 0, "substep_count": 1},
        "candidates": [{"candidate_id": n} for n in range(candidates)],
        "extensions": extensions,
    }})


def payload_ext(**extra):
    return {"schema": search.INFOSET_SCHEMA, "payload_json": json.dumps(PAYLOAD), **extra}


def test_spend_reserves_the_fixed_charge_before_the_threshold():
    # The Rust reference (serve.rs spend_v1) cases.
    assert search.spend(4000, 300, 10_000, None) == 4000
    assert search.spend(4000, 300, 2_300, None) == 2000
    assert search.spend(4000, 300, 1_300, None) == 1000
    assert search.spend(4000, 300, 1_299, None) is None
    assert search.spend(4000, 300, 200, None) is None
    assert search.spend(4000, 300, 100_000, 2_300) == 2000


def test_search_line_embeds_the_payload_bytes_verbatim():
    text = json.dumps(PAYLOAD)
    line = search.search_line("g/p0/7/0", 4000, 300, text, [1, 2])
    assert text.encode() in line
    assert json.loads(line) == {"a_units": 300, "budget": 4000, "path": [1, 2], "payload": PAYLOAD,
                                "root_id": "g/p0/7/0"}
    assert json.loads(search.point_line(text, [])) == {"op": "point", "path": [], "payload": PAYLOAD}


def test_load_entrant_checks_the_group_cap(tmp_path):
    path = tmp_path / "e.json"
    path.write_text(json.dumps(ENTRANT))
    assert search.load_entrant(path)["budget"] == 4000
    path.write_text(json.dumps({**ENTRANT, "group_cap": 1}))
    with pytest.raises(flat.BotError, match="group_cap"):
        search.load_entrant(path)


def test_searched_pick_maps_through_the_order_map_and_charges():
    pool = FakePool(picks={(): 1}, units={(): 3000})
    bot = make_bot(pool)
    answer = bot.choose(decision(0, payload_ext(live_candidate_ids=[2, 0, 1])))
    assert answer == 0  # imported row 1 is wire candidate 0
    request = json.loads(pool.lines[0])
    assert request["root_id"] == "g-test/p0/7/0" and request["budget"] == 4000 and request["a_units"] == 300
    assert bot._game_remaining == 100_000 - 3300
    assert bot._tally["searched"] == 1


def test_policy_answers_use_the_plain_bot_stream_whatever_was_searched():
    # The entrant's policy answers equal kernel_flat_bot's at the same steps:
    # one draw per wire decision, searched or not.
    plain = flat.KernelFlatBot(RecordedScorer(), seed=11, decision_log=None, name="b512", version="0",
                               expect_model_state="0" * 64)
    start(plain)
    expected = [plain.choose(decision(step)) for step in range(4)]
    pool = FakePool(picks={(): 0})
    bot = make_bot(pool)
    got = [bot.choose(decision(0, {"schema": search.INFOSET_SCHEMA, "refusal": "R2"})),
           bot.choose(decision(1, payload_ext(live_candidate_ids=[0, 1, 2]))),
           bot.choose(decision(2)),
           bot.choose(decision(3, payload_ext(live_candidate_ids=None)))]
    assert got[0] == expected[0] and got[2] == expected[2] and got[3] == expected[3]
    assert got[1] == 0
    assert bot._tally["policy:R2"] == 1 and bot._tally["policy:order_map_missing"] == 1
    assert bot._tally["policy:ineligible"] == 1


def test_allowance_below_a_quarter_budget_answers_by_policy():
    pool = FakePool(picks={(): 0})
    bot = make_bot(pool, entrant={**ENTRANT, "allowance": 1_299})
    bot.choose(decision(0, payload_ext(live_candidate_ids=[0, 1, 2])))
    assert pool.lines == [] and bot._tally["policy:allowance"] == 1


def test_incomplete_search_is_charged_and_falls_back():
    pool = FakePool(picks={}, units={(): 10})
    bot = make_bot(pool)
    bot.choose(decision(0, payload_ext(live_candidate_ids=[0, 1, 2])))
    assert bot._tally["policy:incomplete"] == 1
    assert bot._game_remaining == 100_000 - 310


def trigger_completions():
    """Worked example 1: triggers A, B, C. Wire substep 1 picks the first
    trigger, substep 2 the second; the native point has 6 permutation rows."""
    perms = ["ABC", "ACB", "BAC", "BCA", "CAB", "CBA"]
    keys = [f"k{p}" for p in perms]
    rows = []
    for p in perms:
        first = "ABC".index(p[0])
        rest = sorted(set("ABC") - {p[0]})
        rows.append({"wire": [first, rest.index(p[1])], "native": [perms.index(p)]})
    return keys, {"keys": keys, "completions": rows}


def group_decision(step, index, count, candidates, infoset=None):
    return decision(step, infoset, candidates=candidates, proposals=True,
                    group={"group_id": 5, "substep_index": index, "substep_count": count})


def test_worked_example_1_three_trigger_order():
    keys, composition = trigger_completions()
    # The search at the native point picks BCA (row 3).
    pool = FakePool(picks={(): 3}, points={(): (keys, True)})
    bot = make_bot(pool)
    first = bot.choose(group_decision(0, 0, 2, 3, payload_ext(composition=composition)))
    assert first == 1  # B: only BCA's completions start with B
    searches = [line for line in pool.lines if b'"op"' not in line]
    assert len(searches) == 1
    second = bot.choose(group_decision(1, 1, 2, 2))
    assert second == 1  # C among (A, C): Pi already covers the point, no new search
    assert len([line for line in pool.lines if b'"op"' not in line]) == 1
    assert bot._tally["walk"] == 2 and bot._group is None


def test_the_group_plan_log_carries_every_walked_points_digests(tmp_path):
    # Amendment 43.9 (a): G6 reads the walk's masked observation digests
    # from the group_plan record; a record without them classifies every
    # differing point as a drift (smokemc65: 102 drifted points, 0 known-hand
    # divergences).
    class DigestPool(FakePool):
        def request_line(self, line):
            answer = super().request_line(line)
            point = answer.get("point", {})
            if point.get("viewer_decision"):
                point["flat"]["known_hand_masked_observation_sha256"] = "ab" * 32
            return answer

    keys, composition = trigger_completions()
    bot = search.KernelSearchBot(RecordedScorer(), DigestPool(picks={(): 3}, points={(): (keys, True)}),
                                 dict(ENTRANT), seed=11, decision_log=tmp_path, name="entrant", version="0",
                                 expect_model_state="0" * 64)
    start(bot)
    bot.choose(group_decision(0, 0, 2, 3, payload_ext(composition=composition)))
    bot.choose(group_decision(1, 1, 2, 2))
    records = [json.loads(line) for line in (tmp_path / "g-test.p0.jsonl").read_text().splitlines()]
    (plan,) = [r for r in records if r.get("kind") == "group_plan"]
    walked = len(plan["plan"])
    assert walked >= 1
    for field in ("tensors", "masked_tensors", "known_hands", "masked_observations"):
        assert len(plan[field]) == walked, field
    assert plan["masked_observations"] == ["ab" * 32] * walked


def block_composition():
    """Worked example 2: blockers b1, b2; attackers a1, a2. Wire is
    blocker-major (each blocker picks none, a1 or a2); natives are
    attacker-major inclusions (a1,b1), (a1,b2), (a2,b1), (a2,b2), each posed
    only while the blocker is unassigned."""
    keys, index = [], {}

    def key(name):
        if name not in index:
            index[name] = len(keys)
            keys.append(name)
        return index[name]

    rows = []
    for b1 in (None, "a1", "a2"):
        for b2 in (None, "a1", "a2"):
            native, used = [], set()
            for attacker in ("a1", "a2"):
                for blocker, choice in (("b1", b1), ("b2", b2)):
                    if blocker in used:
                        continue
                    include = choice == attacker
                    native.append(key(f"{attacker}{blocker}:{'in' if include else 'ex'}"))
                    if include:
                        used.add(blocker)
            rows.append({"wire": [(None, "a1", "a2").index(b1), (None, "a1", "a2").index(b2)], "native": native})
    return keys, {"keys": keys, "completions": rows}


def test_worked_example_2_blocks_with_the_group_cap():
    keys, composition = block_composition()
    point = lambda attacker, blocker: ([f"{attacker}{blocker}:ex", f"{attacker}{blocker}:in"], True)
    pool = FakePool(
        # Search 1: (a1,b1) exclude; search 2: (a1,b2) include. Both use their
        # whole budget, so the third point is decided by policy.
        picks={(): 0, (0,): 1},
        points={(): point("a1", "b1"), (0,): point("a1", "b2"), (0, 1): point("a2", "b1"),
                (0, 1, 0): point("a2", "b2"), (0, 1, 1): point("a2", "b2")},
    )
    scorer = RecordedScorer()
    bot = make_bot(pool, scorer=scorer)
    b1 = bot.choose(group_decision(0, 0, 2, 3, payload_ext(composition=composition)))
    searches = [json.loads(line) for line in pool.lines if b'"op"' not in line]
    assert [s["budget"] for s in searches] == [4000, 4000]
    assert searches[1]["path"] == [0] and searches[1]["root_id"] == "g-test/p0/7/1"
    # Group remainder after two full searches: 8600 - 2 x 4300 = 0, so the
    # third point is policy (the scorer drew a row), then the plan decides b1.
    point_requests = [r for r in scorer.requests if r["request_id"].endswith(":p2")]
    assert len(point_requests) == 1
    policy_row = point_requests[0]["sample_seed"] % 2
    plan = bot._group["plan"] if bot._group else None
    assert plan == ["a1b1:ex", "a1b2:in", ["a2b1:ex", "a2b1:in"][policy_row]]
    assert b1 == (2 if policy_row == 1 else 0)
    b2 = bot.choose(group_decision(1, 1, 2, 3))
    assert b2 == 1  # b2 blocks a1, as Pi requires
    assert bot._group is None


def test_no_match_falls_back_to_policy_and_counts_a_fault():
    keys, composition = trigger_completions()
    pool = FakePool(picks={(): 0}, points={(): (["unknown"] * 6, True)})
    bot = make_bot(pool)
    bot.choose(group_decision(0, 0, 2, 3, payload_ext(composition=composition)))
    assert bot._tally["fault:no_match"] == 1 and bot._tally["policy:group_no_match"] == 1
    bot.choose(group_decision(1, 1, 2, 2))
    assert bot._tally["policy:group_no_match"] == 2


def test_groups_without_composition_or_payload_play_the_proposals():
    _, composition = trigger_completions()
    pool = FakePool()
    bot = make_bot(pool)
    bot.choose(group_decision(0, 0, 2, 3, {"schema": search.INFOSET_SCHEMA, "refusal": "R2"}))
    bot.choose(group_decision(1, 1, 2, 2))
    bot.choose(group_decision(2, 0, 2, 3, payload_ext(composition=None)))
    assert pool.lines == []
    assert bot._tally["policy:R2"] == 1 and bot._tally["policy:group_R2"] == 1
    assert bot._tally["policy:composition_cap"] == 1


def test_availability_record_counts_c5_faults(tmp_path):
    pool = FakePool(picks={(): 0})
    bot = search.KernelSearchBot(RecordedScorer(), pool, dict(ENTRANT), seed=11, decision_log=tmp_path,
                                 name="entrant", version="0", expect_model_state="0" * 64)
    start(bot)
    bot.choose(decision(0, {"schema": search.INFOSET_SCHEMA, "refusal": "R8b"}))
    bot.choose(decision(1, payload_ext(live_candidate_ids=[0, 1, 2])))
    bot.choose(decision(2))
    bot.on_game_over(GameOver.from_request({"game_id": "g-test", "terminal": {}}))
    records = [json.loads(line) for line in (tmp_path / "g-test.p0.jsonl").read_text().splitlines()]
    summary = records[-1]
    assert summary["kind"] == "availability"
    assert summary["eligible"] == 2 and summary["searched_decisions"] == 1 and summary["c5_faults"] == 1
    assert any(r.get("kind") == "search" and r["tree_digests"] == ["d"] for r in records)


class ForcedRowScorer(RecordedScorer):
    """Native-point policy answers a fixed row."""

    def __init__(self, row):
        super().__init__()
        self.row = row

    def score(self, request):
        wire, result = super().score(request)
        if request["schema"] == flat.REQUEST_SCHEMA and request["request_id"].count(":p"):
            row = self.row
            result.update(selected_row=row, selected_candidate_id=request["row_candidate_ids"][row])
        return wire, result


def test_allowance_limited_group_still_walks_by_native_policy():
    # Sol r1: with too little allowance the native point is decided by policy
    # (CBA, row 5) and the wire answer follows it (C first).
    keys, composition = trigger_completions()
    pool = FakePool(points={(): (keys, True)})
    bot = make_bot(pool, entrant={**ENTRANT, "allowance": 1_299}, scorer=ForcedRowScorer(5))
    assert bot.choose(group_decision(0, 0, 2, 3, payload_ext(composition=composition))) == 2
    assert bot.choose(group_decision(1, 1, 2, 2)) == 1  # B after C
    assert [line for line in pool.lines if b'"op"' not in line] == []
    assert bot._tally["allowance_points"] == 1 and bot._tally["walk"] == 2


class DeadPool(FakePool):
    def request_line(self, line):
        self.lines.append(line)
        raise flat.BotError("search pool exited (code 1)")


def test_pool_failures_fall_back_to_policy_and_count():
    bot = make_bot(DeadPool())
    bot.choose(decision(0, payload_ext(live_candidate_ids=[0, 1, 2])))
    assert bot._tally["fault:pool_error"] == 1 and bot._tally["policy:pool_error"] == 1
    assert bot._game_remaining == 100_000 - 4300  # charged its whole budget
    keys, composition = trigger_completions()
    bot.choose(group_decision(1, 0, 2, 3, payload_ext(composition=composition)))
    assert bot._tally["fault:pool_error"] == 2 and bot._tally["policy:group_pool_error"] == 1


def test_failed_group_search_is_a_fault_and_a_searched_group_counts_once(tmp_path):
    keys, composition = trigger_completions()
    pool = FakePool(picks={}, points={(): (keys, True)}, units={(): 5})
    bot = search.KernelSearchBot(RecordedScorer(), pool, dict(ENTRANT), seed=11, decision_log=tmp_path,
                                 name="entrant", version="0", expect_model_state="0" * 64)
    start(bot)
    bot.choose(group_decision(0, 0, 2, 3, payload_ext(composition=composition)))
    bot.choose(group_decision(1, 1, 2, 2))
    assert bot._tally["fault:incomplete"] == 1 and bot._tally["policy_points"] == 1
    pool.picks[()] = 3
    bot.choose(group_decision(2, 0, 2, 3, payload_ext(composition=composition)))
    bot.choose(group_decision(3, 1, 2, 2))
    bot.on_game_over(GameOver.from_request({"game_id": "g-test", "terminal": {}}))
    summary = json.loads((tmp_path / "g-test.p0.jsonl").read_text().splitlines()[-1])
    assert summary["eligible"] == 2 and summary["searched_decisions"] == 1 and summary["c5_faults"] == 1


def test_upper_bound_is_stable_on_large_counts():
    import entrant_availability as report
    assert report.upper_bound_95(0, 300) == pytest.approx(1 - 0.05 ** (1 / 300), rel=1e-6)
    for faults, n in ((100, 100_000), (200, 10_000), (3, 5_000)):
        bound = report.upper_bound_95(faults, n)
        assert faults / n < bound < 1


def test_an_excluded_tree_is_a_fault_even_when_the_search_picks():
    class OneTreeFails(FakePool):
        def request_line(self, line):
            answer = super().request_line(line)
            if "search" in answer:
                answer["search"]["excluded"] = [1]
                answer["trees"].append({"transitions": 9, "cpu_seconds": 0.0, "faults": ["worker 1: panicked"]})
            return answer

    bot = make_bot(OneTreeFails(picks={(): 2}))
    assert bot.choose(decision(0, payload_ext(live_candidate_ids=[0, 1, 2]))) == 2
    assert bot._tally["fault:tree_fault"] == 1 and bot._tally["searched"] == 1


def test_report_counts_allowance_limited_group_points(tmp_path):
    import entrant_availability as report
    keys, composition = trigger_completions()
    bot = search.KernelSearchBot(RecordedScorer(), FakePool(points={(): (keys, True)}),
                                 {**ENTRANT, "allowance": 1_299}, seed=11, decision_log=tmp_path,
                                 name="entrant", version="0", expect_model_state="0" * 64)
    start(bot)
    bot.choose(group_decision(0, 0, 2, 3, payload_ext(composition=composition)))
    bot.choose(group_decision(1, 1, 2, 2))
    bot.on_game_over(GameOver.from_request({"game_id": "g-test", "terminal": {}}))
    result = report.report([tmp_path])
    assert result["allowance_limited"]["group_points"] == 1
    assert result["allowance_limited"]["share_of_eligible"] == 1.0
    assert result["group_points"] == {"searched": 0, "policy": 1}


def test_allowance_share_counts_a_multi_point_group_once(tmp_path):
    # Sol r3: worked example 2 with no allowance: every native point is
    # policy (exclude, row 0), four limited points, one eligible group.
    import entrant_availability as report
    keys, composition = block_composition()
    point = lambda attacker, blocker: ([f"{attacker}{blocker}:ex", f"{attacker}{blocker}:in"], True)
    pool = FakePool(points={(): point("a1", "b1"), (0,): point("a1", "b2"), (0, 0): point("a2", "b1"),
                            (0, 0, 0): point("a2", "b2")})
    bot = search.KernelSearchBot(ForcedRowScorer(0), pool, {**ENTRANT, "allowance": 1}, seed=11,
                                 decision_log=tmp_path, name="entrant", version="0", expect_model_state="0" * 64)
    start(bot)
    assert bot.choose(group_decision(0, 0, 2, 3, payload_ext(composition=composition))) == 0
    assert bot.choose(group_decision(1, 1, 2, 3)) == 0
    bot.on_game_over(GameOver.from_request({"game_id": "g-test", "terminal": {}}))
    result = report.report([tmp_path])
    assert result["allowance_limited"] == {"decisions": 0, "groups": 1, "group_points": 4,
                                           "share_of_eligible": 1.0}


def test_c5_counts_each_eligible_unit_once(tmp_path):
    # Sol r4: an all-trees-excluded search is a tree fault and an incomplete
    # search (two events), but one faulted eligible decision.
    class AllExcluded(FakePool):
        def request_line(self, line):
            answer = super().request_line(line)
            if "search" in answer:
                answer["search"]["excluded"] = [0]
            return answer

    bot = search.KernelSearchBot(RecordedScorer(), AllExcluded(picks={}), dict(ENTRANT), seed=11,
                                 decision_log=tmp_path, name="entrant", version="0", expect_model_state="0" * 64)
    start(bot)
    bot.choose(decision(0, payload_ext(live_candidate_ids=[0, 1, 2])))
    bot.choose(decision(1, {"schema": search.INFOSET_SCHEMA, "refusal": "R8"}))
    bot.on_game_over(GameOver.from_request({"game_id": "g-test", "terminal": {}}))
    assert bot._tally["fault:tree_fault"] == 1 and bot._tally["fault:incomplete"] == 1
    summary = json.loads((tmp_path / "g-test.p0.jsonl").read_text().splitlines()[-1])
    assert summary["eligible"] == 2 and summary["c5_faults"] == 2


def selection_then_order_completions():
    """Brainstorm-like put-back of two of A, B, C: wire group 1 selects two
    cards (sorted remaining choices), wire group 2 orders them (first pick
    among the sorted selection); natively the cards go back one at a time."""
    keys, index, rows = [], {}, []
    cards = ["A", "B", "C"]
    for i in range(3):
        rest = [c for c in cards if c != cards[i]]
        for j in range(2):
            selected = sorted([cards[i], rest[j]])
            for k in range(2):
                order = [selected[k], selected[1 - k]]
                native = []
                for card in order:
                    name = f"top:{card}"
                    if name not in index:
                        index[name] = len(keys)
                        keys.append(name)
                    native.append(index[name])
                rows.append({"wire": [i, j, k], "native": native})
    return keys, {"keys": keys, "completions": rows}


def test_a_buffer_spanning_two_wire_groups_keeps_its_plan():
    # Sol r5: the order phase follows the searched native order (C, then A).
    _, composition = selection_then_order_completions()
    pool = FakePool(picks={(): 2, (2,): 0},
                    points={(): (["top:A", "top:B", "top:C"], True), (2,): (["top:A", "top:B"], True),
                            (2, 0): None})
    bot = make_bot(pool)
    select = lambda step, index, candidates, infoset=None: decision(
        step, infoset, candidates=candidates, proposals=True,
        group={"group_id": 5, "substep_index": index, "substep_count": 2})
    assert bot.choose(select(0, 0, 3, payload_ext(composition=composition))) == 0  # A (lowest of A, C)
    assert bot.choose(select(1, 1, 2)) == 1  # C
    assert bot._group is not None and bot._group["continues"]
    order = decision(2, None, candidates=2, proposals=True,
                     group={"group_id": 6, "substep_index": 0, "substep_count": 1})
    assert bot.choose(order) == 1  # C first, as the plan put it back first
    assert bot._group is None and bot._tally["walk"] == 3 and bot._tally["c5_units"] == 0


def test_r3_decisions_are_ineligible_and_counted(tmp_path):
    # Amendment 43.1: an R3 refusal is not an eligible unit and not a C5
    # fault; the availability record and the report count it separately.
    pool = FakePool(picks={(): 0})
    bot = search.KernelSearchBot(RecordedScorer(), pool, dict(ENTRANT), seed=11, decision_log=tmp_path,
                                 name="entrant", version="0", expect_model_state="0" * 64)
    start(bot)
    bot.choose(decision(0, {"schema": search.INFOSET_SCHEMA, "refusal": "R3", "refusal_detail": "opponent"}))
    bot.choose(decision(1, {"schema": search.INFOSET_SCHEMA, "refusal": "R2"}))
    bot.choose(decision(2, payload_ext(live_candidate_ids=[0, 1, 2])))
    bot.on_game_over(GameOver.from_request({"game_id": "g-test", "terminal": {}}))
    summary = json.loads((tmp_path / "g-test.p0.jsonl").read_text().splitlines()[-1])
    assert summary["eligible"] == 2 and summary["c5_faults"] == 1 and summary["r3_ineligible"] == 1
    assert summary["tally"]["policy:R3"] == 1 and "fault:R3" not in summary["tally"]
    import entrant_availability

    report = entrant_availability.report([tmp_path])
    assert report["r3_ineligible"] == 1 and report["eligible"] == 2 and report["c5_faults"] == 1


def test_refusals_are_classified_by_subclass(tmp_path):
    # Amendment 43.1 part 2: each refusal is tallied by code and the bridge's
    # subclass; the report lists them and counts any without a subclass.
    pool = FakePool(picks={(): 0})
    bot = search.KernelSearchBot(RecordedScorer(), pool, dict(ENTRANT), seed=11, decision_log=tmp_path,
                                 name="entrant", version="0", expect_model_state="0" * 64)
    start(bot)
    bot.choose(decision(0, {"schema": search.INFOSET_SCHEMA, "refusal": "R2", "refusal_detail": "hunter_trigger_order"}))
    bot.choose(decision(1, {"schema": search.INFOSET_SCHEMA, "refusal": "R3", "refusal_detail": "opponent"}))
    bot.choose(decision(2, {"schema": search.INFOSET_SCHEMA, "refusal": "R2"}))
    bot.on_game_over(GameOver.from_request({"game_id": "g-test", "terminal": {}}))
    import entrant_availability

    report = entrant_availability.report([tmp_path])
    assert report["refusals_by_subclass"] == {"R2:hunter_trigger_order": 1, "R2:unclassified": 1, "R3:opponent": 1}
    assert report["unclassified_refusals"] == 1
    assert report["eligible"] == 2 and report["c5_faults"] == 2 and report["r3_ineligible"] == 1


def test_r1_same_name_refusals_are_counted_c5_faults(tmp_path):
    # G2: an R1 of any subclass is answered by policy and counted as a C5
    # fault, tallied as R1:<subclass>; the game goes on.
    pool = FakePool(picks={(): 0})
    bot = search.KernelSearchBot(RecordedScorer(), pool, dict(ENTRANT), seed=11, decision_log=tmp_path,
                                 name="entrant", version="0", expect_model_state="0" * 64)
    start(bot)
    for step, detail in enumerate(("same_name_batch", "same_name_hand", "export", "same_name_batch")):
        pick = bot.choose(decision(step, {"schema": search.INFOSET_SCHEMA, "refusal": "R1", "refusal_detail": detail}))
        assert 0 <= pick < 3
    bot.on_game_over(GameOver.from_request({"game_id": "g-test", "terminal": {}}))
    import entrant_availability

    report = entrant_availability.report([tmp_path])
    assert report["refusals_by_subclass"] == {"R1:export": 1, "R1:same_name_batch": 2, "R1:same_name_hand": 1}
    assert report["eligible"] == 4 and report["c5_faults"] == 4 and report["c5_by_reason"] == {"R1": 4}
    assert report["unclassified_refusals"] == 0


def test_r3_is_ineligible_only_for_the_opponents_plan():
    # G1: R3 with any subclass but "opponent" is eligible and a C5 fault.
    bot = make_bot(FakePool())
    bot.choose(decision(0, {"schema": search.INFOSET_SCHEMA, "refusal": "R3", "refusal_detail": "opponent"}))
    bot.choose(decision(1, {"schema": search.INFOSET_SCHEMA, "refusal": "R3", "refusal_detail": "plan_error"}))
    bot.choose(decision(2, {"schema": search.INFOSET_SCHEMA, "refusal": "R3"}))
    assert bot._tally["r3_ineligible"] == 1 and bot._tally["eligible"] == 2
    assert bot._tally["fault:R3:plan_error"] == 1 and bot._tally["fault:R3:unclassified"] == 1
    assert bot._tally["c5_units"] == 2


def test_unknown_refusal_codes_are_faults():
    # G2: fail closed on any refusal code other than R3 for the opponent.
    bot = make_bot(FakePool())
    bot.choose(decision(0, {"schema": search.INFOSET_SCHEMA, "refusal": "R9", "refusal_detail": "export"}))
    assert bot._tally["fault:R9"] == 1 and bot._tally["c5_units"] == 1
    assert search.is_fault("anything_new") and not search.is_fault("ineligible")
    assert not search.is_fault("allowance") and not search.is_fault("R3") and not search.is_fault("group_R2")
    # A refusal code named like a policy reason that is no fault still is one.
    for code in ("allowance", "ineligible", "group_new"):
        bot = make_bot(FakePool())
        bot.choose(decision(0, {"schema": search.INFOSET_SCHEMA, "refusal": code, "refusal_detail": "export"}))
        assert bot._tally[f"fault:refusal:{code}"] == 1 and bot._tally["c5_units"] == 1


def test_groups_without_composition_fault_by_reason():
    # G3: each reason a group carries no composition is its own C5 fault.
    for why in ("composition_cap", "no_completions", "missing_preview_keys"):
        bot = make_bot(FakePool())
        bot.choose(group_decision(0, 0, 2, 3, payload_ext(composition=None, composition_unavailable=why)))
        assert bot._tally[f"fault:{why}"] == 1 and bot._tally["c5_units"] == 1


class FailingPool(FakePool):
    """Answers every search with a failure charged nothing (a pool that
    failed before dispatch, as an old pool did)."""

    def request_line(self, line):
        self.lines.append(line)
        return {"ok": False, "error": "import: payload", "charge": 0}


def test_a_failed_attempt_is_charged_at_least_a_units():
    # G4: the fixed charge covers import and dispatch even when they fail.
    bot = make_bot(FailingPool())
    remaining = bot._game_remaining
    bot.choose(decision(0, payload_ext(live_candidate_ids=[0, 1, 2])))
    assert bot._game_remaining == remaining - ENTRANT["a_units"]
    assert bot._tally["units_charged"] == ENTRANT["a_units"] and bot._tally["fault:pool_error"] == 1


def _one_game_log(tmp_path, pool=None, infosets=()):
    """One game's decision log (game g-test, seat p0) in tmp_path."""
    bot = search.KernelSearchBot(RecordedScorer(), pool or FakePool(picks={(): 0}), dict(ENTRANT), seed=11,
                                 decision_log=tmp_path, name="entrant", version="0", expect_model_state="0" * 64)
    start(bot)
    for step, infoset in enumerate(infosets):
        bot.choose(decision(step, infoset))
    bot.on_game_over(GameOver.from_request({"game_id": "g-test", "terminal": {}}))
    return tmp_path / "g-test.p0.jsonl"


def _ledger(path, *games, entrant="entrant"):
    rows = [{"game_id": game, "seats": [{"name": entrant, "seat": "p0"}, {"name": "heuristic", "seat": "p1"}]}
            for game in games]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def test_report_counts_each_game_and_seat_once(tmp_path):
    # G8: a log read twice (two directories) neither inflates the units nor passes.
    import entrant_availability
    first = tmp_path / "a"
    first.mkdir()
    log = _one_game_log(first, infosets=[payload_ext(live_candidate_ids=[0, 1, 2])])
    second = tmp_path / "b"
    second.mkdir()
    (second / log.name).write_text(log.read_text())
    once = entrant_availability.report([first])
    twice = entrant_availability.report([first, second])
    assert twice["eligible"] == once["eligible"] == 1 and twice["logs"]["duplicates"] == [log.name]
    assert once["checks"]["one_log_per_game_and_seat"] and not twice["checks"]["one_log_per_game_and_seat"]
    # Without a ledger and receipts the report cannot pass (no vacuous pass).
    assert not once["checks_pass"] and not once["checks"]["ledger_given"]


def test_report_requires_the_terminal_record_and_every_ledger_game(tmp_path):
    import entrant_availability
    log = _one_game_log(tmp_path, infosets=[payload_ext(live_candidate_ids=[0, 1, 2])])
    lines = log.read_text().splitlines()
    cut = tmp_path / "cut"
    cut.mkdir()
    (cut / "g-cut.p0.jsonl").write_text("\n".join(lines[:-1]) + "\n")
    assert entrant_availability.report([cut])["checks"]["every_log_complete"] is False
    ledger = _ledger(tmp_path / "matches.jsonl", "g-test", "g-lost")
    result = entrant_availability.report([tmp_path], [ledger], "entrant")
    assert result["logs"]["missing_for_ledger_games"] == ["g-lost.p0"]
    assert not result["checks"]["every_ledger_game_logged"] and result["games"] == 1


def test_report_keeps_unledgered_games_out_of_the_totals(tmp_path):
    import entrant_availability
    _one_game_log(tmp_path, infosets=[payload_ext(live_candidate_ids=[0, 1, 2])])
    ledger = _ledger(tmp_path / "matches.jsonl", "g-other")
    result = entrant_availability.report([tmp_path], [ledger], "entrant")
    assert result["games"] == 0 and result["logs"]["unledgered"] == ["g-test.p0.jsonl"]


def test_report_counts_failed_searches_as_attempts(tmp_path):
    import entrant_availability
    _one_game_log(tmp_path, pool=FailingPool(), infosets=[payload_ext(live_candidate_ids=[0, 1, 2])])
    result = entrant_availability.report([tmp_path])
    assert result["search_errors"] == 1 and result["attempted_searches"] == 1 and result["searches"] == 0
    assert result["checks"]["charge_within_allowance"] and result["checks"]["every_search_balanced"]


def test_report_reconciles_the_engine_side_receipts(tmp_path):
    import entrant_availability
    logs = tmp_path / "logs"
    logs.mkdir()
    _one_game_log(logs, infosets=[{"schema": search.INFOSET_SCHEMA, "refusal": "R2", "refusal_detail": "other_surface"},
                                  payload_ext(live_candidate_ids=[0, 1, 2])])
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    ledger = _ledger(tmp_path / "matches.jsonl", "g-test")

    def bridge(by_subclass, eligible=2, native=0):
        side = {"exported": 1, "by_code": {"R2": sum(by_subclass.values())} if by_subclass else {},
                "by_subclass": by_subclass}
        tally = [side, {"exported": 0, "by_code": {}}] if native == 0 else [{"exported": 0, "by_code": {}}, side]
        counts = [eligible, 0] if native == 0 else [0, eligible]
        (receipts / "g-test.bridge.json").write_text(json.dumps({
            "receipt": "x_kernel_infoset_v1", "game_id": "g-test", "eligible": counts,
            "tally": tally, "order_map_missing": [0, 0]}))

    def adapter(native_p0, internal=None, groups=()):
        seats = {"p0": native_p0, "p1": "p1" if native_p0 == "p0" else "p0"}
        (receipts / "g-test.adapter.json").write_text(json.dumps({
            "receipt": "x_kernel_infoset_v1_adapter", "game_id": "g-test", "native_seats": seats,
            "composition": {"groups": 0, "wall_us": 0, "max_wall_us": 0, "unavailable": {}},
            "internal": internal or {}, "groups": list(groups)}))

    check = lambda: entrant_availability.report([logs], [ledger], "entrant", receipts)
    bridge({"R2:other_surface": 1})
    assert check()["checks"]["receipts_reconcile"] is False  # no adapter receipt
    adapter("p0")
    result = check()
    assert result["checks"]["receipts_reconcile"] and result["receipts"][0]["bridge_eligible"] == 2
    assert result["checks_pass"]
    bridge({"R2:hunter_trigger_order": 1})
    assert check()["checks"]["receipts_reconcile"] is False  # another subclass
    bridge({"R2:other_surface": 2})
    assert check()["checks"]["receipts_reconcile"] is False  # another count
    bridge({"R2:other_surface": 1}, eligible=3)
    assert check()["checks"]["receipts_reconcile"] is False  # another eligible count
    bridge({"R2:other_surface": 1}, native=1)
    assert check()["checks"]["receipts_reconcile"] is False  # read from the wrong native seat
    adapter("p1")
    assert check()["checks"]["receipts_reconcile"]  # the adapter seated the entrant as native p1
    # A committing group's internal points: counted by the bridge, not the entrant.
    bridge({"R2:other_surface": 1, "R4:export": 1}, eligible=4, native=1)
    assert check()["checks"]["receipts_reconcile"] is False
    adapter("p1", internal={"p1": {"eligible": 2, "refusals": {"R4:export": 1}}})
    assert check()["checks"]["receipts_reconcile"] is False  # by_code must cover R4 too
    side = {"exported": 2, "by_code": {"R2": 1, "R4": 1}, "by_subclass": {"R2:other_surface": 1, "R4:export": 1}}
    (receipts / "g-test.bridge.json").write_text(json.dumps({
        "receipt": "x_kernel_infoset_v1", "game_id": "g-test", "eligible": [0, 4],
        "tally": [{"exported": 0, "by_code": {}}, side], "order_map_missing": [0, 0]}))
    assert check()["checks"]["receipts_reconcile"]
    # G6: a commit that left the previewed points fails.
    bad = {"type": "BlockDeclaration", "root_seat": "p0", "points": 2, "composition": True,
           "witness": {"multi_attacker": True}, "views_equal": False, "keys_equal": True,
           "committed_keys": ["a", "b"], "expected_keys": ["a", "b"]}
    adapter("p1", internal={"p1": {"eligible": 2, "refusals": {"R4:export": 1}}}, groups=[bad])
    assert check()["checks"]["receipts_reconcile"] is False
    adapter("p1", internal={"p1": {"eligible": 2, "refusals": {"R4:export": 1}}},
            groups=[{**bad, "views_equal": True}])
    result = check()
    # The group is rooted at the opponent's native seat: checked, but not the
    # entrant's witness.
    assert result["checks"]["receipts_reconcile"] and result["commit_check"]["witness"]["multi_attacker"] == 0
    assert result["commit_check"]["groups"] == 1 and result["commit_check"]["all_ok"]
    assert entrant_availability.report([logs], [ledger], None, receipts)["checks"]["entrant_given"] is False


def test_report_fails_on_an_unclassified_refusal(tmp_path):
    import entrant_availability
    _one_game_log(tmp_path, infosets=[{"schema": search.INFOSET_SCHEMA, "refusal": "R2"}])
    result = entrant_availability.report([tmp_path])
    assert result["unclassified_refusals"] == 1 and not result["checks"]["no_unclassified_refusal"]
    assert entrant_availability.main([str(tmp_path)]) == 1


def test_own_library_searches_are_ineligible_and_reported(tmp_path):
    # Amendment 43.2: R3b own_library_search is ineligible, not C5; any other
    # R3b subclass is a fault; the report gives the own share.
    _one_game_log(tmp_path, infosets=[
        {"schema": search.INFOSET_SCHEMA, "refusal": "R3b", "refusal_detail": "own_library_search"},
        {"schema": search.INFOSET_SCHEMA, "refusal": "R3b", "refusal_detail": "export"},
        payload_ext(live_candidate_ids=[0, 1, 2])])
    import entrant_availability

    report = entrant_availability.report([tmp_path])
    assert report["own_ineligible"] == 1 and report["eligible"] == 2 and report["c5_faults"] == 1
    assert report["c5_by_reason"] == {"R3b:export": 1}
    assert report["own_share"] == pytest.approx(1 / 3) and report["own_share_over_2pct"] is True

