"""Aprendizado de categorias a partir das correções do usuário.

Cada palavra significativa da descrição vira uma regra palavra → categoria.
Na hora de sugerir, somam-se os "acertos" das palavras encontradas no texto.
Simples, explicável e funciona sem IA e sem internet.
"""

import re
import unicodedata
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CategorizationRule, Category

STOPWORDS = {
    "de",
    "da",
    "do",
    "das",
    "dos",
    "no",
    "na",
    "nos",
    "nas",
    "em",
    "um",
    "uma",
    "com",
    "por",
    "para",
    "pra",
    "pro",
    "reais",
    "real",
    "gastei",
    "paguei",
    "comprei",
    "recebi",
    "hoje",
    "ontem",
    "que",
    "meu",
    "minha",
    "seu",
    "sua",
    "foi",
    "dia",
    "mes",
    "the",
    "valor",
    "conta",
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text)).strip()


def keywords(text: str) -> list[str]:
    return [w for w in normalize(text).split() if len(w) >= 3 and not w.isdigit() and w not in STOPWORDS][:8]


def learn(db: Session, user_id: str, description: str, category_id: str) -> None:
    for word in set(keywords(description)):
        rule = db.scalar(
            select(CategorizationRule).where(
                CategorizationRule.user_id == user_id, CategorizationRule.keyword == word
            )
        )
        if rule is None:
            db.add(CategorizationRule(user_id=user_id, keyword=word, category_id=category_id, hits=1))
        elif rule.category_id == category_id:
            rule.hits += 1
        else:
            # Correção mais recente prevalece, mas com peso baixo até se confirmar
            rule.category_id = category_id
            rule.hits = 1


def suggest_from_rules(db: Session, user_id: str, text: str) -> str | None:
    words = keywords(text)
    if not words:
        return None
    rows = db.execute(
        select(CategorizationRule.category_id, CategorizationRule.hits)
        .join(Category, Category.id == CategorizationRule.category_id)
        .where(
            CategorizationRule.user_id == user_id,
            CategorizationRule.keyword.in_(words),
            Category.deleted_at.is_(None),
        )
    ).all()
    scores: dict[str, int] = defaultdict(int)
    for category_id, hits in rows:
        scores[category_id] += hits
    return max(scores, key=scores.get) if scores else None
