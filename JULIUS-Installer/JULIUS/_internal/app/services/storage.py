"""Armazenamento dos arquivos de documentos.

- "db"   (padrão): bytes no próprio banco. Funciona em hospedagem gratuita sem disco
          persistente e entra automaticamente nos backups do banco.
- "local": arquivos em STORAGE_DIR/<usuário>/<aa>/<uuid>.bin (instalação no PC).

Para nuvem (ex.: Cloudflare R2 / S3, que têm camada gratuita), basta uma classe
com os mesmos três métodos registrada em BACKENDS — o resto do sistema não muda.
"""

import uuid
from pathlib import Path
from typing import Protocol

from app.config import BACKEND_DIR, get_settings
from app.models import Attachment


class StorageBackend(Protocol):
    name: str

    def save(self, att: Attachment, data: bytes) -> None: ...
    def load(self, att: Attachment) -> bytes: ...
    def delete(self, att: Attachment) -> None: ...


class DatabaseStorage:
    name = "db"

    def save(self, att: Attachment, data: bytes) -> None:
        att.data = data
        att.storage_key = None

    def load(self, att: Attachment) -> bytes:
        return att.data or b""

    def delete(self, att: Attachment) -> None:
        att.data = None


class LocalStorage:
    name = "local"

    def __init__(self, root: Path):
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:  # nunca sair da pasta de arquivos
            raise ValueError("Chave de armazenamento inválida")
        return path

    def save(self, att: Attachment, data: bytes) -> None:
        key = f"{att.user_id}/{att.sha256[:2]}/{uuid.uuid4().hex}.bin"
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        att.storage_key = key
        att.data = None

    def load(self, att: Attachment) -> bytes:
        return self._path(att.storage_key).read_bytes() if att.storage_key else b""

    def delete(self, att: Attachment) -> None:
        if att.storage_key:
            self._path(att.storage_key).unlink(missing_ok=True)
            att.storage_key = None


def _local_root() -> Path:
    configured = get_settings().storage_dir
    return Path(configured) if configured else BACKEND_DIR / "data" / "files"


def get_backend(name: str | None = None) -> StorageBackend:
    name = name or get_settings().storage_backend
    if name == "local":
        return LocalStorage(_local_root())
    return DatabaseStorage()


def save(att: Attachment, data: bytes) -> None:
    backend = get_backend()
    att.storage_backend = backend.name
    backend.save(att, data)


def load(att: Attachment) -> bytes:
    return get_backend(att.storage_backend).load(att)


def delete(att: Attachment) -> None:
    get_backend(att.storage_backend).delete(att)
