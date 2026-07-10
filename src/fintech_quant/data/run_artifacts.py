from __future__ import annotations

import hashlib
import json
import platform
import shutil
from pathlib import Path
from typing import Iterable, Mapping, Sequence


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RunArtifactStore:
    def __init__(
        self,
        root: Path,
        run_id: str,
        *,
        layer: str,
        parent_manifest: str | None = None,
    ) -> None:
        if not run_id.strip():
            raise ValueError("run_id is required")
        if layer not in {"raw", "processed"}:
            raise ValueError("layer must be raw or processed")
        self.run_id = run_id
        self.layer = layer
        self.parent_manifest = parent_manifest
        self.run_dir = root / run_id
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self._artifacts: list[dict[str, object]] = []

    def write_jsonl(
        self,
        relative_path: str,
        rows: Iterable[Mapping[str, object]],
    ) -> Path:
        path = self._new_artifact_path(relative_path)
        row_count = 0
        with path.open("x", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")
                row_count += 1
        self._record_artifact(path, row_count)
        return path

    def copy_artifact(self, source: Path, relative_path: str) -> Path:
        path = self._new_artifact_path(relative_path)
        with source.open("rb") as source_handle, path.open("xb") as target_handle:
            shutil.copyfileobj(source_handle, target_handle)
        with path.open("rb") as handle:
            row_count = sum(1 for line in handle if line.strip())
        self._record_artifact(path, row_count)
        return path

    def write_manifest(
        self,
        *,
        request: Mapping[str, object],
        scopes: Sequence[Mapping[str, object]],
        created_at: str,
        git_sha: str,
        provider_versions: Mapping[str, str],
    ) -> Path:
        path = self.run_dir / "manifest.json"
        if path.exists():
            raise FileExistsError(path)
        payload = {
            "run_id": self.run_id,
            "layer": self.layer,
            "created_at": created_at,
            "git_sha": git_sha,
            "python_version": platform.python_version(),
            "provider_versions": dict(sorted(provider_versions.items())),
            "parent_manifest": self.parent_manifest,
            "request": dict(request),
            "scopes": [dict(scope) for scope in scopes],
            "artifacts": sorted(self._artifacts, key=lambda item: str(item["path"])),
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    def _new_artifact_path(self, relative_path: str) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("artifact path must stay inside the run directory")
        path = self.run_dir / relative
        if path.exists():
            raise FileExistsError(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _record_artifact(self, path: Path, row_count: int) -> None:
        self._artifacts.append(
            {
                "path": str(path.relative_to(self.run_dir)),
                "bytes": path.stat().st_size,
                "row_count": row_count,
                "sha256": sha256_file(path),
            }
        )
