from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fintech_quant.information.archive import archive_financial_report_documents
from fintech_quant.information.repository import InformationRepository


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive financial-report source documents from information JSONL.")
    parser.add_argument("--input", default="data/raw/information/information.jsonl")
    parser.add_argument("--output", default=None)
    parser.add_argument("--document-root", default="data/raw/information/financial_reports")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path
    repository = InformationRepository(input_path)
    records, archived_count = archive_financial_report_documents(
        repository.all_records(),
        Path(args.document_root),
    )
    InformationRepository(output_path).replace_all(records)
    print(f"archived_financial_reports={archived_count}")
    print(f"written_records={len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
