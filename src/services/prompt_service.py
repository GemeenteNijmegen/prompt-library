from datetime import datetime, timezone

from sqlalchemy import or_, func, select
from sqlalchemy.orm import Session, selectinload

from src.models.prompt import Prompt
from src.models.user import User
from src.models.category import PromptCategory
from src.models.rating import PromptRating
from src.models.joins import prompts_categories, prompts_tags
from src.schemas.prompt import PromptCreate, PromptUpdate
from src.services.taxonomy_service import get_or_create_tags
from src.utils.error import NotFoundError, ConflictError, ForbiddenError


_VALID_TRANSITIONS = {
    "draft": {"published"},
    "published": {"archived"},
    "archived": {"draft"},
}

_SORT_COLUMNS = {
    "created_at": Prompt.created_at,
    "published_at": Prompt.published_at,
    "view_count": Prompt.view_count,
    "use_count": Prompt.use_count,
    "title": Prompt.title,
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _base_query(db: Session):
    return (
        db.query(Prompt)
        .options(selectinload(Prompt.categories), selectinload(Prompt.tags))
        .filter(Prompt.deleted_at.is_(None))
    )


def _ensure_user(db: Session, stub_user) -> User:
    user = db.query(User).filter(User.external_id == stub_user.external_id).first()
    if not user:
        user = User(
            external_id=stub_user.external_id,
            name=stub_user.name,
            email=stub_user.email,
        )
        db.add(user)
        db.flush()
    return user


def list_prompts(
    db: Session,
    caller=None,
    page: int = 1,
    per_page: int = 20,
    search: str | None = None,
    status: str | None = None,
    visibility: str | None = None,
    featured: bool | None = None,
    category_id: int | None = None,
    tag: list[str] | None = None,
    sort: str = "created_at",
    order: str = "desc",
) -> tuple[list[Prompt], int]:
    q = _base_query(db)

    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                Prompt.title.ilike(like),
                Prompt.description.ilike(like),
                Prompt.prompt_text.ilike(like),
            )
        )

    if status:
        q = q.filter(Prompt.status == status)
    if featured is not None:
        q = q.filter(Prompt.featured == featured)
    if category_id:
        q = q.filter(
            Prompt.id.in_(
                select(prompts_categories.c.prompt_id).where(
                    prompts_categories.c.category_id == category_id
                )
            )
        )
    if tag:
        from src.models.tag import PromptTag
        for t_name in tag:
            tag_obj = db.query(PromptTag).filter(PromptTag.name == t_name, PromptTag.deleted_at.is_(None)).first()
            if tag_obj:
                q = q.filter(
                    Prompt.id.in_(
                        select(prompts_tags.c.prompt_id).where(prompts_tags.c.tag_id == tag_obj.id)
                    )
                )
            else:
                q = q.filter(False)

    # Visibility filtering
    if visibility:
        q = q.filter(Prompt.visibility == visibility)
    elif caller is None or not caller.has_scope("prompt:read:restricted"):
        q = q.filter(Prompt.visibility != "restricted")
    if caller is None:
        q = q.filter(Prompt.visibility == "public", Prompt.status == "published")

    sort_col = _SORT_COLUMNS.get(sort, Prompt.created_at)
    if order == "asc":
        q = q.order_by(sort_col.asc())
    else:
        q = q.order_by(sort_col.desc())

    total = q.count()
    prompts = q.offset((page - 1) * per_page).limit(per_page).all()
    return prompts, total


def get_prompt(db: Session, prompt_id: int, caller=None) -> Prompt:
    p = _base_query(db).filter(Prompt.id == prompt_id).first()
    if not p:
        raise NotFoundError(f"Prompt {prompt_id} not found")
    if p.visibility == "restricted" and (caller is None or not caller.has_scope("prompt:read:restricted")):
        raise NotFoundError(f"Prompt {prompt_id} not found")
    p.view_count = (p.view_count or 0) + 1
    db.commit()
    db.refresh(p)
    return p


