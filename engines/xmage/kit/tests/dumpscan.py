"""Scans dumped priority-anchor decisions (front --dump) for observation features: command-zone objects, tokens,
face-down objects, stack entries and pending triggers, with the cards involved.

    python dumpscan.py DUMP_DIR
"""

import glob
import json
import os
import sys
from collections import Counter


def main():
    feats = Counter()
    names = {}
    files = sorted(glob.glob(os.path.join(sys.argv[1], "decision-*.json")))
    for f in files:
        d = json.load(open(f, encoding="utf-8"))["decision"]["observation"]
        for p in d["players"]:
            for c in p.get("command") or []:
                feats["command"] += 1
                names.setdefault("command", Counter())[c.get("card_name")] += 1
            for c in p.get("battlefield") or []:
                if c.get("token"):
                    feats["token"] += 1
                    names.setdefault("token", Counter())[c.get("card_name")] += 1
                if c.get("face_down"):
                    feats["face_down"] += 1
        for e in d.get("stack") or []:
            feats["stack:" + e["stack_kind"]] += 1
            names.setdefault("stack", Counter())[e.get("card_name")] += 1
        if d.get("pending_triggers"):
            feats["pending_triggers"] += 1
            for t in d["pending_triggers"]:
                names.setdefault("pending", Counter())[t.get("source_name")] += 1
    print(json.dumps({"decisions": len(files), "features": feats,
                      "names": {k: dict(v.most_common(12)) for k, v in names.items()}}, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
