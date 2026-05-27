import json
import logging
import time
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

log = logging.getLogger(__name__)

from src.models.prompt import Prompt
from src.models.user import User
from src.models.category import PromptCategory
from src.models.rating import PromptRating
from src.models.joins import prompts_categories, prompts_tags
from src.schemas.prompt import PromptCreate, PromptUpdate
from src.services.taxonomy_service import get_or_create_tags
from src.utils.error import NotFoundError, ConflictError, ForbiddenError, EmbedError


_VALID_TRANSITIONS = {
    "draft": {"published_org"},
    "published_org": {"published_public", "archived"},
    "published_public": {"published_org", "archived"},
    "archived": {"draft"},
}

_SORT_COLUMNS = {
    "created_at": Prompt.created_at,
    "published_at": Prompt.published_at,
    "view_count": Prompt.view_count,
    "use_count": Prompt.use_count,
    "title": Prompt.title,
}

_RRF_K = 60
_VECTOR_TOP_K = 50
_CACHE_TTL = 60

# In-process vector matrix cache: {id: np.ndarray}
_vector_cache: dict[int, np.ndarray] = {}
_vector_cache_loaded_at: float = 0.0


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _embedding_source(title: str, description: str, prompt_text: str) -> str:
    return f"{title}\n\n{description}\n\n{prompt_text}"


def _get_embedder():
    from src.embeddings import get_embedder
    return get_embedder()


def _invalidate_vector_cache() -> None:
    global _vector_cache, _vector_cache_loaded_at
    _vector_cache = {}
    _vector_cache_loaded_at = 0.0


def _load_vector_cache(db: Session) -> dict[int, np.ndarray]:
    global _vector_cache, _vector_cache_loaded_at
    now = time.monotonic()
    if _vector_cache and (now - _vector_cache_loaded_at) < _CACHE_TTL:
        return _vector_cache

    rows = (
        db.query(Prompt.id, Prompt.embedding_vector)
        .filter(Prompt.deleted_at.is_(None), Prompt.embedding_vector.isnot(None))
        .all()
    )
    cache: dict[int, np.ndarray] = {}
    for row_id, ev in rows:
        try:
            vec = np.array(json.loads(ev), dtype=np.float32)
            cache[row_id] = vec
        except Exception:
            pass

    _vector_cache = cache
    _vector_cache_loaded_at = now
    return cache


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _rrf_fuse(
    keyword_ids: list[int],
    vector_ids: list[int],
    k: int = _RRF_K,
) -> tuple[list[int], dict[int, float]]:
    scores: dict[int, float] = {}
    for rank, pid in enumerate(keyword_ids):
        scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + rank + 1)
    for rank, pid in enumerate(vector_ids):
        scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + rank + 1)
    ordered = sorted(scores.keys(), key=lambda pid: scores[pid], reverse=True)
    return ordered, scores


def _base_query(db: Session):
    return (
        db.query(Prompt)
        .options(selectinload(Prompt.categories), selectinload(Prompt.tags))
        .filter(Prompt.deleted_at.is_(None))
    )


def visibility_filter(caller):
    """Return a SQLAlchemy clause implementing CONTEXT.md §Visibility model.

    published_public
    OR (published_org AND org_id = caller.org_id)
    OR (draft AND (author_id = caller.id OR caller is Org Admin of author's org))

    Algorithm whitelist: RS256 for JWKS path, HS256 for HMAC path — do not
    remove the check in jwt_utils; it prevents algorithm-confusion attacks.
    """
    if caller is None:
        return Prompt.status == "published_public"

    org_id = getattr(caller, "org_id", "")

    if not org_id:
        return or_(
            Prompt.status == "published_public",
            and_(Prompt.status == "draft", Prompt.creator_id == caller.id),
        )

    # Correlated subquery: prompt's author belongs to the caller's org
    same_org = (
        select(User.id)
        .where(User.id == Prompt.creator_id, User.org_id == org_id)
        .correlate(Prompt)
        .exists()
    )

    parts = [
        Prompt.status == "published_public",
        and_(Prompt.status == "published_org", same_org),
    ]
    if caller.is_org_admin:
        parts.append(and_(Prompt.status == "draft", same_org))
    else:
        parts.append(and_(Prompt.status == "draft", Prompt.creator_id == caller.id))

    return or_(*parts)


