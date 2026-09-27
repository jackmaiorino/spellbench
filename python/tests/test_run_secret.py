"""Run secrets and derived values: the spec 16 test vectors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spellbench.run_secret import RunSecret, id_key, object_id, stream_seed

VECTOR = RunSecret(bytes(range(32)))
VECTORS_FILE = Path(__file__).resolve().parents[2] / "goldens" / "protocol_v2" / "test_vectors.json"


def test_run_secret_vectors() -> None:
    assert VECTOR.commitment() == "630dcd2966c4336691125448bbb25b4ff412a49c732db2c8abc1b8581bd710dd"
    assert VECTOR.game_secret(0).hex() == "7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e"
    assert VECTOR.game_secret(1).hex() == "952ea875cce08bf7706f87a89ae6a4e318a1bc4b46d6b506f8bb8505c518238e"
    assert (VECTOR.game_id(0), VECTOR.game_id(1)) == ("g-f67d7fe78c792984", "g-bb341404cf686511")
    assert (VECTOR.agent_seed(0, "p0"), VECTOR.agent_seed(0, "p1")) == (8103969398531465, 1382627979884484)
    assert (VECTOR.agent_seed(1, "p0"), VECTOR.agent_seed(1, "p1")) == (4616060983342951, 7705961899067306)


def test_object_id_and_stream_vectors() -> None:
    game0 = VECTOR.game_secret(0)
    assert id_key(game0).hex() == "842e5229d41477f389ae25e2b8196afb5bfa8c6bd9b95d7bd3703031c88e22e6"
    assert object_id(game0, "p0:card-17:z2") == "o-0a3647243d16bf78"
    assert object_id(game0, "p1:card-17:z2") == "o-e5e4b7ed2a0730e4"
    assert object_id(game0, "p0:card-17:z2:look:0") == "o-794a5cb152c9620f"
    assert object_id(game0, "p0:card-17:z2:look:1") == "o-e18a35822cc60e1c"
    assert stream_seed(game0, "spellbench/v2/rng:p1:library_shuffle:0")[:8].hex() == "8a28fd4db75719b1"


def test_the_two_games_of_a_pair_never_share_a_secret_and_preflight_is_separate() -> None:
    secrets = {VECTOR.game_secret(index) for index in range(200)}
    assert len(secrets) == 200
    assert VECTOR.preflight_secret(0) not in secrets
    assert VECTOR.preflight_game_id(0) not in {VECTOR.game_id(index) for index in range(200)}


def test_secrets_never_print() -> None:
    assert "000102" not in repr(VECTOR) and "000102" not in str(VECTOR)


@pytest.mark.parametrize("bad", ["00" * 31, "0g" * 32, "AB" * 32])
def test_from_hex_is_strict(bad: str) -> None:
    with pytest.raises(ValueError):
        RunSecret.from_hex(bad)


def test_generated_secrets_are_fresh() -> None:
    assert RunSecret.generate() != RunSecret.generate()


def test_the_vectors_file_matches_the_implementation() -> None:
    raw = VECTORS_FILE.read_bytes()
    assert raw.endswith(b"\n") and raw.count(b"\n") == 1
    vectors = json.loads(raw)
    secret = RunSecret.from_hex(vectors["run_secret"])
    assert vectors["commitment"] == secret.commitment()
    for index, value in vectors["game_secret"].items():
        assert secret.game_secret(int(index)).hex() == value
    for index, value in vectors["game_id"].items():
        assert secret.game_id(int(index)) == value
    for key, value in vectors["agent_seed"].items():
        index, seat = key.split(":")
        assert secret.agent_seed(int(index), seat) == value
    game0 = secret.game_secret(0)
    assert id_key(game0).hex() == vectors["id_key_game_0"]
    for message, value in vectors["object_id_game_0"].items():
        assert object_id(game0, message) == value
    for label, value in vectors["stream_seed_game_0_first_8_bytes"].items():
        assert stream_seed(game0, label)[:8].hex() == value
