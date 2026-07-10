from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path


def test_build_historical_index_membership_script_writes_intervals(tmp_path: Path) -> None:
    anchor_path = tmp_path / "anchor.csv"
    adjustments_path = tmp_path / "adjustments.csv"
    output_path = tmp_path / "membership.csv"
    anchor_path.write_text(
        "symbol,as_of,source\n"
        "000001,2026-06-15,csindex\n"
        "600000,2026-06-15,csindex\n"
        "600519,2026-06-15,csindex\n",
        encoding="utf-8",
    )
    adjustments_path.write_text(
        "effective_date,removed_symbol,added_symbol,source_url\n"
        "2026-06-15,000002,600519,https://official.example/adjustment.pdf\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_historical_index_membership.py",
            "--anchor",
            str(anchor_path),
            "--adjustments",
            str(adjustments_path),
            "--index-code",
            "000300",
            "--start",
            "2026-06-01",
            "--expected-members",
            "3",
            "--source-fetched-at",
            "2026-07-10T12:00:00+08:00",
            "--output",
            str(output_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    with output_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert tuple(rows[0]) == (
        "index_code",
        "symbol",
        "member_from",
        "member_to",
        "source",
        "source_fetched_at",
    )
    assert {row["symbol"] for row in rows if row["member_to"] == "2026-06-15"} == {"000002.SZ"}
    assert {row["symbol"] for row in rows if row["member_from"] == "2026-06-15"} == {"600519.SH"}
    assert "active_members=3" in completed.stdout


def test_build_historical_index_membership_script_rejects_missing_source_url(tmp_path: Path) -> None:
    anchor_path = tmp_path / "anchor.csv"
    adjustments_path = tmp_path / "adjustments.csv"
    anchor_path.write_text(
        "symbol,as_of,source\n000001,2026-06-15,csindex\n",
        encoding="utf-8",
    )
    adjustments_path.write_text(
        "effective_date,removed_symbol,added_symbol,source_url\n2026-06-15,000002,000001,\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_historical_index_membership.py",
            "--anchor",
            str(anchor_path),
            "--adjustments",
            str(adjustments_path),
            "--index-code",
            "000300",
            "--start",
            "2026-06-01",
            "--expected-members",
            "1",
            "--output",
            str(tmp_path / "membership.csv"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "source_url is required" in completed.stderr
