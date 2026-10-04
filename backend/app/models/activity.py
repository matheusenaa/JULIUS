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

from app.models.base import Base, IdMixin, TimestampMixin, str_enum, utcnow


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


DOC_KINDS = ("receipt", "bill", "invoice", "pix", "statement", "contract", "other")
DOC_STATUSES = ("uploaded", "review", "confirmed", "discarded")


class Attachment(IdMixin, Base):
    """Documento financeiro (conta, boleto, comprovante, nota...).

    Os bytes ficam no armazenamento configurado (`storage_backend`): no próprio
    banco (padrão: entra nos backups e funciona em hospedagem sem disco) ou em
    disco local. `storage_key` localiza o arquivo fora do banco.
    """

    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="size_positive"),
        Index("ix_attachments_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    transaction_id: Mapped[str | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), index=True
    )
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(60))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_backend: Mapped[str] = mapped_column(String(10), default="db", server_default="db")
    storage_key: Mapped[str | None] = mapped_column(String(200))
    data: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    title: Mapped[str | None] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(
        str_enum(DOC_KINDS, "doc_kind"), default="other", server_default="other"
    )
    status: Mapped[str] = mapped_column(
        str_enum(DOC_STATUSES, "doc_status"), default="uploaded", server_default="uploaded"
    )
    # Resultado bruto da extração (OCR/IA/PDF), para auditoria e reprocessamento
    extracted: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIAction(IdMixin, Base):
    """Ação de escrita sugerida pela IA. Só é executada depois que o usuário confirma."""

    __tablename__ = "ai_actions"
    __table_args__ = (Index("ix_ai_actions_user_status", "user_id", "status"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("ai_conversations.id", ondelete="CASCADE"))
    tool: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    summary: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(
        str_enum(("pending", "confirmed", "rejected", "expired", "failed"), "ai_action_status"),
        default="pending",
    )
    result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SyncState(IdMixin, TimestampMixin, Base):
    """Vínculo de uma instalação local com o servidor online (uma linha por usuário)."""

    __tablename__ = "sync_state"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    remote_url: Mapped[str] = mapped_column(String(300))
    remote_email: Mapped[str] = mapped_column(String(254))
    # Token de sessão no servidor remoto (a senha nunca é guardada)
    remote_token: Mapped[str | None] = mapped_column(String(200))
    last_pull_cursor: Mapped[str | None] = mapped_column(String(40))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(300))


class SyncConflict(IdMixin, Base):
    """Mesmo registro alterado aqui e no servidor: o usuário decide qual versão fica."""

    __tablename__ = "sync_conflicts"
    __table_args__ = (Index("ix_sync_conflicts_user_open", "user_id", "resolved_at"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(36))
    local_data: Mapped[dict] = mapped_column(JSON)
    remote_data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(String(10))


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
