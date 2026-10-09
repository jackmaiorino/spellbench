"""Remote seats (spellbench.remote_seat, spec 11.7): the relay and the author-side server over real TLS."""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

from spellbench import remote_seat, wire
from spellbench.arena.config import TournamentConfig
from spellbench.arena.manifest import REMOTE_SEAT_COMMAND, isolation_record, isolation_refusals

from arena_helpers import BOT_HOSTILE, TESTS_DIR, builtin, ledger_rows, make_config, manifest, run

BOT_ONE_LAND = TESTS_DIR / "bot_one_land.py"
TOKEN = "a" * 64


def test_the_relay_shares_the_wire_line_limit() -> None:
    assert remote_seat.MAX_LINE_BYTES == wire.MAX_LINE_BYTES


@pytest.mark.parametrize("text, expected", [
    ("bots.example.org:7443", ("bots.example.org", 7443)),
    ("127.0.0.1:1", ("127.0.0.1", 1)),
    ("[::1]:7443", ("::1", 7443)),
])
def test_endpoints_parse(text: str, expected: tuple[str, int]) -> None:
    assert remote_seat.parse_endpoint(text) == expected


@pytest.mark.parametrize("text", ["bots.example.org", ":7443", "host:0", "host:65536", "host:http"])
def test_malformed_endpoints_are_refused(text: str) -> None:
    with pytest.raises(ValueError):
        remote_seat.parse_endpoint(text)


def test_fingerprints_normalize_and_refuse_garbage() -> None:
    hex_value = "AB" * 32
    assert remote_seat.normalize_sha256(":".join(["AB"] * 32)) == hex_value.lower()
    assert remote_seat.normalize_sha256("sha256:" + hex_value) == hex_value.lower()
    with pytest.raises(ValueError):
        remote_seat.normalize_sha256("ab" * 31)


def test_short_or_spaced_tokens_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "token"
    for bad in ("short", "a" * 20 + " " + "a" * 20):
        path.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError):
            remote_seat.read_token(path)
    path.write_text(TOKEN + "\n", encoding="utf-8")
    assert remote_seat.read_token(path) == TOKEN


def _config(*bots: dict[str, Any]) -> TournamentConfig:
    return TournamentConfig.from_json({"schema": "spellbench-tournament-config/v2", "tournament_dir": "t",
                                       "format": "pauper-bo1", "decks": [{"catalog_id": "Burn"}, {"catalog_id": "Burn"}],
                                       "engine": {"command": ["engine"]},
                                       "bots": [{"name": "uniform", "version": "2.0.0", "type": "builtin"}, *bots],
                                       "pairs_per_matchup": 1, "stats_seed": 1})


def test_a_remote_seat_is_admitted_and_makes_the_run_self_reported() -> None:
    remote = {"name": "remote", "version": "1", "type": "subprocess", "owner": "someone",
              "command": [*REMOTE_SEAT_COMMAND, "--endpoint", "bots.example.org:7443"]}
    # The placeholder alone does not make a remote seat: anything else after it is the author's code on the host.
    disguised = {"name": "disguised", "version": "1", "type": "subprocess", "owner": "someone",
                 "command": [REMOTE_SEAT_COMMAND[0], "bot.py"]}
    config = _config(remote, disguised)
    assert isolation_record(config) == {"entries": [{"name": "uniform", "isolation": "builtin-in-process"},
                                                    {"name": "remote", "isolation": "remote-self-reported"},
                                                    {"name": "disguised", "isolation": "unsandboxed"}],
                                        "self_reported": True}
    (refusal,) = isolation_refusals(config)
    assert "disguised" in refusal and "remote seat" in refusal
    assert isolation_record(_config(remote))["self_reported"] is True and isolation_refusals(_config(remote)) == []


# ---------------- real TLS on localhost ----------------


