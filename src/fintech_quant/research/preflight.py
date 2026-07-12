from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from fintech_quant.data.run_artifacts import sha256_file


def require_passing_data_health(
    path: Path | None,
    inputs: Mapping[str, Path | None] | None = None,
) -> None:
    if path is None:
        raise ValueError("--data-health is required in point-in-time mode")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("passed") is not True:
        raise ValueError(f"data health report did not pass: {path}")
    if inputs is None:
        return
    recorded = payload.get("inputs")
    if not isinstance(recorded, dict):
        raise ValueError("data health report does not record input hashes")
    for name, input_path in inputs.items():
        if input_path is None:
            continue
        reference = recorded.get(name)
        if not isinstance(reference, dict) or reference.get("sha256") != sha256_file(input_path):
            raise ValueError(f"data health input hash mismatch: {name}")
