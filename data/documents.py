"""Raw-first document writer (PRD §5.2).

Stores bytes in object storage, registers a ``raw_documents`` row keyed by SHA-256 (identical
re-fetches deduplicate) and, for text documents, a ``document_texts`` row that evidence spans
are validated against.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from data.storage import ObjectStore, raw_document_key
from database.models import Company, DocumentText, ExtractionMethod, RawDocument, Source

PAGE_BREAK = "\f"


def page_offsets_for(text: str) -> list[int]:
    """Character offsets at which each page starts; pages are separated by form feeds."""
    offsets = [0]
    for i, ch in enumerate(text):
        if ch == PAGE_BREAK:
            offsets.append(i + 1)
    return offsets


@dataclass(frozen=True)
class StoredDocument:
    raw_document: RawDocument
    text: DocumentText
    created: bool


class DocumentWriter:
    def __init__(self, session: Session, store: ObjectStore, *, is_mock: bool) -> None:
        self.session = session
        self.store = store
        self.is_mock = is_mock

    def write_text_document(
        self,
        *,
        company: Company | None,
        source: Source,
        text: str,
        public_at: datetime,
        parser_version: str,
        title: str | None = None,
        url: str | None = None,
        extraction_method: ExtractionMethod = ExtractionMethod.TEXT,
        ext: str = "txt",
        content_type: str = "text/plain; charset=utf-8",
    ) -> StoredDocument:
        if public_at.tzinfo is None:
            raise ValueError("public_at must be timezone-aware")
        data = text.encode("utf-8")
        sha = hashlib.sha256(data).hexdigest()
        existing = self.session.scalars(
            select(RawDocument).where(RawDocument.sha256 == sha)
        ).first()
        created = existing is None
        if existing is None:
            key = raw_document_key(
                source.value, company.id if company else None, public_at, sha, ext
            )
            if not self.store.exists(key):
                self.store.put(key, data, content_type)
            existing = RawDocument(
                company_id=company.id if company else None,
                source=source,
                sha256=sha,
                storage_key=key,
                url=url,
                content_type=content_type,
                byte_size=len(data),
                title=title,
                public_at=public_at,
                is_mock=self.is_mock,
            )
            self.session.add(existing)
            self.session.flush()
        doc_text = self.session.scalars(
            select(DocumentText).where(
                DocumentText.raw_document_id == existing.id,
                DocumentText.parser_version == parser_version,
            )
        ).first()
        if doc_text is None:
            doc_text = DocumentText(
                raw_document_id=existing.id,
                parser_version=parser_version,
                extraction_method=extraction_method,
                text=text,
                char_count=len(text),
                page_offsets=page_offsets_for(text),
            )
            self.session.add(doc_text)
            self.session.flush()
        return StoredDocument(raw_document=existing, text=doc_text, created=created)
