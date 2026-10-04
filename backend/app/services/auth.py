import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError, Conflict
from app.models import (
    Account,
    AIAction,
    AIConversation,
    Attachment,
    AuditLog,
    Budget,
    CategorizationRule,
    Category,
    Debt,
    Goal,
    InstallmentPlan,
    Recurrence,
    SyncConflict,
    SyncState,
    Transaction,
    User,
    UserSession,
)
from app.models.base import utcnow
from app.security.passwords import hash_password, needs_rehash, verify_password
from app.services import audit, storage
from app.services.default_categories import create_default_categories

RENEW_AFTER = timedelta(days=1)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _aware(dt: datetime) -> datetime:
    # SQLite devolve datetimes sem fuso; tudo é gravado em UTC
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def register(db: Session, email: str, name: str, password: str) -> User:
    email = email.strip().lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise Conflict("Já existe uma conta com este e-mail.", code="email_taken")
    user = User(
        email=email, name=name.strip(), password_hash=hash_password(password), settings={"onboarded": False}
    )
    db.add(user)
    db.flush()
    create_default_categories(db, user.id)
    db.add(Account(user_id=user.id, name="Carteira", kind="cash", initial_balance_cents=0))
    audit.record(db, user.id, "user", user.id, "create", "Conta de usuário criada.")
    db.commit()
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.strip().lower(), User.deleted_at.is_(None)))
    if not verify_password(user.password_hash if user else None, password) or user is None:
        raise AppError(401, "invalid_credentials", "E-mail ou senha incorretos.")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = utcnow()
    return user


def create_session(db: Session, user: User, user_agent: str | None, ip: str | None) -> str:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(days=get_settings().session_days),
            user_agent=(user_agent or "")[:300] or None,
            ip=ip,
        )
    )
    # Limpeza oportunista de sessões expiradas deste usuário
    db.execute(delete(UserSession).where(UserSession.user_id == user.id, UserSession.expires_at < now))
    audit.record(db, user.id, "session", None, "login", "Login realizado.", ip=ip)
    db.commit()
    return token


def resolve_session(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    now = utcnow()
    if sess is None or _aware(sess.expires_at) <= now:
        return None
    user = db.get(User, sess.user_id)
    if user is None or user.deleted_at is not None:
        return None
    # Renovação deslizante, no máximo uma escrita por dia
    if now - _aware(sess.last_seen_at) > RENEW_AFTER:
        sess.last_seen_at = now
        sess.expires_at = now + timedelta(days=get_settings().session_days)
        db.commit()
    return user


def revoke_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(UserSession).where(UserSession.token_hash == hash_token(token)))
        db.commit()


def change_password(db: Session, user: User, current: str, new: str, keep_token: str) -> None:
    if not verify_password(user.password_hash, current):
        raise AppError(400, "wrong_password", "A senha atual está incorreta.")
    user.password_hash = hash_password(new)
    # Encerra todas as outras sessões
    db.execute(
        delete(UserSession).where(
            UserSession.user_id == user.id, UserSession.token_hash != hash_token(keep_token)
        )
    )
    audit.record(db, user.id, "user", user.id, "update", "Senha alterada.")
    db.commit()


def delete_account(db: Session, user: User, password: str) -> None:
    """Exclusão definitiva de todos os dados do usuário, em ordem segura de dependências."""
    if not verify_password(user.password_hash, password):
        raise AppError(400, "wrong_password", "Senha incorreta. Nada foi excluído.")
    uid = user.id
    for att in db.scalars(select(Attachment).where(Attachment.user_id == uid)):
        storage.delete(att)  # arquivos fora do banco (modo local)
    db.execute(update(Category).where(Category.user_id == uid).values(parent_id=None))
    for model in (
        Transaction,
        AIAction,
        AIConversation,
        Attachment,
        Debt,
        Recurrence,
        InstallmentPlan,
        Budget,
        Goal,
        CategorizationRule,
        Category,
        Account,
        SyncConflict,
        SyncState,
        AuditLog,
        UserSession,
    ):
        db.execute(delete(model).where(model.user_id == uid))
    db.execute(delete(User).where(User.id == uid))
    db.commit()
