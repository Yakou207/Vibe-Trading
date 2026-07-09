from __future__ import annotations

import json
import pickle
import shutil
from collections import deque
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from fintech_quant.training.torch_dqn import (
    DQN_ACTIONS,
    FeatureScaler,
    TorchDQNConfig,
    TorchDQNPolicy,
    TorchDQNTrainingRun,
    Transition,
    _build_network,
    _load_torch,
)


def save_torch_dqn_checkpoint(
    run: TorchDQNTrainingRun,
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

    torch = _load_torch()
    merged_metadata = {**run.metadata, **(metadata or {})}
    merged_metrics = {**run.metrics, **(metrics or {})}

    torch.save(run.policy.network.state_dict(), checkpoint_path / "model.pt")
    torch.save(run.target_network.state_dict(), checkpoint_path / "target_model.pt")
    torch.save(run.optimizer_state, checkpoint_path / "optimizer.pt")
    with (checkpoint_path / "replay_buffer.pkl").open("wb") as handle:
        pickle.dump(list(run.replay), handle)
    _write_json(checkpoint_path / "scaler.json", _scaler_payload(run.policy.scaler))
    _write_json(checkpoint_path / "config.json", asdict(run.policy.config))
    _write_json(
        checkpoint_path / "training_state.json",
        {
            "checkpoint_id": checkpoint_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "episodes_trained": run.episodes_trained,
            "training_steps": run.policy.training_steps,
            "state_fields": list(run.policy.state_fields),
            "metadata": merged_metadata,
        },
    )
    _write_json(checkpoint_path / "metrics.json", merged_metrics)
    _update_manifest(root, checkpoint_id, merged_metadata, merged_metrics, max_checkpoints)
    return checkpoint_path


def load_latest_torch_dqn_checkpoint(checkpoint_root: Path | str) -> TorchDQNTrainingRun:
    root = Path(checkpoint_root)
    manifest = _read_json(root / "manifest.json")
    latest = manifest.get("latest")
    if not latest:
        raise FileNotFoundError(f"No latest torch DQN checkpoint recorded in {root}.")
    return load_torch_dqn_checkpoint(root / "checkpoints" / str(latest))


def load_torch_dqn_checkpoint(checkpoint_path: Path | str) -> TorchDQNTrainingRun:
    path = Path(checkpoint_path)
    torch = _load_torch()
    config = _config_from_payload(_read_json(path / "config.json"))
    scaler = _scaler_from_payload(_read_json(path / "scaler.json"))
    training_state = _read_json(path / "training_state.json")
    state_fields = tuple(str(field) for field in training_state["state_fields"])
    input_size = len(state_fields) + 1
    network = _build_network(torch.nn, input_size, config.hidden_layers, len(DQN_ACTIONS))
    target_network = _build_network(torch.nn, input_size, config.hidden_layers, len(DQN_ACTIONS))
    network.load_state_dict(torch.load(path / "model.pt", map_location="cpu"))
    target_network.load_state_dict(torch.load(path / "target_model.pt", map_location="cpu"))
    optimizer_state = torch.load(path / "optimizer.pt", map_location="cpu")
    with (path / "replay_buffer.pkl").open("rb") as handle:
        replay_items = pickle.load(handle)
    replay = deque(
        (item if isinstance(item, Transition) else Transition(*item) for item in replay_items),
        maxlen=config.replay_capacity,
    )
    policy = TorchDQNPolicy(
        network=network,
        scaler=scaler,
        state_fields=state_fields,
        config=config,
        training_steps=int(training_state["training_steps"]),
    )
    return TorchDQNTrainingRun(
        policy=policy,
        target_network=target_network,
        optimizer_state=optimizer_state,
        replay=replay,
        episodes_trained=int(training_state["episodes_trained"]),
        metadata=dict(training_state.get("metadata", {})),
        metrics=_read_json(path / "metrics.json"),
    )


def _update_manifest(
    root: Path,
    checkpoint_id: str,
    metadata: dict[str, object],
    metrics: dict[str, object],
    max_checkpoints: int,
) -> None:
    manifest_path = root / "manifest.json"
    manifest = _read_json(manifest_path) if manifest_path.exists() else {"latest": "", "checkpoints": []}
    checkpoints = [item for item in manifest.get("checkpoints", []) if item.get("id") != checkpoint_id]
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
        "means": list(scaler.means),
        "stds": list(scaler.stds),
    }


def _scaler_from_payload(payload: dict[str, Any]) -> FeatureScaler:
    return FeatureScaler(
        means=tuple(float(value) for value in payload["means"]),
        stds=tuple(float(value) for value in payload["stds"]),
    )


def _config_from_payload(payload: dict[str, Any]) -> TorchDQNConfig:
    if isinstance(payload.get("hidden_layers"), list):
        payload = {**payload, "hidden_layers": tuple(payload["hidden_layers"])}
    return TorchDQNConfig(**payload)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
