from __future__ import annotations

from datetime import date
from pathlib import Path

from fintech_quant.information.stock_intel import prune_daily_cache


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")


def test_prune_keeps_thirty_days_and_never_touches_model_call_records(tmp_path: Path) -> None:
    for day in ("2026-09-21", "2026-09-22", "2026-10-22"):
        _touch(tmp_path / day / "600011.SH.json")
        _touch(tmp_path / "live" / day / "bars" / "300624.SZ.json")
        _touch(tmp_path / "event_llm" / day / "600011.SH-abc.json")
    _touch(tmp_path / "notes" / "keep.txt")

    removed = prune_daily_cache(tmp_path, today=date(2026, 10, 22))

    assert removed == [tmp_path / "2026-09-21", tmp_path / "live" / "2026-09-21"]
    assert (tmp_path / "2026-09-22").is_dir()  # exactly 30 days old is kept
    assert (tmp_path / "live" / "2026-10-22").is_dir()
    assert len(list((tmp_path / "event_llm").iterdir())) == 3
    assert (tmp_path / "notes" / "keep.txt").exists()


def test_prune_tolerates_a_missing_cache(tmp_path: Path) -> None:
    assert prune_daily_cache(tmp_path / "absent", today=date(2026, 10, 22)) == []
