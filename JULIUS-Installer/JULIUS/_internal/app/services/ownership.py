from typing import TypeVar

from sqlalchemy.orm import Session

from app.errors import NotFound

T = TypeVar("T")


def get_owned(db: Session, model: type[T], obj_id: str | None, user_id: str, what: str) -> T:
    """Busca um registro garantindo que pertence ao usuário e não foi excluído.

    Registro de outro usuário responde "não encontrado" (não revela que existe).
    """
    obj = db.get(model, obj_id) if obj_id else None
    if (
        obj is None
        or getattr(obj, "user_id", None) != user_id
        or getattr(obj, "deleted_at", None) is not None
    ):
        raise NotFound(what)
    return obj
