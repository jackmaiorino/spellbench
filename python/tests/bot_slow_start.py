"""Test fixture: a first-candidate bot that takes argv[1] seconds to start (protocol v2).

Stands in for a neural-network bot that loads its weights before it can
answer ``hello``; it answers every ``choose`` with candidate 0.
"""

from __future__ import annotations

import sys
import time

time.sleep(float(sys.argv[1]))

from spellbench.bot import serve  # noqa: E402

if __name__ == "__main__":
    sys.exit(serve(choose=lambda decision: decision.candidates[0].candidate_id, name="slow", version="1.0.0"))
