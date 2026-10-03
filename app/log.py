"""JSONL log lines on stdout, one event per line, for CloudWatch."""

import json
import sys
import time


def emit(event: str, **fields: object) -> None:
    line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event, **fields}
    sys.stdout.write(json.dumps(line, default=str) + "\n")
    sys.stdout.flush()
