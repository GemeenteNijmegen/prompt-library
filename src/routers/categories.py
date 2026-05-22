from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.cache import cache_delete, cache_get, cache_set
from src.dependencies import get_db, get_current_user
from src.schemas.category import CategoryCreate, CategoryUpdate, CategoryDetail
from src.schemas.common import DataResponse, PaginatedResponse, ActionResponse
from src.services import taxonomy_service
from src.utils.error import NotFoundError, ConflictError

router = APIRouter(tags=["categories"])

_CACHE_KEY = "categories:list"


def _require_taxonomy(user=Depends(get_current_user)):
    if not user.has_scope("admin:manage_taxonomy"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": {"code": "FORBIDDEN", "message": "Requires admin:manage_taxonomy"}})
    return user


@router.get("/categories", response_model=dict)
def list_categories(db: Session = Depends(get_db)):
    cached = cache_get(_CACHE_KEY)
    if cached is not None:
        return {"data": cached}
    cats = taxonomy_service.list_categories(db)
    cache_set(_CACHE_KEY, cats)
    return {"data": cats}


@router.get("/categories/{category_id}", response_model=dict)
def get_category(category_id: int, db: Session = Depends(get_db)):
    try:
        return {"data": taxonomy_service.get_category(db, category_id)}
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail={"error": {"code": e.code, "message": e.message}})


@router.post("/categories", status_code=status.HTTP_201_CREATED, response_model=dict)
def create_category(data: CategoryCreate, db: Session = Depends(get_db), user=Depends(_require_taxonomy)):
    try:
        cat = taxonomy_service.create_category(db, data)
        cache_delete(_CACHE_KEY)
        return {"data": cat, "meta": {"action": "created"}}
    except ConflictError as e:
        raise HTTPException(status_code=409, detail={"error": {"code": e.code, "message": e.message}})


@router.patch("/categories/{category_id}", response_model=dict)
def update_category(category_id: int, data: CategoryUpdate, db: Session = Depends(get_db), user=Depends(_require_taxonomy)):
    try:
        cat = taxonomy_service.update_category(db, category_id, data)
        cache_delete(_CACHE_KEY)
        return {"data": cat}
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail={"error": {"code": e.code, "message": e.message}})
    except ConflictError as e:
        raise HTTPException(status_code=409, detail={"error": {"code": e.code, "message": e.message}})


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(category_id: int, db: Session = Depends(get_db), user=Depends(_require_taxonomy)):
    try:
        taxonomy_service.soft_delete_category(db, category_id)
        cache_delete(_CACHE_KEY)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail={"error": {"code": e.code, "message": e.message}})
