"""S3-compatible object storage abstraction (PRD §5.2, §13).

Raw documents are stored verbatim under
``raw/{source}/{company_id}/{yyyy}/{mm}/{sha256}.{ext}`` before any parsing. The local
backend is a directory; the S3/MinIO backend arrives with live ingestion (step 10) behind
the same interface.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic_settings import BaseSettings, SettingsConfigDict


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def list(self, prefix: str) -> list[str]: ...


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if key.startswith("/") or ".." in key.split("/"):
            raise ValueError(f"invalid object key: {key!r}")
        return self.root / key

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def list(self, prefix: str) -> list[str]:
        base = self._path(prefix) if prefix else self.root
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file())


class MemoryObjectStore:
    """In-memory store for tests."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def exists(self, key: str) -> bool:
        return key in self.objects

    def list(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))


def raw_document_key(
    source: str, company_id: int | None, public_at: datetime, sha256: str, ext: str
) -> str:
    scope = str(company_id) if company_id is not None else "market"
    return f"raw/{source}/{scope}/{public_at:%Y}/{public_at:%m}/{sha256}.{ext}"


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIGNALALPHA_", extra="ignore")

    object_store_dir: Path = Path(".storage")


def get_object_store() -> ObjectStore:
    return LocalObjectStore(StorageSettings().object_store_dir)
