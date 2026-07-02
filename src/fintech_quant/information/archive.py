from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import replace
from io import BytesIO
from pathlib import Path

from fintech_quant.information.models import InformationCategory, InformationRecord


FetchDocument = Callable[[str], tuple[bytes, str]]


def archive_financial_report_documents(
    records: list[InformationRecord],
    document_root: Path,
    *,
    fetch_document: FetchDocument | None = None,
) -> tuple[list[InformationRecord], int]:
    fetcher = fetch_document or _fetch_document
    archived: list[InformationRecord] = []
    archived_count = 0
    for record in records:
        if record.category is not InformationCategory.FINANCIAL_REPORT or not record.url:
            archived.append(record)
            continue
        payload, content_type = fetcher(record.url)
        metadata = _archive_record_document(record, payload, content_type, document_root)
        archived.append(replace(record, metadata={**record.metadata, **metadata}))
        archived_count += 1
    return archived, archived_count


def _fetch_document(url: str) -> tuple[bytes, str]:
    with urllib.request.urlopen(url, timeout=30) as response:
        content_type = response.headers.get_content_type()
        return response.read(), content_type


def _archive_record_document(
    record: InformationRecord,
    payload: bytes,
    content_type: str,
    document_root: Path,
) -> dict[str, object]:
    record_dir = document_root / (record.normalized_symbol or "sector") / str(record.published_at.year)
    record_dir.mkdir(parents=True, exist_ok=True)
    base_name = f"{record.published_at.isoformat()}_{record.record_id[:12]}"
    raw_path = record_dir / f"{base_name}{_document_suffix(record.url, content_type)}"
    raw_path.write_bytes(payload)

    extracted_text = _extract_text(payload, content_type, record.url)
    metadata: dict[str, object] = {
        "archive_status": "archived",
        "raw_document_path": str(raw_path),
        "content_type": content_type,
        "byte_size": len(payload),
    }
    if extracted_text:
        text_path = record_dir / f"{base_name}.txt"
        text_path.write_text(extracted_text, encoding="utf-8")
        metadata["raw_text_path"] = str(text_path)
        metadata["text_chars"] = len(extracted_text)
    return metadata


def _document_suffix(url: str, content_type: str) -> str:
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if suffix:
        return suffix
    if "pdf" in content_type:
        return ".pdf"
    if "html" in content_type:
        return ".html"
    if "text" in content_type:
        return ".txt"
    return ".bin"


def _extract_text(payload: bytes, content_type: str, url: str) -> str:
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if "html" in content_type or suffix in {".html", ".htm"}:
        return _extract_html_text(_decode_text(payload))
    if content_type.startswith("text/") or suffix == ".txt":
        return _decode_text(payload).strip()
    if "pdf" in content_type or suffix == ".pdf":
        return _extract_pdf_text(payload)
    return ""


def _decode_text(payload: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="ignore")


def _extract_html_text(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _extract_pdf_text(payload: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""

    reader = PdfReader(BytesIO(payload))
    page_text = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(part.strip() for part in page_text if part.strip())
