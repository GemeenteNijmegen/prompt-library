from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.cache import cache_delete, cache_get, cache_set
from src.dependencies import get_db, get_current_user
from src.schemas.tag import TagCreate, TagDetail
from src.services import taxonomy_service
from src.services.audit_service import write_event
from src.utils.error import NotFoundError, ConflictError

router = APIRouter(tags=["tags"])

_CACHE_KEY = "tags:list"


def _require_taxonomy(user=Depends(get_current_user)):
    if not user.has_scope("admin:manage_taxonomy"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": {"code": "FORBIDDEN", "message": "Requires admin:manage_taxonomy"}})
    return user


@router.get("/tags", response_model=dict)
def list_tags(db: Session = Depends(get_db)):
    cached = cache_get(_CACHE_KEY)
    if cached is not None:
        return {"data": cached}
    tags = taxonomy_service.list_tags(db)
    cache_set(_CACHE_KEY, tags)
    return {"data": tags}


@router.get("/tags/{tag_id}", response_model=dict)
def get_tag(tag_id: int, db: Session = Depends(get_db)):
    try:
        return {"data": taxonomy_service.get_tag(db, tag_id)}
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail={"error": {"code": e.code, "message": e.message}})


@router.post("/tags", status_code=status.HTTP_201_CREATED, response_model=dict)
def create_tag(data: TagCreate, db: Session = Depends(get_db), user=Depends(_require_taxonomy)):
    try:
        tag = taxonomy_service.create_tag(db, data)
        write_event(db, entity_type="tag", entity_id=tag["id"], action="created", caller=user, details={"name": tag["name"]})
        cache_delete(_CACHE_KEY)
        return {"data": tag, "meta": {"action": "created"}}
    except ConflictError as e:
        raise HTTPException(status_code=409, detail={"error": {"code": e.code, "message": e.message}})


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(tag_id: int, db: Session = Depends(get_db), user=Depends(_require_taxonomy)):
    try:
        taxonomy_service.soft_delete_tag(db, tag_id)
        write_event(db, entity_type="tag", entity_id=tag_id, action="deleted", caller=user)
        cache_delete(_CACHE_KEY)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail={"error": {"code": e.code, "message": e.message}})
