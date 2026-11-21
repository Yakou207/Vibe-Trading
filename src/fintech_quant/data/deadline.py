from __future__ import annotations

import threading
from typing import Callable, TypeVar

T = TypeVar("T")


def call_with_deadline(seconds: float, function: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Many AkShare calls use requests without a timeout, so a stalled connection never returns.
    Run the call in a daemon thread and raise TimeoutError after `seconds`; the stuck thread is
    abandoned and does not keep the process alive."""
    outcome: dict[str, object] = {}

    def call() -> None:
        try:
            outcome["value"] = function(*args, **kwargs)
        except BaseException as exc:  # re-raised in the caller's thread
            outcome["error"] = exc

    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise TimeoutError(f"provider call did not return within {seconds:g}s")
    if "error" in outcome:
        raise outcome["error"]  # type: ignore[misc]
    return outcome["value"]  # type: ignore[return-value]
