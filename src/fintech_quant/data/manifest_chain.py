from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from fintech_quant.data.run_artifacts import sha256_file


@dataclass(frozen=True)
class VerifiedManifest:
    path: Path
    payload: Mapping[str, object]
    artifacts: Mapping[str, Path]


def load_verified_manifest(path: Path, *, expected_layer: str) -> VerifiedManifest:
    resolved = path.resolve()
    payload = _load_manifest(resolved, expected_layer)
    return VerifiedManifest(
        path=resolved,
        payload=payload,
        artifacts=_verified_artifacts(resolved, payload, expected_layer),
    )


def load_verified_manifest_chain(
    path: Path,
    *,
    expected_layer: str,
) -> tuple[VerifiedManifest, ...]:
    seen: set[Path] = set()
    newest_first: list[VerifiedManifest] = []
    current: Path | None = path.resolve()
    while current is not None:
        if current in seen:
            raise ValueError(f"manifest parent cycle: {current}")
        seen.add(current)
        verified = load_verified_manifest(current, expected_layer=expected_layer)
        payload = verified.payload
        newest_first.append(verified)
        parent = payload.get("parent_manifest")
        if parent in (None, ""):
            current = None
        else:
            parent_path = Path(str(parent))
            current = (
                parent_path.resolve()
                if parent_path.is_absolute()
                else (current.parent / parent_path).resolve()
            )
    return tuple(reversed(newest_first))


def _load_manifest(path: Path, expected_layer: str) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"manifest must contain an object: {path}")
    if payload.get("layer") != expected_layer:
        raise ValueError(f"manifest layer must be {expected_layer}: {path}")
    return payload


def _verified_artifacts(
    manifest_path: Path,
    manifest: Mapping[str, object],
    layer: str,
) -> dict[str, Path]:
    raw_artifacts = manifest.get("artifacts", [])
    if not isinstance(raw_artifacts, list):
        raise ValueError(f"manifest artifacts must be a list: {manifest_path}")
    run_dir = manifest_path.parent.resolve()
    result: dict[str, Path] = {}
    for item in raw_artifacts:
        if not isinstance(item, Mapping):
            raise ValueError(f"manifest artifact must be an object: {manifest_path}")
        relative = Path(str(item.get("path", "")))
        if not relative.parts or relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"artifact path escapes manifest run: {relative}")
        relative_text = relative.as_posix()
        if relative_text in result:
            raise ValueError(f"duplicate manifest artifact: {relative_text}")
        artifact_path = (run_dir / relative).resolve()
        if run_dir not in artifact_path.parents:
            raise ValueError(f"artifact path escapes manifest run: {relative_text}")
        if not artifact_path.is_file():
            raise ValueError(f"manifest artifact is missing: {relative_text}")
        if sha256_file(artifact_path) != item.get("sha256"):
            raise ValueError(f"{layer} artifact hash mismatch: {relative_text}")
        result[relative_text] = artifact_path
    return result