def _apply_visibility_filters(q, caller, visibility):
    # Prompt.visibility column gate (public / internal / restricted)
    if visibility:
        q = q.filter(Prompt.visibility == visibility)
    elif caller is None or not caller.has_scope("prompt:read:restricted"):
        q = q.filter(Prompt.visibility != "restricted")

    # Anonymous callers: also exclude non-public visibility column
    if caller is None:
        q = q.filter(Prompt.visibility == "public")

    # Status-based row-level org visibility (CONTEXT.md §Visibility model)
    q = q.filter(visibility_filter(caller))
    return q


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

    q = _apply_visibility_filters(q, caller, visibility)

    if not search:
        sort_col = _SORT_COLUMNS.get(sort, Prompt.created_at)
        if order == "asc":
            q = q.order_by(sort_col.asc())
        else:
            q = q.order_by(sort_col.desc())

        total = q.count()
        prompts = q.offset((page - 1) * per_page).limit(per_page).all()
        return prompts, total

    # Hybrid search path
    # Keyword candidates: ILIKE over title/description/prompt_text
    like = f"%{search}%"
    keyword_q = q.filter(
        or_(
            Prompt.title.ilike(like),
            Prompt.description.ilike(like),
            Prompt.prompt_text.ilike(like),
        )
    )
    # Fetch all candidate IDs from keyword search (no pagination yet)
    keyword_rows = keyword_q.with_entities(Prompt.id, Prompt.title).all()
    keyword_ids = [r[0] for r in keyword_rows]
    _kw_titles = {r[0]: r[1] for r in keyword_rows}

    if log.isEnabledFor(logging.DEBUG):
        log.debug(
            "hybrid search q=%r  keyword hits=%d: %s",
            search,
            len(keyword_ids),
            [(pid, _kw_titles[pid]) for pid in keyword_ids[:10]],
        )

    # Vector candidates: score against embedded query
    vector_cache = _load_vector_cache(db)
    # Get IDs that passed SQL filters (visibility/status etc.) — reuse q for filter context
    filter_ids_rows = q.with_entities(Prompt.id).all()
    filter_ids = set(r[0] for r in filter_ids_rows)

    embedder = _get_embedder()
    query_vec = np.array(embedder.embed_query(search), dtype=np.float32)

    scored: list[tuple[int, float]] = []
    for pid, vec in vector_cache.items():
        if pid in filter_ids:
            scored.append((pid, _cosine_similarity(query_vec, vec)))
    scored.sort(key=lambda x: x[1], reverse=True)
    vector_ids = [pid for pid, _ in scored[:_VECTOR_TOP_K]]

    if log.isEnabledFor(logging.DEBUG):
        _vec_title_rows = (
            db.query(Prompt.id, Prompt.title)
            .filter(Prompt.id.in_(vector_ids))
            .all()
        ) if vector_ids else []
        _vec_titles = {r[0]: r[1] for r in _vec_title_rows}
        _score_map = dict(scored)
        log.debug(
            "hybrid search q=%r  vector hits=%d (top %d shown): %s",
            search,
            len(scored),
            min(10, len(vector_ids)),
            [(pid, round(_score_map[pid], 4), _vec_titles.get(pid, "?")) for pid in vector_ids[:10]],
        )

    # RRF fusion
    fused_ids, rrf_scores = _rrf_fuse(keyword_ids, vector_ids)
    total = len(fused_ids)

    if log.isEnabledFor(logging.DEBUG):
        _fused_title_rows = (
            db.query(Prompt.id, Prompt.title)
            .filter(Prompt.id.in_(fused_ids[:10]))
            .all()
        ) if fused_ids else []
        _fused_titles = {r[0]: r[1] for r in _fused_title_rows}
        log.debug(
            "hybrid search q=%r  fused total=%d (top %d shown): %s",
            search,
            total,
            min(10, len(fused_ids)),
            [
                (pid, round(rrf_scores[pid], 4), _fused_titles.get(pid, "?"))
                for pid in fused_ids[:10]
            ],
        )

    # Pagination
    page_ids = fused_ids[(page - 1) * per_page: page * per_page]
    if not page_ids:
        return [], total

    # Fetch prompts in fused order
    id_to_prompt: dict[int, Prompt] = {
        p.id: p
        for p in _base_query(db).filter(Prompt.id.in_(page_ids)).all()
    }
    prompts = [id_to_prompt[pid] for pid in page_ids if pid in id_to_prompt]
    return prompts, total


