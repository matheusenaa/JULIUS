from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin, utcnow


class AuditLog(IdMixin, Base):
    """Histórico de alterações importantes (criação, edição, exclusão)."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_user_created", "user_id", "created_at"),
        Index("ix_audit_entity", "entity", "entity_id"),
    )

    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(20))
    summary: Mapped[str] = mapped_column(String(300))
    changes: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Attachment(IdMixin, Base):
    """Comprovante, nota fiscal ou documento. Guardado no próprio banco: entra nos
    backups e não depende de disco persistente (planos gratuitos não têm)."""

    __tablename__ = "attachments"
    __table_args__ = (CheckConstraint("size_bytes > 0", name="size_positive"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    transaction_id: Mapped[str | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), index=True
    )
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(60))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    # Resultado bruto da extração (OCR/IA), para auditoria e reprocessamento
    extracted: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AIConversation(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_conversations"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))


class AIMessage(IdMixin, Base):
    __tablename__ = "ai_messages"

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    # Dados estruturados usados na resposta (números calculados pelo backend)
    data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
