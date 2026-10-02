"""X3 checker: validates the observation soak's files with the reference validator and checks the X3 invariants.

Usage (P's reference stack on the path, Python 3.12, no other dependency)::

    PYTHONPATH=<spellbench protocol-v2 checkout>/python python check_observations.py DIR [--jobs N] [--json OUT]

DIR holds ``game*.jsonl.gz`` from ``mage.player.spellbench.x3.ObservationSoak``. For every prompt, both seats'
observations are wrapped in a minimal seat decision and run through the live validator's own checks, in rule
order: V1 (``validate_seat_decision_schema``), V2 (``check_seat``), V4 (``check_references``), V5
(``check_hidden_zones``), V6 (``check_face_down``), V7 (``IdTracker``, one per seat over the whole game), V8
(``check_declarations`` against the declared profile) and V9 (``check_context``). V3 (seat steps and groups) and
V10 (provenance) concern the decision mapper and the server, not the observation. The acting seat's decision
carries its option references as ``select_object`` candidates (a priority prompt carries ``pass``, and its
references are compared with the held records directly), so V1, V4 and V5 also check what X4's candidates will
reference.

Invariants beyond the validator, from the engine-side audit lines (internal keys never reach agents):

- I1 per-viewer ids: no id ever appears in both seats' streams.
- I2 no reuse: within a seat's stream an id always stands for one internal key.
- I3 fresh on zone change: an object (XMage uuid) seen under a new zone change counter has a new id.
- I4 fresh per look: a hidden card shown in consecutive observations keeps its look id; shown again after a gap,
  it has an id the seat never saw.
- I5 nothing hidden by name: no string anywhere in a seat's observation is a name that only hidden cards bear
  (the other seat's hand, both libraries, face-down objects the seat may not look at).
- I6 face-down per D4: a face-down object is named exactly for the seat XMage's CardView lets look (its
  controller on the battlefield and the stack, its owner in exile); unnamed in exile, it has no characteristics.
"""

from __future__ import annotations

import argparse
import gzip
import json
import multiprocessing
import sys
from collections import Counter
from pathlib import Path

from spellbench import digests
from spellbench.errors import ValidationError
from spellbench.host.declarations import check_context, check_declarations
from spellbench.host.hidden import check_hidden_zones, hidden_candidate_key
from spellbench.host.refs import check_face_down, check_references, check_seat
from spellbench.host.tracking import IdTracker
from spellbench.host.validator import validate_seat_decision_schema
from spellbench.host.violation import ValidatorViolation
from spellbench.messages import EngineProfile, Rules
from spellbench.observation import observation_objects, zone_records
from spellbench.wire import canonical_json_dumps

SEATS = ("p0", "p1")
PROFILE_FIELDS = ("rules_supported", "observation", "decision_kinds", "engine_defaults", "rewind", "fairness",
                  "extensions")
MAX_EXAMPLES = 20


def strings(value, out):
    if isinstance(value, str):
        out.add(value)
    elif isinstance(value, dict):
        for k, v in value.items():
            strings(v, out)
    elif isinstance(value, list):
        for v in value:
            strings(v, out)
    return out


def select_candidates(viewer, refs):
    """The acting seat's option references as distinct select_object candidates, hidden-zone ones in V5 order."""
    seen, plain, hidden = set(), [], []
    for ref in refs:
        target = ref["target"]
        if target is None:
            continue
        semantic = {"kind": "select_object", "source": None, "purpose": "other", "choice": target,
                    "selected_count": 0, "minimum": 0, "maximum": 1}
        key = canonical_json_dumps(semantic)
        if key in seen:
            continue
        seen.add(key)
        (hidden if hidden_candidate_key(semantic, viewer) is not None else plain).append(semantic)
    hidden.sort(key=lambda s: hidden_candidate_key(s, viewer))
    semantics = plain + hidden
    if not semantics:
        semantics = [{"kind": "select_object", "source": None, "purpose": "other", "choice": {"player": viewer},
                      "selected_count": 0, "minimum": 0, "maximum": 1}]
    return [{"candidate_id": i, "semantic": s, "display_text": None} for i, s in enumerate(semantics)]


