import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

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
