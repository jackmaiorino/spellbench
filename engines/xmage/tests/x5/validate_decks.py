"""X5: every catalog deck through the engine's validate_deck (spec 9.6), and the hello declarations X5 relies on.

For each deck of catalog.json: validate_deck with the deck as an inline decklist (the engine resolves every name
against its card database), and, when the running engine's hello_ok catalog lists it, again by catalog_id. Also
checks that hello_ok's catalog equals catalog.json (when --expect-catalog is given) and that the engine declares
no probe ("fairness: validator only", spec 9.7 and 12.2). One JSON report on stdout; exit 1 on any failure.

    PYTHONPATH=<p2>/python python validate_decks.py [--expect-catalog] -- <engine argv...>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from spellbench.errors import RemoteError
from spellbench.host.engine_process import EngineProcess

CATALOG = Path(__file__).resolve().parents[2] / "overlay/src/main/resources/mage/player/spellbench/catalog.json"


def main(argv: list[str]) -> int:
    split = argv.index("--")
    options, engine_argv = argv[:split], argv[split + 1:]
    decks = json.loads(CATALOG.read_text(encoding="utf-8"))
    report: dict = {"decks": [], "failures": []}
    with EngineProcess(engine_argv, timeout_s=300) as engine:
        hello = engine.hello()
        raw = engine.last_response or {}
        offered = {d["catalog_id"] for d in raw.get("catalog", [])}
        report["hello"] = {
            "formats": raw.get("formats"),
            "deck_sources": raw.get("deck_sources"),
            "fairness": raw.get("fairness"),
            "catalog_size": len(offered),
            "engine": raw.get("engine"),
        }
        if raw.get("fairness") != {"noninterference_probe": False}:
            report["failures"].append(f"fairness declares {raw.get('fairness')}, not validator only")
        if "--expect-catalog" in options:
            declared = [{"catalog_id": d["catalog_id"], "name": d["name"], "decklist": d["decklist"]}
                        for d in raw.get("catalog", [])]
            expected = [{"catalog_id": d["catalog_id"], "name": d["name"], "decklist": d["decklist"]} for d in decks]
            if declared != expected:
                report["failures"].append("hello_ok catalog differs from catalog.json")
        for deck in decks:
            row = {"catalog_id": deck["catalog_id"], "format": deck["formats"][0],
                   "cards": sum(r["count"] for r in deck["decklist"])}
            for how, kwargs in (("decklist", {"decklist": deck["decklist"]}),
                                ("catalog_id", {"catalog_id": deck["catalog_id"]})):
                if how == "catalog_id" and deck["catalog_id"] not in offered:
                    row[how] = "not in this build's catalog"
                    continue
                try:
                    engine.validate_deck(format=deck["formats"][0], **kwargs)
                    row[how] = "deck_ok"
                except RemoteError as exc:
                    row[how] = f"refused: {exc}"
                    report["failures"].append(f"{deck['catalog_id']} ({how}): {exc}")
            report["decks"].append(row)
    report["verdict"] = "PASS" if not report["failures"] else "FAIL"
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return 0 if not report["failures"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
