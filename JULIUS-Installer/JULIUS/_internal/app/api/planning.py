"""Orçamentos mensais por categoria e metas financeiras."""

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.errors import BadRequest
from app.models import Account, Budget, Category, Goal
from app.models.base import utcnow
from app.schemas import BudgetIn, GoalIn, GoalUpdate
from app.services import analytics, audit
from app.services.dates import local_today
from app.services.ownership import get_owned
from app.services.transactions import brl

router = APIRouter(prefix="/api", tags=["planejamento"])


@router.get("/budgets")
def list_budgets(user: CurrentUser, db: DB):
    return analytics.budgets_status(db, user.id, local_today())


@router.put("/budgets", status_code=200)
def upsert_budget(body: BudgetIn, user: CurrentUser, db: DB):
    """Define (ou altera) o limite mensal de uma categoria de despesa."""
    cat = get_owned(db, Category, body.category_id, user.id, "Categoria")
    if cat.kind != "expense":
        raise BadRequest("Orçamentos se aplicam a categorias de despesa.")
    budget = db.scalar(select(Budget).where(Budget.user_id == user.id, Budget.category_id == cat.id))
    if budget is None:
        budget = Budget(user_id=user.id, category_id=cat.id, amount_cents=body.amount_cents)
        db.add(budget)
    else:
        budget.amount_cents = body.amount_cents
    db.flush()
    audit.record(
        db,
        user.id,
        "budget",
        budget.id,
        "update",
        f"Orçamento de {cat.name} definido em {brl(body.amount_cents)}/mês.",
    )
    db.commit()
    return next(b for b in analytics.budgets_status(db, user.id, local_today()) if b["id"] == budget.id)


@router.delete("/budgets/{budget_id}", status_code=204)
def delete_budget(budget_id: str, user: CurrentUser, db: DB):
    budget = get_owned(db, Budget, budget_id, user.id, "Orçamento")
    db.delete(budget)
    audit.record(db, user.id, "budget", budget_id, "delete", "Orçamento removido.")
    db.commit()


def _goal_out(db, user_id: str, goal_id: str) -> dict:
    return next(g for g in analytics.goals_status(db, user_id, local_today()) if g["id"] == goal_id)


@router.get("/goals")
def list_goals(user: CurrentUser, db: DB):
    return analytics.goals_status(db, user.id, local_today())


@router.post("/goals", status_code=201)
def create_goal(body: GoalIn, user: CurrentUser, db: DB):
    if body.account_id:
        get_owned(db, Account, body.account_id, user.id, "Conta")
    goal = Goal(user_id=user.id, **body.model_dump())
    db.add(goal)
    db.flush()
    audit.record(
        db, user.id, "goal", goal.id, "create", f'Meta "{goal.name}" criada ({brl(goal.target_cents)}).'
    )
    db.commit()
    return _goal_out(db, user.id, goal.id)


@router.patch("/goals/{goal_id}")
def update_goal(goal_id: str, body: GoalUpdate, user: CurrentUser, db: DB):
    goal = get_owned(db, Goal, goal_id, user.id, "Meta")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("account_id"):
        get_owned(db, Account, changes["account_id"], user.id, "Conta")
    before = {k: getattr(goal, k) for k in changes}
    for k, v in changes.items():
        setattr(goal, k, v)
    audit.record(
        db, user.id, "goal", goal.id, "update", f'Meta "{goal.name}" atualizada.', audit.diff(before, changes)
    )
    db.commit()
    return _goal_out(db, user.id, goal.id)


@router.delete("/goals/{goal_id}", status_code=204)
def delete_goal(goal_id: str, user: CurrentUser, db: DB):
    goal = get_owned(db, Goal, goal_id, user.id, "Meta")
    goal.deleted_at = utcnow()
    audit.record(db, user.id, "goal", goal.id, "delete", f'Meta "{goal.name}" removida.')
    db.commit()
