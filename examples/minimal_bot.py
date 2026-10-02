"""The minimal Spellbench v2 bot (spec 10.6): it always picks candidate 0.

The host ignores extra fields in answers but reads every answer as strict JSON (spec 2):
no floats, no duplicate keys, and no nesting deeper than 64 levels.
"""
import json
import sys

for line in sys.stdin.buffer:  # bytes: never decoded with the locale's code page
    request = json.loads(line)
    reply = {"protocol": "spellbench/v2", "request_id": request["request_id"]}
    if request["request_type"] == "hello":
        reply.update(response_type="hello_ok", bot={"name": "minimal", "version": "1.0.0"})
    elif request["request_type"] == "choose":
        reply.update(response_type="choice", selection={"candidate_id": 0})
    else:
        reply.update(response_type="ack")
    sys.stdout.write(json.dumps(reply) + "\n")
    sys.stdout.flush()