@pytest.fixture(scope="module")
def certificate(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, str]:
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl is not on PATH")
    directory = tmp_path_factory.mktemp("cert")
    cert, key = directory / "cert.pem", directory / "key.pem"
    result = subprocess.run([openssl, "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                             "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=localhost"],
                            capture_output=True)
    if result.returncode != 0:
        pytest.skip(f"openssl could not make a test certificate: {result.stderr[-300:]!r}")
    return cert, key, remote_seat.certificate_sha256(cert)


@contextmanager
def _serve(certificate: tuple[Path, Path, str], command: list[str], *, max_games: int = 4,
           log: list[str] | None = None) -> Iterator[remote_seat.SeatServer]:
    cert, key, _ = certificate
    server = remote_seat.SeatServer("127.0.0.1:0", cert=cert, key=key, token=TOKEN, command=command,
                                    max_games=max_games, log=(log.append if log is not None else lambda message: None))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.close()
        thread.join(timeout=10)


@pytest.fixture
def one_land_server(certificate: tuple[Path, Path, str]) -> Iterator[remote_seat.SeatServer]:
    with _serve(certificate, [sys.executable, str(BOT_ONE_LAND)]) as server:
        yield server


def _remote_bot(name: str, port: int, fingerprint: str, token_file: Path) -> dict[str, Any]:
    return {"name": name, "version": "1.0.0", "type": "subprocess", "owner": "a-submitter",
            "command": [*REMOTE_SEAT_COMMAND, "--endpoint", f"127.0.0.1:{port}", "--server-sha256", fingerprint,
                        "--token-file", str(token_file)]}


def _resolve(part: str) -> str:
    return sys.executable if part == REMOTE_SEAT_COMMAND[0] else part


def _token_file(tmp_path: Path, token: str = TOKEN) -> Path:
    path = tmp_path / "seat.token"
    path.write_text(token, encoding="utf-8")
    return path


def test_fingerprint_matches_the_certificate_the_server_presents(certificate: tuple[Path, Path, str]) -> None:
    cert, _, fingerprint = certificate
    out = subprocess.run([sys.executable, "-m", "spellbench.remote_seat", "fingerprint", str(cert)],
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == fingerprint


def test_a_remote_seat_plays_a_tournament(tmp_path: Path, certificate: tuple[Path, Path, str],
                                          one_land_server: remote_seat.SeatServer) -> None:
    remote = _remote_bot("one-land", one_land_server.port, certificate[2], _token_file(tmp_path))
    directory = tmp_path / "t"
    summary = run(make_config(directory, [remote, builtin("heuristic"), builtin("first")], pairs=1,
                              include_self_play=False), resolve=_resolve)
    assert (summary.status, summary.games_total, summary.games_forfeit) == ("complete", 6, 0)
    for row in ledger_rows(directory):
        names = [seat["name"] for seat in row["seats"]]
        if "one-land" in names:
            winner = names[("p0", "p1").index(row["winner"])]
            assert winner == ("heuristic" if "heuristic" in names else "one-land")   # the same bot, played remotely
    assert manifest(directory)["isolation"] == {
        "entries": [{"name": "one-land", "isolation": "remote-self-reported"},
                    {"name": "heuristic", "isolation": "builtin-in-process"},
                    {"name": "first", "isolation": "builtin-in-process"}],
        "self_reported": True,
    }
    # The published config keeps the placeholder, never the resolved interpreter.
    assert manifest(directory)["tournament"]["bots"][0]["name"] == "one-land"
    assert '"${SPELLBENCH_REMOTE_SEAT}","-m","spellbench.remote_seat","relay"' in (directory / "config.json").read_text(encoding="utf-8")


def test_a_remote_bot_that_dies_mid_game_forfeits(tmp_path: Path, certificate: tuple[Path, Path, str]) -> None:
    with _serve(certificate, [sys.executable, str(BOT_HOSTILE), "crash"]) as server:
        remote = _remote_bot("hostile", server.port, certificate[2], _token_file(tmp_path))
        directory = tmp_path / "t"
        run(make_config(directory, [builtin("heuristic"), remote], pairs=1, include_self_play=False), resolve=_resolve)
        assert {row["reason"] for row in ledger_rows(directory)} == {"forfeit:transport_error"}


def _relay(port: int, fingerprint: str, token: str) -> tuple[int, str]:
    stdin, stdout = io.BytesIO(b""), io.BytesIO()
    try:
        return remote_seat.relay(f"127.0.0.1:{port}", fingerprint, token, stdin=stdin, stdout=stdout, timeout_s=10), ""
    except remote_seat.RemoteSeatError as exc:
        return exc.exit_code, str(exc)


def test_a_wrong_pin_stops_before_the_token_is_sent(certificate: tuple[Path, Path, str]) -> None:
    log: list[str] = []
    with _serve(certificate, [sys.executable, str(BOT_ONE_LAND)], log=log) as server:
        code, message = _relay(server.port, "0" * 64, TOKEN)
        assert code == remote_seat.EXIT_REFUSED and "does not match the pinned SHA-256" in message
    assert not any("game started" in line for line in log)


def test_a_wrong_token_is_refused(certificate: tuple[Path, Path, str],
                                  one_land_server: remote_seat.SeatServer) -> None:
    code, message = _relay(one_land_server.port, certificate[2], "b" * 64)
    assert code == remote_seat.EXIT_REFUSED and "unauthorized" in message


def test_games_past_max_games_are_refused_as_busy(certificate: tuple[Path, Path, str]) -> None:
    with _serve(certificate, [sys.executable, str(BOT_ONE_LAND)], max_games=1) as server:
        held = remote_seat.connect(f"127.0.0.1:{server.port}", certificate[2], TOKEN, timeout_s=10)
        try:
            code, message = _relay(server.port, certificate[2], TOKEN)
            assert code == remote_seat.EXIT_REFUSED and "busy" in message
        finally:
            held.close()


def test_an_unreachable_endpoint_exits_with_the_connect_code(certificate: tuple[Path, Path, str]) -> None:
    with _serve(certificate, [sys.executable, str(BOT_ONE_LAND)]) as server:
        port = server.port
    code, message = _relay(port, certificate[2], TOKEN)
    assert code == remote_seat.EXIT_CONNECT and "cannot reach" in message


def test_a_banner_the_bot_prints_before_hello_reaches_the_host(tmp_path: Path, certificate: tuple[Path, Path, str]) -> None:
    # The bot writes a line before it reads anything, so it can arrive with the handshake reply: the relay must
    # pass it on, and the host then refuses the bot at preflight exactly as it refuses the same bot run locally.
    with _serve(certificate, [sys.executable, str(BOT_HOSTILE), "stdout-noise"]) as server:
        remote = _remote_bot("hostile", server.port, certificate[2], _token_file(tmp_path))
        with pytest.raises(Exception, match="preflight: bot 'hostile': malformed_response"):
            run(make_config(tmp_path / "t", [builtin("heuristic"), remote], pairs=1, include_self_play=False),
                resolve=_resolve)



ECHO = "import sys\nfor line in sys.stdin.buffer:\n    sys.stdout.buffer.write(line); sys.stdout.buffer.flush()\n"


def test_large_lines_cross_both_ways_and_oversized_lines_end_the_game(certificate: tuple[Path, Path, str]) -> None:
    # A choose request carries the whole board, so lines far larger than one TLS record must arrive whole.
    with _serve(certificate, [sys.executable, "-c", ECHO]) as server:
        stream = remote_seat.connect(f"127.0.0.1:{server.port}", certificate[2], TOKEN, timeout_s=10)
        stream.settimeout(30)
        try:
            for size in (10, 70_000, 3 * 1024 * 1024):
                line = b'{"x":"' + b"a" * size + b'"}\n'
                stream.sendall(line)
                assert stream.readline(remote_seat.MAX_LINE_BYTES + 1) == line
            stream.sendall(b"b" * (remote_seat.MAX_LINE_BYTES + 1) + b"\n")
            assert stream.readline(remote_seat.MAX_LINE_BYTES + 1) == b""      # the server ended the game
        finally:
            stream.close()
