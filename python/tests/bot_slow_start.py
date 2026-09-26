"""Test fixture: a first-candidate bot that takes argv[1] seconds to start.

Stands in for a neural-network bot that loads its weights before it can
answer ``hello``; it answers every ``choose`` with candidate 0.
"""

from __future__ import annotations

import sys
import time

time.sleep(float(sys.argv[1]))

from spellbench import agent_server  # noqa: E402

if __name__ == "__main__":
    sys.exit(agent_server.serve(choose=lambda decision: 0, bot_name="slow", bot_version="1.0.0"))
