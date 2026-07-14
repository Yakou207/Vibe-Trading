from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from fintech_quant.reports.pnl_curve import (
    build_pnl_curve,
    validate_pnl_curve,
)


ROOT = Path(__file__).resolve().parents[1]


def test_build_pnl_curve_normalizes_three_aligned_series(tmp_path: Path) -> None:
    baseline = _write_report(
        tmp_path / "baseline.json",
        [("2026-01-02", 200.0), ("2026-01-05", 220.0)],
    )
    risk = _write_report(
        tmp_path / "risk.json",
        [("2026-01-02", 400.0), ("2026-01-05", 460.0)],
    )
    benchmark = _write_benchmark(
        tmp_path / "benchmark.csv",
        [("2026-01-02", 1000.0), ("2026-01-05", 1050.0)],
    )

    payload = build_pnl_curve(
        baseline_report=baseline,
        risk_controlled_report=risk,
        benchmark=benchmark,
    )

    assert payload["schema_version"] == 1
    assert payload["initial_equity"] == 100000.0
    assert payload["dates"] == ["2026-01-02", "2026-01-05"]
    series = payload["series"]
    assert series["baseline"]["equity"] == [100000.0, 110000.0]
    assert series["risk_controlled"]["pnl"] == [0.0, 15000.0]
    assert series["csi300"]["return"] == [0.0, 0.05]
    inputs = payload["inputs"]
    assert inputs["baseline_report"]["sha256"] == hashlib.sha256(
        baseline.read_bytes()
    ).hexdigest()
    assert inputs["risk_controlled_report"]["bytes"] == risk.stat().st_size
    assert inputs["benchmark"]["path"] == str(benchmark.resolve())
    validate_pnl_curve(payload)


def test_build_pnl_curve_rejects_strategy_date_mismatch(tmp_path: Path) -> None:
    baseline = _write_report(tmp_path / "baseline.json", [("2026-01-02", 100.0)])
    risk = _write_report(tmp_path / "risk.json", [("2026-01-05", 100.0)])
    benchmark = _write_benchmark(tmp_path / "benchmark.csv", [("2026-01-02", 1000.0)])

    with pytest.raises(ValueError, match="matching dates"):
        build_pnl_curve(
            baseline_report=baseline,
            risk_controlled_report=risk,
            benchmark=benchmark,
        )


def test_build_pnl_curve_ignores_nested_equity_curve_key(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "metadata": {
                    "equity_curve": [{"trade_date": "2020-01-01", "equity": 1.0}]
                },
                "equity_curve": [
                    {"trade_date": "2026-01-02", "equity": 100.0},
                    {"trade_date": "2026-01-05", "equity": 110.0},
                ],
            }
        ),
        encoding="utf-8",
    )
    risk = _write_report(
        tmp_path / "risk.json",
        [("2026-01-02", 100.0), ("2026-01-05", 110.0)],
    )
    benchmark = _write_benchmark(
        tmp_path / "benchmark.csv",
        [("2026-01-02", 1000.0), ("2026-01-05", 1100.0)],
    )

    payload = build_pnl_curve(
        baseline_report=baseline,
        risk_controlled_report=risk,
        benchmark=benchmark,
    )

    assert payload["dates"] == ["2026-01-02", "2026-01-05"]
    assert payload["series"]["baseline"]["return"][-1] == 0.1


def test_build_pnl_curve_rejects_duplicate_strategy_date(tmp_path: Path) -> None:
    duplicate = [("2026-01-02", 100.0), ("2026-01-02", 101.0)]
    baseline = _write_report(tmp_path / "baseline.json", duplicate)
    risk = _write_report(tmp_path / "risk.json", duplicate)
    benchmark = _write_benchmark(tmp_path / "benchmark.csv", [("2026-01-02", 1000.0)])

    with pytest.raises(ValueError, match="strictly increasing"):
        build_pnl_curve(
            baseline_report=baseline,
            risk_controlled_report=risk,
            benchmark=benchmark,
        )


