from __future__ import annotations

import json
import pickle
import shutil
from collections import deque
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import torch

from fintech_quant.training.dqn import (
    ACTIONS,
    DQNConfig,
    DQNModel,
    DQNNetwork,
    DQNTrainingRun,
    FeatureScaler,
    Transition,
)


def save_dqn_checkpoint(
    run: DQNTrainingRun,
    checkpoint_root: Path | str,
    checkpoint_id: str | None = None,
    metadata: dict[str, object] | None = None,
    metrics: dict[str, object] | None = None,
    max_checkpoints: int = 10,
) -> Path:
    root = Path(checkpoint_root)
    checkpoints_dir = root / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_id = checkpoint_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    checkpoint_path = checkpoints_dir / checkpoint_id
    if checkpoint_path.exists():
        shutil.rmtree(checkpoint_path)
    checkpoint_path.mkdir(parents=True)

    metadata = {**run.metadata, **(metadata or {})}
    metrics = {**run.metrics, **(metrics or {})}

    torch.save(run.model.network.state_dict(), checkpoint_path / "model.pt")
    torch.save(run.target_network.state_dict(), checkpoint_path / "target_model.pt")
    torch.save(run.optimizer_state, checkpoint_path / "optimizer.pt")
    with (checkpoint_path / "replay_buffer.pkl").open("wb") as handle:
        pickle.dump(list(run.replay), handle)
    _write_json(checkpoint_path / "scaler.json", _scaler_payload(run.model.scaler))
    _write_json(checkpoint_path / "config.json", asdict(run.model.config))
    _write_json(
        checkpoint_path / "training_state.json",
        {
            "checkpoint_id": checkpoint_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "episodes_trained": run.episodes_trained,
            "training_steps": run.model.training_steps,
            "scaler_fit_rows": run.model.scaler_fit_rows,
            "replay_size": len(run.replay),
            "metadata": metadata,
        },
    )
    _write_json(checkpoint_path / "metrics.json", metrics)
    _update_manifest(
        root=root,
        checkpoint_id=checkpoint_id,
        metadata=metadata,
        metrics=metrics,
        max_checkpoints=max_checkpoints,
    )
    return checkpoint_path


def load_latest_dqn_checkpoint(checkpoint_root: Path | str) -> DQNTrainingRun:
    root = Path(checkpoint_root)
    manifest = _read_json(root / "manifest.json")
    latest = manifest.get("latest")
    if not latest:
        raise FileNotFoundError(f"No latest DQN checkpoint recorded in {root}.")
    return load_dqn_checkpoint(root / "checkpoints" / str(latest))


def load_dqn_checkpoint(checkpoint_path: Path | str) -> DQNTrainingRun:
    path = Path(checkpoint_path)
    config = _config_from_payload(_read_json(path / "config.json"))
    scaler = _scaler_from_payload(_read_json(path / "scaler.json"))
    network = DQNNetwork(
        input_size=len(scaler.columns) + 1,
        hidden_layers=config.hidden_layers,
        output_size=len(ACTIONS),
    )
    target_network = DQNNetwork(
        input_size=len(scaler.columns) + 1,
        hidden_layers=config.hidden_layers,
        output_size=len(ACTIONS),
    )
    network.load_state_dict(torch.load(path / "model.pt", map_location="cpu"))
    target_network.load_state_dict(torch.load(path / "target_model.pt", map_location="cpu"))
    optimizer_state = torch.load(path / "optimizer.pt", map_location="cpu")
    with (path / "replay_buffer.pkl").open("rb") as handle:
        replay_items = pickle.load(handle)
    replay = deque(
        (Transition(*item) if not isinstance(item, Transition) else item for item in replay_items),
        maxlen=config.replay_capacity,
    )
    training_state = _read_json(path / "training_state.json")
    metrics = _read_json(path / "metrics.json")
    model = DQNModel(
        network=network,
        scaler=scaler,
        config=config,
        training_steps=int(training_state["training_steps"]),
        scaler_fit_rows=int(training_state["scaler_fit_rows"]),
    )
    return DQNTrainingRun(
        model=model,
        target_network=target_network,
        optimizer_state=optimizer_state,
        replay=replay,
        episodes_trained=int(training_state["episodes_trained"]),
        metadata=dict(training_state.get("metadata", {})),
        metrics=metrics,
    )


def _update_manifest(
    root: Path,
    checkpoint_id: str,
    metadata: dict[str, object],
    metrics: dict[str, object],
    max_checkpoints: int,
) -> None:
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        manifest = _read_json(manifest_path)
    else:
        manifest = {"latest": "", "checkpoints": []}
    checkpoints = [
        item for item in manifest.get("checkpoints", []) if item.get("id") != checkpoint_id
    ]
    checkpoints.append(
        {
            "id": checkpoint_id,
            "path": f"checkpoints/{checkpoint_id}",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "metadata": metadata,
            "metrics": metrics,
        }
    )
    while len(checkpoints) > max_checkpoints:
        removed = checkpoints.pop(0)
        removed_path = root / str(removed["path"])
        if removed_path.exists():
            shutil.rmtree(removed_path)
    _write_json(manifest_path, {"latest": checkpoint_id, "checkpoints": checkpoints})


def _scaler_payload(scaler: FeatureScaler) -> dict[str, object]:
    return {
        "columns": list(scaler.columns),
        "means": scaler.means,
        "stds": scaler.stds,
    }


def _scaler_from_payload(payload: dict[str, Any]) -> FeatureScaler:
    return FeatureScaler(
        columns=tuple(str(column) for column in payload["columns"]),
        means={str(key): float(value) for key, value in payload["means"].items()},
        stds={str(key): float(value) for key, value in payload["stds"].items()},
    )


def _config_from_payload(payload: dict[str, Any]) -> DQNConfig:
    if isinstance(payload.get("hidden_layers"), list):
        payload = {**payload, "hidden_layers": tuple(payload["hidden_layers"])}
    return DQNConfig(**payload)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
