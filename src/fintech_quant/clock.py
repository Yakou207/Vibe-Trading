"""The project's clock: A-share research runs on Shanghai time (UTC+8), whatever zone the machine
running it is set to. The desk Mac runs on GMT, where ``date.today()`` is still yesterday until
08:00 Shanghai time, which covers the whole pre-market window.

Use ``shanghai_today()`` / ``shanghai_now()`` instead of ``date.today()`` / ``datetime.now()``.
Timestamps that already carry an explicit offset (the UTC ``created_at`` values in evidence
manifests) name an exact instant and are left as they are.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


def shanghai_now() -> datetime:
    return datetime.now(SHANGHAI)


def shanghai_today() -> date:
    return shanghai_now().date()


def machine_local_to_shanghai(stamp: str) -> datetime:
    """A naive ``YYYY-MM-DD HH:MM:SS`` produced by ``datetime.fromtimestamp`` on this machine (as
    AkShare does for the Tonghuashun and Futu flashes), as an aware Shanghai time."""
    return datetime.fromisoformat(stamp).astimezone(SHANGHAI)