def check_game(path):
    stats = Counter()
    failures = []
    unresolved = Counter()
    face_down = Counter()

    def fail(where, rule, detail):
        stats[f"fail_{rule}"] += 1
        if len(failures) < MAX_EXAMPLES:
            failures.append({"file": path.name, "at": where, "rule": rule, "detail": detail[:400]})

    with gzip.open(path, "rt", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f]
    header, body, end = lines[0], lines[1:-1], lines[-1]
    hello = header["hello_ok"]
    profile = EngineProfile.from_json({k: hello[k] for k in PROFILE_FIELDS})
    rules = Rules.from_json({"opponent_decklist": "visible", "mulligan": "london",
                             "starting_player": "host_assigned", "starting_seat": header["starting_seat"],
                             "card_name_domain": digests.card_name_domain(["Mountain"]), "extensions": [],
                             "probe": False})
    trackers = {s: IdTracker() for s in SEATS}
    id_key = {s: {} for s in SEATS}            # I2: id -> internal key
    uuid_ids = {s: {} for s in SEATS}          # I3: uuid -> {key: id}
    all_ids = {s: set() for s in SEATS}        # I1, I4
    last_looks = {s: {} for s in SEATS}        # I4: key -> (id, line index)
    stats["games"] += 1
    stats[f"terminal_{end['terminal']}"] += 1
    for line in body:
        n = line["i"]
        stats["prompts"] += 1
        for viewer in SEATS:
            where = f"i={n} viewer={viewer}"
            obs = line["observations"][viewer]
            acting = line["acting"] == viewer
            refs = line["option_refs"] if acting else []
            priority = acting and line["priority"]
            if priority:
                candidates = [{"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None}]
            else:
                candidates = select_candidates(viewer, refs)
            sd = {"acting_seat": viewer, "seat_step": n, "group": {"group_id": n, "substep_index": 0,
                                                                   "substep_count": 1},
                  "context": {"kind": "priority" if priority else "choice", "source": None, "purpose": None,
                              "text": None, "rewind": False},
                  "observation": obs, "candidates": candidates, "extensions": {}}
            stats["observations"] += 1
            try:
                try:
                    validate_seat_decision_schema(sd, rules)
                except ValidationError as exc:
                    raise ValidatorViolation("V1", str(exc)) from exc
                check_seat(sd)
                check_references(sd)
                check_hidden_zones(sd)
                check_face_down(sd)
                held = [ref for _, ref in observation_objects(obs)]
                trackers[viewer].check(viewer, {r["object_id"]: r["zone"] for r in held},
                                       owners={r["object_id"]: r["owner_seat"] for r in held})
                check_declarations(sd, profile, rules)
                check_context(sd)
            except ValidatorViolation as exc:
                fail(where, exc.rule, exc.detail)
                continue
            except Exception as exc:  # a check meeting input it cannot read is a schema failure (R1-8)
                fail(where, "V1", f"{type(exc).__name__}: {exc}")
                continue
            held_by_id = {ref["object_id"]: ref for _, ref in observation_objects(obs)}
            if priority:
                for ref in refs:
                    target = ref["target"]
                    if target is not None and "object" in target:
                        if held_by_id.get(target["object"]["object_id"]) != target["object"]:
                            fail(where, "refs", f"option reference {target['object']} is not a held record")
            for ref in refs:
                if ref["target"] is None:
                    unresolved[ref.get("unresolved_zone") or "none"] += 1
                else:
                    stats["option_refs_resolved"] += 1
            check_invariants(line, viewer, obs, where, fail, stats, id_key, uuid_ids, all_ids, last_looks)
        for entry in line["audit"]["face_down"]:
            check_face_down_d4(line, entry, fail, face_down)
        stats["known_entries"] += sum(len(line["observations"][s]["known"]) for s in SEATS)
        stats["stack_entries"] += len(line["observations"]["p0"]["stack"])
    shared = all_ids["p0"] & all_ids["p1"]
    if shared:
        fail("game", "I1", f"{len(shared)} ids appear in both seats' streams, e.g. {sorted(shared)[0]}")
    stats["ids_p0"] += len(all_ids["p0"])
    stats["ids_p1"] += len(all_ids["p1"])
    return {"stats": stats, "failures": failures, "unresolved": unresolved, "face_down": face_down,
            "terminal": end, "file": path.name, "decks": header["decks"]}


def check_invariants(line, viewer, obs, where, fail, stats, id_key, uuid_ids, all_ids, last_looks):
    n = line["i"]
    looked_now = {}
    for a in line["audit"][viewer]:
        object_id, key = a["object_id"], a["key"]
        before = id_key[viewer].get(object_id)
        if before is not None and before != key:
            fail(where, "I2", f"id {object_id} stood for {before} and now {key}")
        id_key[viewer][object_id] = key
        uuid, zcc = key.rsplit(":z", 1)
        per_key = uuid_ids[viewer].setdefault(uuid, {})
        if key not in per_key and per_key:
            stats["zone_changes_seen"] += 1
            if object_id in per_key.values():
                fail(where, "I3", f"{uuid} changed zones (z{zcc}) and kept id {object_id}")
        if a["look"]:
            looked_now[key] = object_id
            prev = last_looks[viewer].get(key)
            if prev is not None and prev[1] == n - 1:
                if prev[0] != object_id:
                    fail(where, "I4", f"look id of {key} changed within consecutive observations")
            elif object_id in all_ids[viewer]:
                fail(where, "I4", f"a new look at {key} reused id {object_id}")
            else:
                stats["looks_fresh"] += 1
        per_key.setdefault(key, object_id)
        all_ids[viewer].add(object_id)
    for key, object_id in looked_now.items():
        last_looks[viewer][key] = (object_id, n)
    leak = set(line["audit"]["leak_names"][viewer])
    if leak:
        found = leak & strings(obs, set())
        if found:
            fail(where, "I5", f"hidden names in the observation: {sorted(found)[:5]}")
        stats["leak_names_checked"] += len(leak)


def check_face_down_d4(line, entry, fail, face_down):
    for viewer in SEATS:
        obs = line["observations"][viewer]
        ids = {a["key"]: a["object_id"] for a in line["audit"][viewer] if not a["look"]}
        object_id = ids.get(entry["key"])
        where = f"i={line['i']} viewer={viewer} face-down {entry['zone']}"
        if object_id is None:
            fail(where, "I6", "a face-down object is missing from the observation")
            continue
        records = [r for _, _, r in zone_records(obs)] + obs["stack"]
        record = next((r for r in records if r["object_id"] == object_id), None)
        if record is None:
            fail(where, "I6", "no record holds the face-down object's id")
            continue
        may_look = viewer == entry["visible_to"]
        if not record["face_down"]:
            fail(where, "I6", "the record is not marked face_down")
        if (record["card_name"] is not None) != may_look:
            fail(where, "I6", f"card_name {record['card_name']!r} but visible_to {entry['visible_to']}")
        if entry["zone"] == "exile" and not may_look and record["characteristics"] is not None:
            fail(where, "I6", "an unnamed face-down exiled card shows characteristics")
        face_down[f"{entry['zone']}_{'named' if may_look else 'nameless'}"] += 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dir")
    parser.add_argument("--jobs", type=int, default=max(1, multiprocessing.cpu_count() - 2))
    parser.add_argument("--json")
    args = parser.parse_args()
    files = sorted(Path(args.dir).glob("game*.jsonl.gz"))
    if not files:
        sys.exit(f"no game files in {args.dir}")
    with multiprocessing.Pool(args.jobs) as pool:
        results = pool.map(check_game, files)
    stats, unresolved, face_down, failures = Counter(), Counter(), Counter(), []
    decks = Counter()
    for r in results:
        stats.update(r["stats"])
        unresolved.update(r["unresolved"])
        face_down.update(r["face_down"])
        failures.extend(r["failures"])
        decks[":".join(r["decks"])] += 1
    failed = sum(v for k, v in stats.items() if k.startswith("fail_"))
    report = {"files": len(files), "decks": dict(sorted(decks.items())), "stats": dict(sorted(stats.items())),
              "face_down": dict(sorted(face_down.items())), "unresolved_option_ids": dict(sorted(unresolved.items())),
              "failures": failures[:MAX_EXAMPLES], "failed": failed}
    text = json.dumps(report, indent=1, sort_keys=True)
    print(text)
    if args.json:
        Path(args.json).write_text(text + "\n", encoding="utf-8")
    print(f"X3 check: {len(files)} games, {stats['observations']} observations, {failed} failures",
          file=sys.stderr)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
