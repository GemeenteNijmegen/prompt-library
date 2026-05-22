from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models.category import PromptCategory
from src.models.tag import PromptTag
from src.models.joins import prompts_categories, prompts_tags
from src.schemas.category import CategoryCreate, CategoryUpdate
from src.schemas.tag import TagCreate
from src.utils.error import NotFoundError, ConflictError


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── Categories ────────────────────────────────────────────────────────────────

def list_categories(db: Session) -> list[dict]:
    cats = db.query(PromptCategory).filter(PromptCategory.deleted_at.is_(None)).all()
    result = []
    for c in cats:
        count = db.execute(
            select(func.count()).select_from(prompts_categories).where(prompts_categories.c.category_id == c.id)
        ).scalar_one()
        result.append({**_cat_dict(c), "prompt_count": count})
    return result


def get_category(db: Session, category_id: int) -> dict:
    c = db.query(PromptCategory).filter(
        PromptCategory.id == category_id, PromptCategory.deleted_at.is_(None)
    ).first()
    if not c:
        raise NotFoundError(f"Category {category_id} not found")
    count = db.execute(
        select(func.count()).select_from(prompts_categories).where(prompts_categories.c.category_id == c.id)
    ).scalar_one()
    return {**_cat_dict(c), "prompt_count": count}


def create_category(db: Session, data: CategoryCreate) -> dict:
    existing = db.query(PromptCategory).filter(PromptCategory.name == data.name).first()
    if existing and existing.deleted_at is None:
        raise ConflictError(f"Category '{data.name}' already exists")
    cat = PromptCategory(name=data.name, description=data.description)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return {**_cat_dict(cat), "prompt_count": 0}


def update_category(db: Session, category_id: int, data: CategoryUpdate) -> dict:
    c = db.query(PromptCategory).filter(
        PromptCategory.id == category_id, PromptCategory.deleted_at.is_(None)
    ).first()
    if not c:
        raise NotFoundError(f"Category {category_id} not found")
    if data.name is not None:
        dup = db.query(PromptCategory).filter(
            PromptCategory.name == data.name, PromptCategory.id != category_id, PromptCategory.deleted_at.is_(None)
        ).first()
        if dup:
            raise ConflictError(f"Category '{data.name}' already exists")
        c.name = data.name
    if data.description is not None:
        c.description = data.description
    db.commit()
    db.refresh(c)
    count = db.execute(
        select(func.count()).select_from(prompts_categories).where(prompts_categories.c.category_id == c.id)
    ).scalar_one()
    return {**_cat_dict(c), "prompt_count": count}


def soft_delete_category(db: Session, category_id: int) -> None:
    c = db.query(PromptCategory).filter(
        PromptCategory.id == category_id, PromptCategory.deleted_at.is_(None)
    ).first()
    if not c:
        raise NotFoundError(f"Category {category_id} not found")
    c.deleted_at = _now()
    # Unlink from prompts via the association table
    db.execute(
        prompts_categories.delete().where(prompts_categories.c.category_id == category_id)
    )
    db.commit()


def _cat_dict(c: PromptCategory) -> dict:
    return {"id": c.id, "name": c.name, "description": c.description, "created_at": c.created_at}


# ── Tags ──────────────────────────────────────────────────────────────────────

def list_tags(db: Session) -> list[dict]:
    tags = db.query(PromptTag).filter(PromptTag.deleted_at.is_(None)).all()
    result = []
    for t in tags:
        count = db.execute(
            select(func.count()).select_from(prompts_tags).where(prompts_tags.c.tag_id == t.id)
        ).scalar_one()
        result.append({**_tag_dict(t), "prompt_count": count})
    return result


def get_tag(db: Session, tag_id: int) -> dict:
    t = db.query(PromptTag).filter(
        PromptTag.id == tag_id, PromptTag.deleted_at.is_(None)
    ).first()
    if not t:
        raise NotFoundError(f"Tag {tag_id} not found")
    count = db.execute(
        select(func.count()).select_from(prompts_tags).where(prompts_tags.c.tag_id == t.id)
    ).scalar_one()
    return {**_tag_dict(t), "prompt_count": count}


def create_tag(db: Session, data: TagCreate) -> dict:
    existing = db.query(PromptTag).filter(PromptTag.name == data.name).first()
    if existing and existing.deleted_at is None:
        raise ConflictError(f"Tag '{data.name}' already exists")
    tag = PromptTag(name=data.name)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return {**_tag_dict(tag), "prompt_count": 0}


def soft_delete_tag(db: Session, tag_id: int) -> None:
    t = db.query(PromptTag).filter(
        PromptTag.id == tag_id, PromptTag.deleted_at.is_(None)
    ).first()
    if not t:
        raise NotFoundError(f"Tag {tag_id} not found")
    t.deleted_at = _now()
    db.execute(
        prompts_tags.delete().where(prompts_tags.c.tag_id == tag_id)
    )
    db.commit()


def get_or_create_tags(db: Session, names: list[str]) -> list[PromptTag]:
    tags = []
    for name in names:
        name = name.strip().lower()
        if not name:
            continue
        tag = db.query(PromptTag).filter(PromptTag.name == name).first()
        if tag is None:
            tag = PromptTag(name=name)
            db.add(tag)
            db.flush()
        elif tag.deleted_at is not None:
            # Resurrect soft-deleted tag
            tag.deleted_at = None
            db.flush()
        tags.append(tag)
    return tags


def _tag_dict(t: PromptTag) -> dict:
    return {"id": t.id, "name": t.name, "created_at": t.created_at}
