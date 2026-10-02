"""Run secrets and derived values: the spec 16 test vectors."""

from __future__ import annotations

import hashlib
import hmac
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


@pytest.mark.parametrize(
    "bad",
    [VECTOR.game_secret(0).hex().encode("ascii"), VECTOR.game_secret(0)[:31], VECTOR.game_secret(0) + bytes(1),
     VECTOR.game_secret(0).hex()],
    ids=["hex-text-as-bytes", "31-bytes", "33-bytes", "hex-str"],
)
def test_game_secret_keys_are_exactly_32_raw_bytes(bad: object) -> None:
    derived = (id_key, lambda key: object_id(key, "p0:card-17:z2"),
               lambda key: stream_seed(key, "spellbench/v2/rng:p1:library_shuffle:0"))
    for derive in derived:
        with pytest.raises(ValueError, match="32 raw bytes"):
            derive(bad)


def _plain_hmac(key: bytes, message: str) -> bytes:
    """Spec 11.6 as written, without the module under test."""
    return hmac.new(key, message.encode("ascii"), hashlib.sha256).digest()


def test_the_reference_extra_vectors_agree_with_plain_hmac_and_the_implementation() -> None:
    extra = json.loads(VECTORS_FILE.read_bytes())["reference_extra"]
    run_secret = bytes(range(32))
    assert set(extra) == {"note", "game_secret", "game_id", "agent_seed", "stream_seed_game_0"}
    assert set(extra["game_secret"]) == set(extra["game_id"]) == {"10", "255", "256"}
    assert set(extra["agent_seed"]) == {f"{index}:{seat}" for index in (10, 255, 256) for seat in ("p0", "p1")} | {"2:p0"}
    for index, value in extra["game_secret"].items():
        assert value == _plain_hmac(run_secret, "spellbench/v2/game:" + index).hex() == VECTOR.game_secret(int(index)).hex()
    for index, value in extra["game_id"].items():
        assert value == "g-" + _plain_hmac(run_secret, "spellbench/v2/game-id:" + index)[:8].hex() == VECTOR.game_id(int(index))
    raw_seed = lambda key: int.from_bytes(_plain_hmac(run_secret, "spellbench/v2/agent-seed:" + key)[:8], "big")
    for key, value in extra["agent_seed"].items():
        index, seat = key.split(":")
        assert value == raw_seed(key) % 2**53 == VECTOR.agent_seed(int(index), seat)
    # 2:p0 is the first seed whose raw 64-bit value has bit 53 set, so a mask one bit too wide changes it.
    assert [raw_seed(key) >> 53 & 1 for key in ("0:p0", "0:p1", "1:p0", "1:p1", "2:p0")] == [0, 0, 0, 0, 1]
    game0 = _plain_hmac(run_secret, "spellbench/v2/game:0")
    assert set(extra["stream_seed_game_0"]) == {"spellbench/v2/rng:p1:library_shuffle:0"}
    for label, value in extra["stream_seed_game_0"].items():
        assert value == _plain_hmac(game0, label).hex() == stream_seed(game0, label).hex()
        assert value[:16] == "8a28fd4db75719b1"  # the spec 16 first 8 bytes
