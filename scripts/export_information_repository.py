from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.information import InformationRepository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the information repository into retention-class files.")
    parser.add_argument("--input", default="data/raw/information/information.jsonl")
    parser.add_argument("--output-dir", default="data/raw/information/classified")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    manifest = InformationRepository(Path(args.input)).export_by_retention_class(output_dir)
    print(f"manifest_path={output_dir / 'manifest.json'}")
    print(f"record_count={manifest['record_count']}")
    for class_name, class_summary in sorted(manifest["classes"].items()):
        print(f"{class_name}_count={class_summary['record_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