def create_prompt(db: Session, data: PromptCreate, caller) -> Prompt:
    user = _ensure_user(db, caller)

    # Status transition for creation
    if data.status != "draft" and not caller.has_scope("prompt:publish"):
        raise ForbiddenError("Requires prompt:publish to create with non-draft status")

    categories = []
    if data.category_ids:
        categories = db.query(PromptCategory).filter(
            PromptCategory.id.in_(data.category_ids),
            PromptCategory.deleted_at.is_(None),
        ).all()
        if len(categories) != len(data.category_ids):
            raise NotFoundError("One or more categories not found")

    tags = get_or_create_tags(db, data.tag_names)

    p = Prompt(
        title=data.title,
        description=data.description,
        prompt_text=data.prompt_text,
        example_output=data.example_output,
        image_url=data.image_url,
        status=data.status,
        visibility=data.visibility,
        featured=data.featured,
        creator_id=user.id,
        categories=categories,
        tags=tags,
    )
    if data.status == "published":
        p.published_at = _now()

    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def update_prompt(db: Session, prompt_id: int, data: PromptUpdate, caller) -> Prompt:
    p = _base_query(db).filter(Prompt.id == prompt_id).first()
    if not p:
        raise NotFoundError(f"Prompt {prompt_id} not found")

    if not caller.has_scope("prompt:write"):
        raise ForbiddenError("Requires prompt:write")

    if data.status is not None and data.status != p.status:
        _apply_status_transition(p, data.status, caller)

    if data.title is not None:
        p.title = data.title
    if data.description is not None:
        p.description = data.description
    if data.prompt_text is not None:
        p.prompt_text = data.prompt_text
    if data.example_output is not None:
        p.example_output = data.example_output
    if data.image_url is not None:
        p.image_url = data.image_url
    if data.visibility is not None:
        p.visibility = data.visibility
    if data.featured is not None:
        p.featured = data.featured

    if data.category_ids is not None:
        categories = db.query(PromptCategory).filter(
            PromptCategory.id.in_(data.category_ids),
            PromptCategory.deleted_at.is_(None),
        ).all()
        if len(categories) != len(data.category_ids):
            raise NotFoundError("One or more categories not found")
        p.categories = categories

    if data.tag_names is not None:
        p.tags = get_or_create_tags(db, data.tag_names)

    p.updated_at = _now()
    db.commit()
    db.refresh(p)
    return p


def _apply_status_transition(prompt: Prompt, new_status: str, caller) -> None:
    allowed = _VALID_TRANSITIONS.get(prompt.status, set())
    if new_status not in allowed:
        raise ConflictError(
            f"Invalid status transition: {prompt.status} → {new_status}"
        )
    if not caller.has_scope("prompt:publish"):
        raise ForbiddenError("Requires prompt:publish to change status")
    prompt.status = new_status
    if new_status == "published":
        prompt.published_at = _now()


def increment_use_count(db: Session, prompt_id: int) -> None:
    p = db.query(Prompt).filter(Prompt.id == prompt_id, Prompt.deleted_at.is_(None)).first()
    if not p:
        raise NotFoundError(f"Prompt {prompt_id} not found")
    p.use_count = (p.use_count or 0) + 1
    db.commit()


def list_featured(db: Session, caller=None) -> list[Prompt]:
    q = _base_query(db).filter(Prompt.featured == True, Prompt.status == "published")
    if caller is None or not caller.has_scope("prompt:read:restricted"):
        q = q.filter(Prompt.visibility != "restricted")
    if caller is None:
        q = q.filter(Prompt.visibility == "public")
    return q.order_by(Prompt.created_at.desc()).all()


# ── Ratings ───────────────────────────────────────────────────────────────────

def submit_rating(db: Session, prompt_id: int, user_db_id: int, rating_value: int) -> PromptRating:
    p = db.query(Prompt).filter(Prompt.id == prompt_id, Prompt.deleted_at.is_(None)).first()
    if not p:
        raise NotFoundError(f"Prompt {prompt_id} not found")

    existing = db.query(PromptRating).filter(
        PromptRating.prompt_id == prompt_id,
        PromptRating.user_id == user_db_id,
    ).first()

    if existing:
        existing.rating = rating_value
        existing.updated_at = _now()
        db.commit()
        db.refresh(existing)
        return existing

    r = PromptRating(prompt_id=prompt_id, user_id=user_db_id, rating=rating_value)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def get_user_rating(db: Session, prompt_id: int, user_db_id: int) -> PromptRating:
    r = db.query(PromptRating).filter(
        PromptRating.prompt_id == prompt_id,
        PromptRating.user_id == user_db_id,
    ).first()
    if not r:
        raise NotFoundError("No rating found for this user on this prompt")
    return r


def get_rating_stats(db: Session, prompt_id: int) -> dict:
    p = db.query(Prompt).filter(Prompt.id == prompt_id, Prompt.deleted_at.is_(None)).first()
    if not p:
        raise NotFoundError(f"Prompt {prompt_id} not found")

    ratings = db.query(PromptRating).filter(PromptRating.prompt_id == prompt_id).all()
    count = len(ratings)
    average = round(sum(r.rating for r in ratings) / count, 2) if count else 0.0
    distribution = {str(i): 0 for i in range(6)}
    for r in ratings:
        distribution[str(r.rating)] += 1

    return {"average": average, "count": count, "distribution": distribution}
