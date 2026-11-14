"""A proxy that refuses everything at once, for the play browser's closed network.

The browser reaches only this machine and four Scryfall hosts directly (its proxy bypass list); every other request is
sent to the proxy. Pointing that at a closed port makes each blocked request wait through Windows' connection retries
(seconds each), and the web client's card renderer asks for dozens of fonts and templates from blocked hosts at the start
of every game, which holds the loading screen. This server answers every request, plain or CONNECT, with
``403 Forbidden`` immediately and keeps nothing: it never forwards anything.

``python -m spellbench.human.manabrew.deny_proxy [--port 9450]``
"""

from __future__ import annotations

import argparse
import asyncio

REPLY = (b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n"
         b"Cache-Control: no-store\r\n\r\n")


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        try:
            await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError):
            pass
        writer.write(REPLY)
        await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            writer.close()
        except OSError:
            pass


async def serve(port: int) -> None:
    server = await asyncio.start_server(handle, "127.0.0.1", port)
    print(f"deny proxy on 127.0.0.1:{port}: every request is refused with 403", flush=True)
    async with server:
        await server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=9450)
    args = parser.parse_args(argv)
    try:
        asyncio.run(serve(args.port))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
