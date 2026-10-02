"""Local inference stand-in: records every process start and decision, with no network."""
from pathlib import Path
import sys

from bot_one_land import OneLand
from spellbench.bot import serve


class CountedBot(OneLand):
    def choose(self, decision):
        with marker.open("a", encoding="utf-8") as handle:
            handle.write("choose\n")
        return super().choose(decision)


if __name__ == "__main__":
    marker = Path(sys.argv[2].split("=", 1)[1])
    with marker.open("a", encoding="utf-8") as handle:
        handle.write("start\n")
    raise SystemExit(serve(CountedBot(), name=sys.argv[1], version="1.0.0"))
