"""One JSON line per event on stdout.

Only stable machine fields are ever passed in: request id, principal id, route template, job id, status, runtime exit/code and
duration. Headers, bodies, environment values, runtime stderr and exception text are never logged.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from typing import Any

_LOCK = threading.Lock()


def emit(record: dict[str, Any]) -> None:
    line = json.dumps({"ts": round(time.time(), 3), **record}, ensure_ascii=False, separators=(",", ":"), default=str)
    with _LOCK:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
