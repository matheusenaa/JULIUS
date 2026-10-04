"""Agente de IA do JULIUS (modo com ferramentas).

USUÁRIO → API → agente → [ferramentas controladas] → dados reais → agente → resposta.

- O agente só enxerga o que as ferramentas devolvem (filtrado pelo usuário logado).
- Números vêm prontos das ferramentas; o agente é instruído a não fazer contas.
- Escritas viram ações pendentes de confirmação (ver tools.py).
- Sem provedor, ou se ele falhar, o assistente por regras responde (nunca fica sem resposta).
- "Integrar o agente do Gemini": cole as instruções do seu agente (Gem) em Ajustes → IA
  ou aponte AI_AGENT_INSTRUCTIONS_FILE para um arquivo. Elas entram como instruções do sistema.
"""

import json
import logging
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import tools
from app.ai.providers import AIUnavailable, get_provider_for
from app.config import get_settings
from app.models import AIMessage, Category, Transaction, User
from app.services import analytics

log = logging.getLogger("julius.agent")
MAX_STEPS = 6
HISTORY = 8

BASE_INSTRUCTIONS = """Você é o JULIUS, assistente financeiro pessoal. Fale português do Brasil, de forma
simples, direta e cordial (até 8 frases). Regras invioláveis:
1. Use as ferramentas para obter dados. Nunca invente valores, datas ou lançamentos.
2. NÃO faça contas: os totais, saldos e projeções já vêm calculados das ferramentas. Repita-os.
3. Projeções são estimativas — diga isso. Sugestões são sugestões, não certezas.
4. Para criar, alterar ou excluir algo, use a ferramenta correspondente: ela só PROPÕE a ação.
   Depois diga ao usuário que ele precisa confirmar no botão. Nunca diga que já foi feito.
5. Se faltar dado, diga claramente o que falta.
Hoje é {today}. Moeda: {currency}."""


def _custom_instructions(user: User) -> str:
    parts = []
    path = get_settings().ai_agent_instructions_file
    if path:
        try:
            parts.append(Path(path).read_text(encoding="utf-8")[:6000])
        except OSError:
            log.warning("Arquivo de instruções do agente não encontrado")
    custom = (user.settings or {}).get("ai_custom_instructions")
    if custom:
        parts.append(custom[:4000])
    return "\n\n".join(parts)


def _memory(db: Session, user: User, today: date) -> str:
    """Contexto mínimo: preferências e hábitos, sem valores de lançamentos."""
    cats = db.scalars(
        select(Category).where(Category.user_id == user.id, Category.deleted_at.is_(None))
    ).all()
    used = db.scalars(
        select(Transaction.category_id)
        .where(
            Transaction.user_id == user.id,
            Transaction.deleted_at.is_(None),
            Transaction.category_id.is_not(None),
        )
        .order_by(Transaction.occurred_on.desc())
        .limit(200)
    ).all()
    names = {c.id: c.name for c in cats}
    top = [names[c] for c in dict.fromkeys(used) if c in names][:8]
    goals = [g["name"] for g in analytics.goals_status(db, user.id, today)]
    lines = [f"Nome do usuário: {user.name.split(' ')[0]}"]
    if top:
        lines.append("Categorias que mais usa: " + ", ".join(top))
    if goals:
        lines.append("Metas: " + ", ".join(goals))
    return "\n".join(lines)


def _history(db: Session, conversation_id: str | None) -> list[dict]:
    if not conversation_id:
        return []
    msgs = db.scalars(
        select(AIMessage)
        .where(AIMessage.conversation_id == conversation_id)
        .order_by(AIMessage.created_at.desc())
        .limit(HISTORY)
    ).all()
    return [{"role": m.role, "content": m.content} for m in reversed(msgs)]


def run(db: Session, user: User, question: str, conversation_id: str | None, today: date) -> dict | None:
    """Responde com o agente. Retorna None quando não há IA disponível (cai nas regras)."""
    provider = get_provider_for(user)
    if provider is None or not hasattr(provider, "chat"):
        return None
    currency = (user.settings or {}).get("currency", "BRL")
    system = BASE_INSTRUCTIONS.format(today=today.isoformat(), currency=currency)
    system += "\n\nContexto do usuário:\n" + _memory(db, user, today)
    custom = _custom_instructions(user)
    if custom:
        system += "\n\nInstruções adicionais (não sobrepõem as regras invioláveis):\n" + custom
    messages = [
        {"role": "system", "content": system},
        *_history(db, conversation_id),
        {"role": "user", "content": question},
    ]
    used: list[str] = []
    actions: list[str] = []
    try:
        for _ in range(MAX_STEPS):
            reply = provider.chat(messages, tools.SPECS)
            if not reply.tool_calls:
                text = (reply.text or "").strip()
                if not text:
                    return None
                return {
                    "answer": text,
                    "intent": "agent",
                    "engine": "ai",
                    "is_estimate": "estimativa" in text.lower(),
                    "data": {"tools": used},
                    "action_ids": actions,
                }
            messages.append(reply.raw_message)
            for call in reply.tool_calls:
                used.append(call["name"])
                result = tools.run_tool(db, user, conversation_id, call["name"], call["arguments"], today)
                if result.get("action_id"):
                    actions.append(result["action_id"])
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )
    except AIUnavailable:
        return None
    return {
        "answer": "Não consegui concluir a análise agora. Tente reformular a pergunta.",
        "intent": "agent",
        "engine": "ai",
        "is_estimate": False,
        "data": {"tools": used},
        "action_ids": actions,
    }
