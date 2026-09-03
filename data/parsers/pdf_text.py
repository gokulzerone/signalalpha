"""Text-layer PDF extraction (PRD §5.2). Scanned PDFs (no text layer) are reported, not OCR'd
in v1: the caller records a parse failure so the data-quality page shows the gap."""

from __future__ import annotations

import io

from pypdf import PdfReader

PARSER_VERSION = "pdf-text-1"
PAGE_BREAK = "\f"


class NoTextLayerError(ValueError):
    pass


def extract_pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    text = PAGE_BREAK.join(pages)
    if len(text.strip()) < 20:
        raise NoTextLayerError("PDF has no usable text layer; OCR is not enabled in v1")
    return text
