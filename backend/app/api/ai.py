from fastapi import APIRouter
from sqlalchemy import select

from app.ai import assistant, quick_input
from app.ai.providers import get_provider
from app.api.deps import DB, CurrentUser
from app.errors import AppError
from app.models import AIConversation, AIMessage
from app.models.base import utcnow
from app.schemas import AskIn, QuickInputIn
from app.security.ratelimit import ai_limiter
from app.services.dates import local_today
from app.services.ownership import get_owned

router = APIRouter(prefix="/api", tags=["ia"])


def _limit(user_id: str) -> None:
    if not ai_limiter.hit(user_id):
        raise AppError(429, "rate_limited", "Muitas mensagens em pouco tempo. Aguarde um minuto.")


@router.get("/ai/status")
def ai_status(user: CurrentUser):
    provider = get_provider()
    return {"enabled": provider is not None, "provider": provider.name if provider else None}


@router.post("/quick-input/parse")
def parse_quick_input(body: QuickInputIn, user: CurrentUser, db: DB):
    _limit(user.id)
    return quick_input.parse(db, user, body.text, local_today())


@router.post("/assistant/ask")
def ask(body: AskIn, user: CurrentUser, db: DB):
    _limit(user.id)
    if body.conversation_id:
        conv = get_owned(db, AIConversation, body.conversation_id, user.id, "Conversa")
    else:
        conv = AIConversation(user_id=user.id, title=body.question[:120])
        db.add(conv)
        db.flush()
    result = assistant.answer(db, user, body.question, local_today())
    db.add(AIMessage(conversation_id=conv.id, role="user", content=body.question))
    db.add(
        AIMessage(
            conversation_id=conv.id,
            role="assistant",
            content=result["answer"],
            data={
                "intent": result["intent"],
                "engine": result["engine"],
                "is_estimate": result["is_estimate"],
            },
        )
    )
    conv.updated_at = utcnow()
    db.commit()
    return {**result, "conversation_id": conv.id}


@router.get("/assistant/conversations")
def conversations(user: CurrentUser, db: DB):
    return [
        {"id": c.id, "title": c.title, "updated_at": c.updated_at}
        for c in db.scalars(
            select(AIConversation)
            .where(AIConversation.user_id == user.id)
            .order_by(AIConversation.updated_at.desc())
            .limit(30)
        )
    ]


@router.get("/assistant/conversations/{conv_id}")
def conversation(conv_id: str, user: CurrentUser, db: DB):
    conv = get_owned(db, AIConversation, conv_id, user.id, "Conversa")
    msgs = db.scalars(
        select(AIMessage).where(AIMessage.conversation_id == conv.id).order_by(AIMessage.created_at)
    ).all()
    return {
        "id": conv.id,
        "title": conv.title,
        "messages": [
            {"role": m.role, "content": m.content, "data": m.data, "created_at": m.created_at} for m in msgs
        ],
    }


@router.delete("/assistant/conversations/{conv_id}", status_code=204)
def delete_conversation(conv_id: str, user: CurrentUser, db: DB):
    conv = get_owned(db, AIConversation, conv_id, user.id, "Conversa")
    db.delete(conv)
    db.commit()