def test_build_pnl_curve_rejects_missing_benchmark_date(tmp_path: Path) -> None:
    points = [("2026-01-02", 100.0), ("2026-01-05", 101.0)]
    baseline = _write_report(tmp_path / "baseline.json", points)
    risk = _write_report(tmp_path / "risk.json", points)
    benchmark = _write_benchmark(tmp_path / "benchmark.csv", [("2026-01-02", 1000.0)])

    with pytest.raises(ValueError, match="missing strategy dates"):
        build_pnl_curve(
            baseline_report=baseline,
            risk_controlled_report=risk,
            benchmark=benchmark,
        )


@pytest.mark.parametrize("initial", [0.0, float("nan")])
def test_build_pnl_curve_rejects_invalid_initial_equity(
    tmp_path: Path,
    initial: float,
) -> None:
    points = [("2026-01-02", initial), ("2026-01-05", 101.0)]
    baseline = _write_report(tmp_path / "baseline.json", points)
    risk = _write_report(tmp_path / "risk.json", points)
    benchmark = _write_benchmark(
        tmp_path / "benchmark.csv",
        [("2026-01-02", 1000.0), ("2026-01-05", 1001.0)],
    )

    with pytest.raises(ValueError, match="initial equity"):
        build_pnl_curve(
            baseline_report=baseline,
            risk_controlled_report=risk,
            benchmark=benchmark,
        )


def test_build_pnl_curve_rejects_non_finite_later_value(tmp_path: Path) -> None:
    points = [("2026-01-02", 100.0), ("2026-01-05", float("inf"))]
    baseline = _write_report(tmp_path / "baseline.json", points)
    risk = _write_report(tmp_path / "risk.json", points)
    benchmark = _write_benchmark(
        tmp_path / "benchmark.csv",
        [("2026-01-02", 1000.0), ("2026-01-05", 1001.0)],
    )

    with pytest.raises(ValueError, match="finite"):
        build_pnl_curve(
            baseline_report=baseline,
            risk_controlled_report=risk,
            benchmark=benchmark,
        )


def test_validate_pnl_curve_rejects_internal_inconsistency(tmp_path: Path) -> None:
    payload = _valid_payload(tmp_path)
    payload["series"]["baseline"]["pnl"][1] = 99.0

    with pytest.raises(ValueError, match="inconsistent"):
        validate_pnl_curve(payload)


def test_build_pnl_curve_cli_writes_deterministic_json(tmp_path: Path) -> None:
    points = [("2026-01-02", 100.0), ("2026-01-05", 105.0)]
    baseline = _write_report(tmp_path / "baseline.json", points)
    risk = _write_report(tmp_path / "risk.json", points)
    benchmark = _write_benchmark(
        tmp_path / "benchmark.csv",
        [("2026-01-02", 1000.0), ("2026-01-05", 1050.0)],
    )
    output = tmp_path / "pnl_curve.json"
    command = [
        sys.executable,
        "scripts/build_pnl_curve.py",
        "--baseline-report",
        str(baseline),
        "--risk-controlled-report",
        str(risk),
        "--benchmark",
        str(benchmark),
        "--output",
        str(output),
    ]

    first = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0, first.stderr
    first_bytes = output.read_bytes()
    second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)

    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == f"pnl_curve_path={output}"
    assert output.read_bytes() == first_bytes
    validate_pnl_curve(json.loads(output.read_text(encoding="utf-8")))


def _valid_payload(tmp_path: Path) -> dict[str, object]:
    points = [("2026-01-02", 100.0), ("2026-01-05", 105.0)]
    return build_pnl_curve(
        baseline_report=_write_report(tmp_path / "baseline.json", points),
        risk_controlled_report=_write_report(tmp_path / "risk.json", points),
        benchmark=_write_benchmark(
            tmp_path / "benchmark.csv",
            [("2026-01-02", 1000.0), ("2026-01-05", 1050.0)],
        ),
    )


def _write_report(path: Path, points: list[tuple[str, float]]) -> Path:
    path.write_text(
        json.dumps(
            {
                "before": {"equity_curve_note": "not the target array"},
                "equity_curve": [
                    {"trade_date": trade_date, "equity": equity}
                    for trade_date, equity in points
                ],
                "after": [1, 2, 3],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_benchmark(path: Path, points: list[tuple[str, float]]) -> Path:
    path.write_text(
        "trade_date,index_close\n"
        + "".join(f"{trade_date},{value}\n" for trade_date, value in points),
        encoding="utf-8",
    )
    return path
