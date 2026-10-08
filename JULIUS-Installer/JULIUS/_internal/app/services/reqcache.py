"""Cache por requisição (por sessão do banco) para cálculos repetidos na mesma tela.

Ex.: a Visão geral precisa do saldo, das faturas e da linha do tempo em vários
blocos; sem isso, o mesmo cálculo rodava várias vezes. Qualquer gravação na sessão
apaga o cache, então nunca há número desatualizado.
"""

from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import event
from sqlalchemy.orm import Session

T = TypeVar("T")
_KEY = "julius_cache"


def cached(db: Session, key: tuple, compute: Callable[[], T]) -> T:
    store = db.info.setdefault(_KEY, {})
    if key not in store:
        store[key] = compute()
    return store[key]


@event.listens_for(Session, "after_flush")
def _invalidate_on_write(session: Session, _ctx) -> None:
    session.info.pop(_KEY, None)


@event.listens_for(Session, "after_commit")
def _invalidate_on_commit(session: Session) -> None:
    session.info.pop(_KEY, None)


@event.listens_for(Session, "after_rollback")
def _invalidate_on_rollback(session: Session) -> None:
    session.info.pop(_KEY, None)
