from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_passing_data_health_rejects_mismatched_research_input(tmp_path: Path) -> None:
    from fintech_quant.data.run_artifacts import sha256_file
    from fintech_quant.research.preflight import require_passing_data_health

    features = tmp_path / "features.csv"
    features.write_text("original\n", encoding="utf-8")
    health = tmp_path / "health.json"
    health.write_text(
        json.dumps(
            {
                "passed": True,
                "inputs": {"features": {"path": str(features), "sha256": sha256_file(features)}},
            }
        ),
        encoding="utf-8",
    )
    features.write_text("changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="input hash mismatch: features"):
        require_passing_data_health(health, {"features": features})
