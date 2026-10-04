from fastapi import APIRouter
from pydantic import ValidationError
from sqlalchemy import delete, select

from app.ai import agent, assistant, quick_input, tools
from app.ai.providers import get_provider
from app.api.deps import DB, CurrentUser
from app.errors import AppError
from app.models import AIAction, AIConversation, AIMessage, CategorizationRule
from app.models.base import utcnow
from app.schemas import AskIn, QuickInputIn
from app.security.ratelimit import ai_limiter
from app.services import audit
from app.services.dates import local_today
from app.services.ownership import get_owned

router = APIRouter(prefix="/api", tags=["ia"])


def _limit(user_id: str) -> None:
    if not ai_limiter.hit(user_id):
        raise AppError(429, "rate_limited", "Muitas mensagens em pouco tempo. Aguarde um minuto.")


@router.get("/ai/status")
def ai_status(user: CurrentUser):
    provider = get_provider()
    user_enabled = (user.settings or {}).get("ai_enabled") is not False
    return {
        "enabled": provider is not None and user_enabled,
        "configured": provider is not None,
        "user_enabled": user_enabled,
        "provider": provider.name if provider else None,
        "agent": provider is not None and hasattr(provider, "chat"),
    }


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
    today = local_today()
    tools.expire_old(db, user.id)
    # Perguntas que as regras entendem são respondidas na hora, sem custo de IA e com números exatos.
    # O agente entra nas perguntas abertas ("por que…", "me ajude a…", pedidos livres).
    result = None
    if assistant.detect_intent(body.question) in ("unknown", "advice"):
        result = agent.run(db, user, body.question, conv.id, today)
    if result is None:
        result = assistant.answer(db, user, body.question, today, conv.id)
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
                "action_ids": result.get("action_ids", []),
            },
        )
    )
    conv.updated_at = utcnow()
    db.commit()
    actions = [_action_out(a) for a in _actions(db, user.id, result.get("action_ids", []))]
    return {**result, "conversation_id": conv.id, "actions": actions}


def _actions(db, user_id: str, ids: list[str]) -> list[AIAction]:
    if not ids:
        return []
    return list(db.scalars(select(AIAction).where(AIAction.user_id == user_id, AIAction.id.in_(ids))))


def _action_out(a: AIAction) -> dict:
    return {
        "id": a.id,
        "tool": a.tool,
        "summary": a.summary,
        "status": a.status,
        "result": a.result,
        "created_at": a.created_at,
    }


@router.get("/assistant/actions")
def list_actions(user: CurrentUser, db: DB, status: str = "pending"):
    tools.expire_old(db, user.id)
    db.commit()
    rows = db.scalars(
        select(AIAction)
        .where(AIAction.user_id == user.id, AIAction.status == status)
        .order_by(AIAction.created_at.desc())
        .limit(50)
    )
    return [_action_out(a) for a in rows]


@router.post("/assistant/actions/{action_id}/confirm")
def confirm_action(action_id: str, user: CurrentUser, db: DB):
    """O usuário confirmou: só agora a ação sugerida pela IA é executada."""
    action = get_owned(db, AIAction, action_id, user.id, "Ação")
    tools.expire_old(db, user.id)
    if action.status != "pending":
        raise AppError(
            409, "action_closed", "Esta ação já foi decidida ou expirou. Peça novamente ao assistente."
        )
    try:
        result = tools.execute_action(db, user, action)
    except (AppError, ValidationError, tools.ToolError) as exc:
        db.rollback()
        message = exc.message if isinstance(exc, AppError) else "Os dados desta ação não são mais válidos."
        action = get_owned(db, AIAction, action_id, user.id, "Ação")
        action.status, action.result, action.decided_at = "failed", {"error": message}, utcnow()
        db.commit()
        raise AppError(400, "action_failed", message) from exc
    action = get_owned(db, AIAction, action_id, user.id, "Ação")
    action.status, action.result, action.decided_at = "confirmed", result, utcnow()
    audit.record(
        db,
        user.id,
        "ai_action",
        action.id,
        "confirm",
        f"Ação do assistente confirmada: {action.summary}"[:300],
    )
    db.commit()
    return _action_out(action)


@router.post("/assistant/actions/{action_id}/reject")
def reject_action(action_id: str, user: CurrentUser, db: DB):
    action = get_owned(db, AIAction, action_id, user.id, "Ação")
    if action.status == "pending":
        action.status, action.decided_at = "rejected", utcnow()
        db.commit()
    return _action_out(action)


@router.delete("/assistant/history", status_code=204)
def clear_history(user: CurrentUser, db: DB):
    """Apaga todas as conversas e ações sugeridas (memória de conversa do agente)."""
    db.execute(delete(AIAction).where(AIAction.user_id == user.id))
    db.execute(delete(AIConversation).where(AIConversation.user_id == user.id))
    audit.record(db, user.id, "privacy", None, "delete", "Histórico de conversas com o assistente apagado.")
    db.commit()


@router.delete("/assistant/learning", status_code=204)
def clear_learning(user: CurrentUser, db: DB):
    """Apaga o que o JULIUS aprendeu com suas correções de categoria."""
    db.execute(delete(CategorizationRule).where(CategorizationRule.user_id == user.id))
    audit.record(db, user.id, "privacy", None, "delete", "Aprendizado de categorias apagado.")
    db.commit()


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
