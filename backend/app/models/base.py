import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, Integer, MetaData, String, event, inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

# Nomes determinísticos de constraints: essenciais para migrations em SQLite e Postgres
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def str_enum(values: tuple[str, ...], name: str) -> Enum:
    """Enum portátil: VARCHAR + CHECK (sem tipo ENUM nativo do Postgres)."""
    return Enum(*values, name=name, native_enum=False, create_constraint=True, length=20)


class IdMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class SyncMixin:
    """Controle de versão para edição concorrente e sincronização entre dispositivos.

    - `version` sobe 1 a cada alteração real (automaticamente, ver `_bump_versions`).
    - `synced_version` é a última versão confirmada pelo servidor remoto (só usado
      por instalações locais que sincronizam com o servidor online). Registro "sujo"
      = version != synced_version.
    """

    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    synced_version: Mapped[int | None] = mapped_column(Integer)


_NOT_A_CHANGE = {"version", "synced_version", "updated_at"}


@event.listens_for(Session, "before_flush")
def _bump_versions(session: Session, _ctx, _instances) -> None:
    for obj in list(session.new) + list(session.dirty):
        if not isinstance(obj, SyncMixin):
            continue
        # Dados recebidos do servidor remoto já chegam com a versão dele. A marca vale
        # só para ESTA gravação: se ficasse no objeto, uma edição local posterior não
        # subiria a versão e seria sobrescrita em silêncio na próxima sincronização.
        if obj.__dict__.pop("_sync_apply", False) or obj in session.new:
            continue
        state = inspect(obj)
        if any(a.history.has_changes() for a in state.attrs if a.key not in _NOT_A_CHANGE):
            obj.version = (obj.version or 0) + 1
