"""The live host validates opt-in reveal streams before accepting decisions."""
from copy import deepcopy

import pytest

from spellbench.host.violation import ValidatorViolation
from spellbench.host.hidden import known_sort_key
from spellbench.reveal_meaning_v3 import SCHEMA
from test_host_validator import _decision, _validator
from test_messages import HELLO_OK, RULES
from v2_sample_semantics import SAMPLES, seat_decision


def validator():
    hello, rules = deepcopy(HELLO_OK), deepcopy(RULES)
    hello["extensions"].append({"name": SCHEMA, "native_ids": False})
    rules["extensions"].append(SCHEMA)
    return _validator(hello=hello, rules=rules)


def transcript(sequence=0, *, meaning="present", arrival=None):
    event = {"kind": "card_revealed", "owner_seat": "p1", "card_name": "Island", "meaning": meaning}
    if arrival is not None:
        event["arrival"] = arrival
    return {"schema": SCHEMA, "operations": [{"sequence": sequence, "events": [event]}]}


def decision(payload, *, index=0):
    sd = seat_decision([SAMPLES["pass"]], extensions={SCHEMA: payload})
    sd["seat_step"] = sd["group"]["group_id"] = index
    return sd


def test_host_requires_enabled_transcript_and_validates_links_before_other_rules():
    host = validator()
    with pytest.raises(ValidatorViolation) as missing:
        host.check(_decision(seat_decision()))
    assert missing.value.rule == "V1"
    malformed = decision(transcript(meaning="moved", arrival="arrival:0:0"))
    malformed["observation"]["viewer"] = "p1"  # also breaks V2
    with pytest.raises(ValidatorViolation) as invalid:
        host.check(_decision(malformed))
    assert invalid.value.rule == "V1"
    assert host.check(_decision(decision(transcript())))["extensions"][SCHEMA] == transcript()


def test_host_rejects_changed_duplicates_and_stale_links_without_committing_them():
    host = validator()
    first = host.check(_decision(decision(transcript())))
    host.answered(first, 0)
    bad = transcript()
    bad["operations"][0]["events"][0]["card_name"] = "Mountain"
    with pytest.raises(ValidatorViolation):
        host.check(_decision(decision(bad, index=1), step=1))
    with pytest.raises(ValidatorViolation):
        host.check(_decision(decision(transcript(1, meaning="moved", arrival="arrival:0:0"), index=1), step=1))
    # The exact duplicate is harmless, including at a later decision.
    host.check(_decision(decision(transcript(), index=1), step=1))
    assert host._reveal_v3["p0"].known_hand() == [{"owner_seat": "p1", "card_name": "Island", "minimum": 1}]


def test_other_validation_failure_does_not_commit_a_reveal_batch():
    host = validator()
    bad = decision(transcript())
    bad["observation"]["viewer"] = "p1"
    with pytest.raises(ValidatorViolation) as invalid:
        host.check(_decision(bad))
    assert invalid.value.rule == "V2"
    assert host._reveal_v3["p0"].known_hand() == []
    host.check(_decision(decision(transcript())))


def test_host_keeps_independent_operation_sequences_for_both_viewers():
    host = validator()
    first = host.check(_decision(decision(transcript())))
    host.answered(first, 0)

    def flip(value):
        if isinstance(value, str):
            return {"p0": "p1", "p1": "p0"}.get(value, value)
        if isinstance(value, list):
            return [flip(item) for item in value]
        if isinstance(value, dict):
            return {key: flip(item) for key, item in value.items()}
        return value

    other = flip(decision(transcript()))
    other["observation"]["players"].sort(key=lambda player: player["seat"])
    other["observation"]["known"].sort(key=known_sort_key)
    host.check(_decision(other, step=1))
    assert host._reveal_v3["p0"].known_hand()[0]["owner_seat"] == "p1"
    assert host._reveal_v3["p1"].known_hand()[0]["owner_seat"] == "p0"


def test_legacy_host_path_has_no_reveal_state_and_preserves_the_decision():
    host = _validator()
    sd = seat_decision()
    before = deepcopy(sd)
    assert host._reveal_v3 is None
    assert host.check(_decision(sd)) == before
