from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.dependencies import get_db, get_current_user, get_optional_user
from src.schemas.prompt import PromptCreate, PromptUpdate
from src.schemas.rating import RatingSubmit
from src.services import prompt_service
from src.utils.error import NotFoundError, ConflictError, ForbiddenError

router = APIRouter(tags=["prompts"])


def _require_scope(scope: str):
    def dep(user=Depends(get_current_user)):
        if not user.has_scope(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "FORBIDDEN", "message": f"Requires {scope}"}},
            )
        return user
    return dep


def _handle(exc: NotFoundError | ConflictError | ForbiddenError):
    codes = {NotFoundError: 404, ConflictError: 409, ForbiddenError: 403}
    raise HTTPException(
        status_code=codes[type(exc)],
        detail={"error": {"code": exc.code, "message": exc.message}},
    )


# ── Featured must come before /{id} ──────────────────────────────────────────

@router.get("/prompts/featured", response_model=dict)
def list_featured(db: Session = Depends(get_db), caller=Depends(get_optional_user)):
    prompts = prompt_service.list_featured(db, caller)
    from src.schemas.prompt import PromptSummary
    return {"data": [PromptSummary.model_validate(p).model_dump() for p in prompts]}


# ── Prompts CRUD ──────────────────────────────────────────────────────────────

@router.get("/prompts", response_model=dict)
def list_prompts(
    db: Session = Depends(get_db),
    caller=Depends(get_optional_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str | None = None,
    status: str | None = None,
    visibility: str | None = None,
    featured: bool | None = None,
    category_id: int | None = None,
    tag: list[str] = Query(default=[]),
    sort: str = Query("created_at", pattern="^(created_at|published_at|view_count|use_count|title)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
):
    prompts, total = prompt_service.list_prompts(
        db,
        caller=caller,
        page=page,
        per_page=per_page,
        search=search,
        status=status,
        visibility=visibility,
        featured=featured,
        category_id=category_id,
        tag=tag if tag else None,
        sort=sort,
        order=order,
    )
    from src.schemas.prompt import PromptSummary
    import math
    return {
        "data": [PromptSummary.model_validate(p).model_dump() for p in prompts],
        "meta": {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, math.ceil(total / per_page)),
        },
    }


@router.get("/prompts/{prompt_id}", response_model=dict)
def get_prompt(prompt_id: int, db: Session = Depends(get_db), caller=Depends(get_optional_user)):
    try:
        p = prompt_service.get_prompt(db, prompt_id, caller)
        from src.schemas.prompt import PromptDetail
        return {"data": PromptDetail.model_validate(p).model_dump()}
    except NotFoundError as e:
        _handle(e)


@router.post("/prompts", status_code=status.HTTP_201_CREATED, response_model=dict)
def create_prompt(
    data: PromptCreate,
    db: Session = Depends(get_db),
    caller=Depends(_require_scope("prompt:create")),
):
    try:
        p = prompt_service.create_prompt(db, data, caller)
        from src.schemas.prompt import PromptDetail
        return {"data": PromptDetail.model_validate(p).model_dump(), "meta": {"action": "created"}}
    except (NotFoundError, ConflictError, ForbiddenError) as e:
        _handle(e)


@router.patch("/prompts/{prompt_id}", response_model=dict)
def update_prompt(
    prompt_id: int,
    data: PromptUpdate,
    db: Session = Depends(get_db),
    caller=Depends(get_current_user),
):
    try:
        p = prompt_service.update_prompt(db, prompt_id, data, caller)
        from src.schemas.prompt import PromptDetail
        return {"data": PromptDetail.model_validate(p).model_dump()}
    except (NotFoundError, ConflictError, ForbiddenError) as e:
        _handle(e)


@router.post("/prompts/{prompt_id}/use", status_code=status.HTTP_204_NO_CONTENT)
def use_prompt(prompt_id: int, db: Session = Depends(get_db)):
    try:
        prompt_service.increment_use_count(db, prompt_id)
    except NotFoundError as e:
        _handle(e)


# ── Ratings ───────────────────────────────────────────────────────────────────

@router.post("/prompts/{prompt_id}/rate", response_model=dict)
def submit_rating(
    prompt_id: int,
    data: RatingSubmit,
    db: Session = Depends(get_db),
    caller=Depends(_require_scope("prompt:rate")),
):
    user = _get_or_create_user(db, caller)
    try:
        r = prompt_service.submit_rating(db, prompt_id, user.id, data.rating)
        from src.schemas.rating import RatingDetail
        return {"data": RatingDetail.model_validate(r).model_dump()}
    except NotFoundError as e:
        _handle(e)


@router.get("/prompts/{prompt_id}/rate", response_model=dict)
def get_user_rating(
    prompt_id: int,
    db: Session = Depends(get_db),
    caller=Depends(_require_scope("prompt:rate")),
):
    user = _get_or_create_user(db, caller)
    try:
        r = prompt_service.get_user_rating(db, prompt_id, user.id)
        from src.schemas.rating import RatingDetail
        return {"data": RatingDetail.model_validate(r).model_dump()}
    except NotFoundError as e:
        _handle(e)


@router.get("/prompts/{prompt_id}/ratings", response_model=dict)
def get_rating_stats(prompt_id: int, db: Session = Depends(get_db)):
    try:
        stats = prompt_service.get_rating_stats(db, prompt_id)
        return {"data": stats}
    except NotFoundError as e:
        _handle(e)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_or_create_user(db: Session, caller):
    from src.models.user import User
    user = db.query(User).filter(User.external_id == caller.external_id).first()
    if not user:
        user = User(external_id=caller.external_id, name=caller.name, email=caller.email)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user
