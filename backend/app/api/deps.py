from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError
from app.models import User
from app.services.auth import resolve_session
from app.services.money import current_currency

SESSION_COOKIE = "julius_session"
CSRF_COOKIE = "julius_csrf"
CSRF_HEADER = "x-csrf-token"

DB = Annotated[Session, Depends(get_db)]


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def current_user(request: Request, db: DB) -> User:
    # async de propósito: o contextvar da moeda definido aqui é herdado pelo endpoint
    # (endpoints síncronos rodam numa cópia deste contexto). A consulta é uma busca por índice.
    user = resolve_session(db, request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise AppError(401, "unauthenticated", "Sua sessão expirou. Entre novamente.")
    current_currency.set((user.settings or {}).get("currency", "BRL"))
    return user


CurrentUser = Annotated[User, Depends(current_user)]
