from fastapi import APIRouter
from sqlalchemy import func, select, update

from app.api.deps import DB, CurrentUser
from app.errors import BadRequest, Conflict
from app.models import Category, Transaction
from app.models.base import utcnow
from app.schemas import CategoryIn, CategoryOut, CategoryUpdate
from app.services import audit
from app.services.ownership import get_owned

router = APIRouter(prefix="/api/categories", tags=["categorias"])


def _name_taken(db, user_id: str, parent_id: str | None, name: str, kind: str, exclude: str | None = None):
    q = select(Category.id).where(
        Category.user_id == user_id,
        Category.deleted_at.is_(None),
        Category.kind == kind,
        func.lower(Category.name) == name.lower(),
        Category.parent_id.is_(None) if parent_id is None else Category.parent_id == parent_id,
    )
    if exclude:
        q = q.where(Category.id != exclude)
    return db.scalar(q) is not None


@router.get("", response_model=list[CategoryOut])
def list_categories(user: CurrentUser, db: DB):
    return db.scalars(
        select(Category)
        .where(Category.user_id == user.id, Category.deleted_at.is_(None))
        .order_by(Category.kind, Category.name)
    ).all()


@router.post("", response_model=CategoryOut, status_code=201)
def create_category(body: CategoryIn, user: CurrentUser, db: DB):
    if body.parent_id:
        parent = get_owned(db, Category, body.parent_id, user.id, "Categoria principal")
        if parent.parent_id is not None:
            raise BadRequest("Subcategorias não podem ter subcategorias.")
        if parent.kind != body.kind:
            raise BadRequest("A subcategoria precisa ser do mesmo tipo da categoria principal.")
    if _name_taken(db, user.id, body.parent_id, body.name, body.kind):
        raise Conflict("Já existe uma categoria com este nome.")
    cat = Category(user_id=user.id, **body.model_dump())
    db.add(cat)
    db.flush()
    audit.record(db, user.id, "category", cat.id, "create", f'Categoria "{cat.name}" criada.')
    db.commit()
    return cat


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(category_id: str, body: CategoryUpdate, user: CurrentUser, db: DB):
    cat = get_owned(db, Category, category_id, user.id, "Categoria")
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and _name_taken(db, user.id, cat.parent_id, changes["name"], cat.kind, cat.id):
        raise Conflict("Já existe uma categoria com este nome.")
    before = {k: getattr(cat, k) for k in changes}
    for k, v in changes.items():
        setattr(cat, k, v)
    audit.record(
        db,
        user.id,
        "category",
        cat.id,
        "update",
        f'Categoria "{cat.name}" editada.',
        audit.diff(before, changes),
    )
    db.commit()
    return cat


@router.delete("/{category_id}", status_code=204)
def delete_category(category_id: str, user: CurrentUser, db: DB):
    """Arquiva a categoria (e subcategorias). Os lançamentos ficam sem categoria, sem perda."""
    cat = get_owned(db, Category, category_id, user.id, "Categoria")
    ids = [cat.id, *db.scalars(select(Category.id).where(Category.parent_id == cat.id))]
    now = utcnow()
    db.execute(update(Category).where(Category.id.in_(ids)).values(deleted_at=now))
    moved = db.execute(
        update(Transaction)
        .where(Transaction.category_id.in_(ids))
        .values(category_id=None, version=Transaction.version + 1)
    ).rowcount
    audit.record(
        db,
        user.id,
        "category",
        cat.id,
        "delete",
        f'Categoria "{cat.name}" excluída; {moved} lançamento(s) ficaram sem categoria.',
    )
    db.commit()
