from __future__ import annotations

import time
from datetime import date, datetime, timezone

import pytest

from fintech_quant import clock
from fintech_quant.information.global_intel import _news_item
from fintech_quant.reports.picker import _shanghai_date


@pytest.fixture
def gmt_machine(monkeypatch):
    """The desk Mac runs on GMT."""
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


class _Frozen(datetime):
    """02:16 on 2026-11-24 in Shanghai, still 2026-11-23 on a GMT clock."""

    @classmethod
    def now(cls, tz=None):
        moment = datetime(2026, 11, 23, 18, 16, tzinfo=timezone.utc)
        return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)


def test_today_is_the_shanghai_date_before_8am_on_a_gmt_machine(gmt_machine, monkeypatch) -> None:
    monkeypatch.setattr(clock, "datetime", _Frozen)
    assert clock.shanghai_today() == date(2026, 11, 24)
    assert clock.shanghai_now().utcoffset().total_seconds() == 8 * 3600


def test_machine_local_stamps_become_shanghai_time(gmt_machine) -> None:
    assert clock.machine_local_to_shanghai("2026-11-23 17:52:28") == datetime(2026, 11, 24, 1, 52, 28, tzinfo=clock.SHANGHAI)


def test_tonghuashun_flash_is_shown_in_shanghai_time(gmt_machine) -> None:
    row = {"标题": "英伟达涨幅收窄至30%", "内容": "", "发布时间": "2026-11-23 17:52:28", "链接": ""}
    assert _news_item(row, "同花顺全球快讯", machine_local=True)["published_at"] == "2026-11-24 01:52:28"
    em = {"标题": "英伟达股价涨幅收窄至30%", "摘要": "", "发布时间": "2026-11-24 01:51:39", "链接": ""}
    assert _news_item(em, "东方财富全球快讯")["published_at"] == "2026-11-24 01:51:39"


def test_model_spend_counts_a_call_on_its_shanghai_date(gmt_machine) -> None:
    assert _shanghai_date("2026-11-23T18:16:00+00:00") == date(2026, 11, 24)
