"""Host-computed identifiers and the game digest chain (spec 4.3, 11.8)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from spellbench import wire
from spellbench.digests import GAME_DIGEST_DOMAIN, GameDigest, card_name_domain, deck_id, deck_rows, domain_id
from spellbench.errors import ValidationError
from spellbench.run_secret import RunSecret, id_key, object_id, stream_seed

BURN = [{"name": "Lightning Bolt", "count": 4}, {"name": "Mountain", "count": 18}]
VECTORS_FILE = Path(__file__).resolve().parents[2] / "goldens" / "protocol_v2" / "test_vectors.json"
VECTORS = json.loads(VECTORS_FILE.read_bytes())
VECTOR_GROUPS = (
    "commitment", "game_secret", "game_id", "agent_seed", "id_key_game_0", "object_id_game_0",
    "stream_seed_game_0_first_8_bytes", "deck_id", "domain_id", "canonical_sha256", "first_digest_chain_value",
)
NFD_NAME = "Lim-Dûl's Vault"  # "u" plus a combining circumflex: the NFD spelling of an Oracle name


def test_deck_and_domain_vectors() -> None:
    assert deck_id(BURN) == "sha256:0df0a001e3c4b74b1061b21e319a645f32fbe3173120e432864e14d6d6f2f5d2"
    assert deck_id(list(reversed(BURN))) == deck_id(BURN)  # rows are sorted by name first
    assert domain_id(["Lightning Bolt", "Mountain"]) == (
        "sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697"
    )
    assert card_name_domain(["Mountain", "Lightning Bolt", "Mountain"]) == {
        "domain_id": domain_id(["Lightning Bolt", "Mountain"]),
        "names": ["Lightning Bolt", "Mountain"],
    }


def test_canonical_json_vector() -> None:
    value = {"b": "Chainer's Edict", "a": "Lim-Dûl's Vault", "c": "tab\there"}
    assert hashlib.sha256(wire.canonical_json_dumps(value)).hexdigest() == (
        "041575311eb1deb02f63f70361e14159034faf0d2a31e57edf8b4cf037680377"
    )


@pytest.mark.parametrize(
    ("decklist", "message"),
    [
        ([], "nonempty"),
        ([{"name": "Mountain", "count": 0}], "count"),
        ([{"name": "Mountain", "count": 1}, {"name": "Mountain", "count": 2}], "twice"),
        ([{"name": NFD_NAME, "count": 1}], "Lim-Dûl's Vault.*NFC"),
        ([{"name": "Mountain", "count": 1, "set": "M21"}], "exactly"),
        ([{"name": "Mountain", "count": 1 << 32}], "count"),
        ([{"name": "Mountain", "count": True}], "count"),
        ([{"name": "", "count": 1}], "nonempty"),
        (["Mountain"], "exactly"),
        ({"name": "Mountain", "count": 1}, "array"),
    ],
)
def test_deck_rows_are_strict(decklist: object, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        deck_rows(decklist)


def test_deck_rows_name_the_card_under_the_callers_context() -> None:
    decklist = [{"name": "Mountain", "count": 18}, {"name": NFD_NAME, "count": 1}]
    with pytest.raises(ValidationError) as caught:
        deck_rows(decklist, context="catalog[0] (Vault).decklist")
    assert str(caught.value) == f"catalog[0] (Vault).decklist[1].name: card name {NFD_NAME!r} is not in Unicode NFC"


def test_a_domain_is_the_set_of_its_nfc_names() -> None:
    assert domain_id(("Mountain", "Lightning Bolt", "Mountain")) == domain_id(["Lightning Bolt", "Mountain"])
    with pytest.raises(ValidationError, match="Lim-Dûl's Vault.*NFC"):
        card_name_domain(["Mountain", NFD_NAME])
    with pytest.raises(ValidationError, match="array"):
        domain_id("Mountain")


def test_first_chain_value_matches_the_spec_vector() -> None:
    reset = VECTORS["first_digest_chain_value"]["reset"]
    assert GameDigest({**reset, "request_id": "h-2"}).chain_hex() == VECTORS["first_digest_chain_value"]["d"]
    assert VECTORS["first_digest_chain_value"]["d"] == "a328e304e4dcacdde5d8abe089c93a8bedd108e9985d3bdab6ede3b8e8f093a3"


def _manual(reset: dict, *messages: dict) -> str:
    d = hashlib.sha256(GAME_DIGEST_DOMAIN + wire.canonical_json_dumps(reset)).digest()
    for message in messages:
        d = hashlib.sha256(d + wire.canonical_json_dumps(message)).digest()
    return "sha256:" + d.hex()


def test_chain_order_strips_request_ids_and_chains_a_retransmission_once() -> None:
    reset = {"request_type": "reset", "request_id": "h-2", "game_id": "g-1"}
    first = {"response_type": "decision", "request_id": "h-2", "step": 0}
    step = {"request_type": "step", "request_id": "h-3", "expected_step": 0}
    done = {"response_type": "terminal", "request_id": "h-3", "outcome": "draw"}
    digest = GameDigest(reset)
    digest.add_response(first)
    digest.add_step(step, done)
    digest.add_step(step, done)  # the identical retransmission and its cached response
    strip = lambda message: {key: value for key, value in message.items() if key != "request_id"}
    assert digest.value() == _manual(strip(reset), strip(first), strip(step), strip(done))


def test_an_adjudication_is_appended_once() -> None:
    reset = {"request_type": "reset", "request_id": "h-2"}
    digest = GameDigest(reset)
    digest.add_adjudication(classification="forfeit", outcome="p1_win", reason="forfeit:timeout", winner="p1")
    record = {"adjudication": {"classification": "forfeit", "outcome": "p1_win", "reason": "forfeit:timeout", "winner": "p1"}}
    assert digest.value() == _manual({"request_type": "reset"}, record)
    with pytest.raises(ValueError):
        digest.add_adjudication(classification="halted", outcome="halted", reason="x", winner=None)


def test_the_vectors_file_holds_exactly_its_groups_and_each_reads_back() -> None:
    assert set(VECTORS) == {"schema", "run_secret", *VECTOR_GROUPS}
    assert VECTORS["schema"] == "spellbench-test-vectors/v2"
    assert deck_id(VECTORS["deck_id"]["decklist"]) == VECTORS["deck_id"]["deck_id"]
    assert domain_id(VECTORS["domain_id"]["names"]) == VECTORS["domain_id"]["domain_id"]
    canonical = wire.canonical_json_dumps(VECTORS["canonical_sha256"]["value"])
    assert hashlib.sha256(canonical).hexdigest() == VECTORS["canonical_sha256"]["sha256"]


def _vectors_document() -> dict[str, Any]:
    """The test-vector file rebuilt from the implementation and the inputs of spec 16 and 9.2."""
    secret = RunSecret(bytes(range(32)))
    game0 = secret.game_secret(0)
    names = ["Lightning Bolt", "Mountain"]
    burn = {"deck_id": deck_id(BURN), "catalog_id": "Burn"}
    reset = {  # the spec 9.2 example without its request_id
        "request_type": "reset", "protocol": "spellbench/v2", "game_id": secret.game_id(0), "format": "pauper-bo1",
        "seats": [{"seat": "p0", "deck": burn}, {"seat": "p1", "deck": burn}],
        "rules": {"opponent_decklist": "visible", "mulligan": "none", "starting_player": "host_assigned",
                  "starting_seat": "p0", "card_name_domain": card_name_domain(names), "extensions": [], "probe": False},
        "game_secret": game0.hex(), "max_decisions": 10000, "max_steps": 100000,
    }
    messages = ("p0:card-17:z2", "p1:card-17:z2", "p0:card-17:z2:look:0", "p0:card-17:z2:look:1")
    labels = ("spellbench/v2/rng:p1:library_shuffle:0",)
    value = {"b": "Chainer's Edict", "a": "Lim-Dûl's Vault", "c": "tab\there"}
    return {
        "schema": "spellbench-test-vectors/v2",
        "run_secret": secret.hex(),
        "commitment": secret.commitment(),
        "game_secret": {str(index): secret.game_secret(index).hex() for index in (0, 1)},
        "game_id": {str(index): secret.game_id(index) for index in (0, 1)},
        "agent_seed": {f"{index}:{seat}": secret.agent_seed(index, seat) for index in (0, 1) for seat in ("p0", "p1")},
        "id_key_game_0": id_key(game0).hex(),
        "object_id_game_0": {message: object_id(game0, message) for message in messages},
        "stream_seed_game_0_first_8_bytes": {label: stream_seed(game0, label)[:8].hex() for label in labels},
        "deck_id": {"decklist": deck_rows(BURN), "deck_id": deck_id(BURN)},
        "domain_id": {"names": names, "domain_id": domain_id(names)},
        "canonical_sha256": {"value": value, "sha256": hashlib.sha256(wire.canonical_json_dumps(value)).hexdigest()},
        "first_digest_chain_value": {"reset": reset, "d": GameDigest({**reset, "request_id": "h-2"}).chain_hex()},
    }


def test_the_vectors_file_is_rebuilt_byte_for_byte() -> None:
    assert VECTORS_FILE.read_bytes() == wire.canonical_json_line(_vectors_document())
