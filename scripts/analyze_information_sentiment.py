from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.information.repository import InformationRepository
from fintech_quant.information.sentiment import analyze_information_records


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze information-record text sentiment with a fixed dictionary.")
    parser.add_argument("--input", default="data/raw/information/information.jsonl")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path
    records, negative_count = analyze_information_records(InformationRepository(input_path).all_records())
    InformationRepository(output_path).replace_all(records)
    print(f"analyzed_records={len(records)}")
    print(f"negative_text_records={negative_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
