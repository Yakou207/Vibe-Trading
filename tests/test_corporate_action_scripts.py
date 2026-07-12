from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path


def test_collect_and_build_corporate_actions_preserve_raw_and_normalize_terms(
    tmp_path: Path,
) -> None:
    membership = tmp_path / "membership.csv"
    membership.write_text("symbol\n000001.SZ\n", encoding="utf-8")
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        json.dumps(
            {
                "000001.SZ": [
                    {
                        "实施方案公告日期": "2026-06-05",
                        "股权登记日": "2026-06-11",
                        "除权日": "2026-06-12",
                        "派息比例": 3.6,
                        "送股比例": 2.0,
                        "转增比例": 1.0,
                    },
                    {
                        "_action_type": "rights_issue",
                        "公告日期": "2026-07-01",
                        "除权基准日": "2026-07-10",
                        "配股上市日": "2026-07-20",
                        "配股比例": 2.0,
                        "配股价格": 8.0,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    collected = subprocess.run(
        [
            sys.executable,
            "scripts/collect_corporate_actions.py",
            "--source",
            "fixture",
            "--fixture-input",
            str(fixture),
            "--membership",
            str(membership),
            "--start",
            "2026-01-01",
            "--end",
            "2026-12-31",
            "--run-id",
            "actions-raw",
            "--raw-root",
            str(tmp_path / "raw"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert collected.returncode == 0, collected.stderr
    raw_manifest = tmp_path / "raw/actions-raw/manifest.json"
    raw_payload = json.loads(raw_manifest.read_text(encoding="utf-8"))
    assert raw_payload["artifacts"][0]["path"] == "corporate_actions/000001.SZ.jsonl"

    built = subprocess.run(
        [
            sys.executable,
            "scripts/build_corporate_actions.py",
            "--raw-manifest",
            str(raw_manifest),
            "--run-id",
            "actions-processed",
            "--processed-root",
            str(tmp_path / "processed"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    output = tmp_path / "processed/actions-processed/corporate_actions.csv"
    with output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {
            "symbol": "000001.SZ",
            "ex_date": "2026-06-12",
            "action_type": "distribution",
            "cash_dividend_per_share": "0.36",
            "share_multiplier": "1.3",
            "rights_ratio": "0.0",
            "rights_price": "0.0",
            "listing_date": "",
            "source": "akshare_cninfo_dividend",
        },
        {
            "symbol": "000001.SZ",
            "ex_date": "2026-07-10",
            "action_type": "rights_issue",
            "cash_dividend_per_share": "0.0",
            "share_multiplier": "1.0",
            "rights_ratio": "0.2",
            "rights_price": "8.0",
            "listing_date": "2026-07-20",
            "source": "akshare_cninfo_rights_issue",
        },
    ]
