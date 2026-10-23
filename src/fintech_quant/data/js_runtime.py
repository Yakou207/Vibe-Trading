"""Serialise akshare calls that run JavaScript.

akshare decodes some Sina and CNInfo responses (A-share daily bars, US quotes, CNInfo industry
history) with an embedded V8 engine (py_mini_racer). V8 aborts the whole process when two threads
start an engine at the same time, which would take down the multi-threaded trading desk. Every such
call in that process goes through ``js_call``; the timeout makes a caller fail instead of waiting
forever behind a hung request.
"""

from __future__ import annotations

import threading
from typing import Callable, TypeVar

T = TypeVar("T")
JS_LOCK = threading.Lock()
LOCK_TIMEOUT = 45.0


def js_call(fn: Callable[..., T], *args: object, **kwargs: object) -> T:
    if not JS_LOCK.acquire(timeout=LOCK_TIMEOUT):
        raise TimeoutError("another JavaScript-decoded request is still running")
    try:
        return fn(*args, **kwargs)
    finally:
        JS_LOCK.release()
