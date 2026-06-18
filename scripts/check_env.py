from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


PROJECT_FILES = (
    "data/processed/akshare_research_features.csv",
    "outputs/strategy_comparison_report.json",
    "outputs/baseline_backtest.json",
    "outputs/data_quality_report.json",
)

PACKAGES = (
    "akshare",
    "numpy",
    "pandas",
    "plotly",
    "streamlit",
    "torch",
)


def collect_environment_status(project_root: Path | None = None) -> dict[str, object]:
    root = project_root or Path.cwd()
    return {
        "python": sys.version.split()[0],
        "packages": {name: _package_status(name) for name in PACKAGES},
        "project_files": {path: (root / path).exists() for path in PROJECT_FILES},
    }


def main() -> int:
    status = collect_environment_status()
    print(f"Python: {status['python']}")

    print("Packages:")
    for name, available in status["packages"].items():
        marker = "ok" if available else "missing"
        print(f"  {name}: {marker}")

    print("Project files:")
    missing_files = []
    for path, exists in status["project_files"].items():
        marker = "ok" if exists else "missing"
        print(f"  {path}: {marker}")
        if not exists:
            missing_files.append(path)

    missing_packages = [name for name, available in status["packages"].items() if not available]
    if missing_packages:
        print("Install missing optional packages with: python -m pip install -e '.[data,research,dashboard,rl]'")

    return 1 if missing_files else 0


def _package_status(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


if __name__ == "__main__":
    raise SystemExit(main())