def get_prompt(db: Session, prompt_id: int, caller=None) -> Prompt:
    q = _base_query(db).filter(Prompt.id == prompt_id)
    q = _apply_visibility_filters(q, caller, visibility=None)
    p = q.first()
    if not p:
        raise NotFoundError(f"Prompt {prompt_id} not found")
    p.view_count = (p.view_count or 0) + 1
    db.commit()
    db.refresh(p)
    return p


def create_prompt(db: Session, data: PromptCreate, caller) -> Prompt:
    user = _ensure_user(db, caller)

    if data.status == "published_public" and not caller.has_scope("prompt:publish:public"):
        raise ForbiddenError("Requires prompt:publish:public to create with published_public status")
    if data.status not in ("draft", None) and not caller.has_scope("prompt:publish"):
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

    source = _embedding_source(data.title, data.description, data.prompt_text)
    try:
        embedder = _get_embedder()
        vector = embedder.embed_passage(source)
        embedding_vector = json.dumps(vector)
    except Exception as exc:
        raise EmbedError(f"Embedding failed: {exc}") from exc

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
        embedding_vector=embedding_vector,
    )
    if data.status in ("published_org", "published_public"):
        p.published_at = _now()

    db.add(p)
    db.commit()
    db.refresh(p)
    _invalidate_vector_cache()
    return p


def update_prompt(db: Session, prompt_id: int, data: PromptUpdate, caller) -> Prompt:
    q = _base_query(db).filter(Prompt.id == prompt_id)
    q = _apply_visibility_filters(q, caller, visibility=None)
    p = q.first()
    if not p:
        raise NotFoundError(f"Prompt {prompt_id} not found")

    if not caller.has_scope("prompt:write"):
        raise ForbiddenError("Requires prompt:write")

    if data.status is not None and data.status != p.status:
        _apply_status_transition(p, data.status, caller)

    # Compute old source before applying patch fields
    old_source = _embedding_source(p.title, p.description, p.prompt_text)

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

    new_source = _embedding_source(p.title, p.description, p.prompt_text)
    did_reembed = False
    if new_source != old_source:
        try:
            embedder = _get_embedder()
            vector = embedder.embed_passage(new_source)
            p.embedding_vector = json.dumps(vector)
            did_reembed = True
        except Exception as exc:
            raise EmbedError(f"Embedding failed: {exc}") from exc

    p.updated_at = _now()
    db.commit()
    db.refresh(p)

    if did_reembed:
        _invalidate_vector_cache()

    return p


def reembed_prompt(db: Session, prompt_id: int, embedder) -> bool:
    """Re-embed a single prompt within an active session. Returns True if updated."""
    p = db.query(Prompt).filter(Prompt.id == prompt_id, Prompt.deleted_at.is_(None)).first()
    if not p:
        return False
    source = _embedding_source(p.title, p.description, p.prompt_text)
    vector = embedder.embed_passage(source)
    p.embedding_vector = json.dumps(vector)
    return True


def _apply_status_transition(prompt: Prompt, new_status: str, caller) -> None:
    allowed = _VALID_TRANSITIONS.get(prompt.status, set())
    if new_status not in allowed:
        raise ConflictError(
            f"Invalid status transition: {prompt.status} → {new_status}"
        )
    if new_status == "published_public" and not caller.has_scope("prompt:publish:public"):
        raise ForbiddenError("Requires prompt:publish:public to promote to published_public")
    if not caller.has_scope("prompt:publish"):
        raise ForbiddenError("Requires prompt:publish to change status")
    prompt.status = new_status
    if new_status in ("published_org", "published_public"):
        prompt.published_at = _now()


def increment_use_count(db: Session, prompt_id: int) -> None:
    p = db.query(Prompt).filter(Prompt.id == prompt_id, Prompt.deleted_at.is_(None)).first()
    if not p:
        raise NotFoundError(f"Prompt {prompt_id} not found")
    p.use_count = (p.use_count or 0) + 1
    db.commit()


def list_featured(db: Session, caller=None) -> list[Prompt]:
    q = _base_query(db).filter(Prompt.featured == True)
    q = _apply_visibility_filters(q, caller, visibility=None)
    # Drafts never appear in featured listings
    q = q.filter(Prompt.status != "draft")
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
