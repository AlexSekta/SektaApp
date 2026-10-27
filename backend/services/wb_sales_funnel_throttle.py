"""Shared in-process throttle for WB Sales Funnel requests.

Both the history collector and the live collector use this wrapper so their
requests cannot overlap or violate the configured spacing in one process.
"""
import threading
import time

_LOCK = threading.Lock()
_LAST = 0.0
_GAP = 65.0


def fetch_throttled(fetch_fn, db, day):
    global _LAST
    with _LOCK:
        remaining = _GAP - (time.monotonic() - _LAST)
        if _LAST and remaining > 0:
            time.sleep(remaining)
        _LAST = time.monotonic()  # a failed API call also consumes rate budget
        return fetch_fn(db, day)
