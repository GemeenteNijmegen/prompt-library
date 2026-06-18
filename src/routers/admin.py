from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.dependencies import get_current_user, get_db
from src.models.prompt_event import PromptEvent
from src.utils.openapi_responses import UNAUTHORIZED, FORBIDDEN

router = APIRouter(tags=["admin"])


def _require_scope(scope: str):
    def dep(user=Depends(get_current_user)):
        if not user.has_scope(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "FORBIDDEN", "message": f"Requires {scope}"}},
            )
        return user
    return dep


@router.get("/admin/audit", responses={**UNAUTHORIZED, **FORBIDDEN})
def list_audit_events(
    entity_type: str | None = Query(None),
    entity_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    caller=Depends(_require_scope("admin:read_audit")),
):
    """Return a paginated audit log of gallery actions (prompt created/updated/deleted, API keys issued/revoked, etc.). Filterable by entity_type and entity_id. Requires the `admin:read_audit` scope."""
    q = db.query(PromptEvent).order_by(PromptEvent.created_at.desc())
    if entity_type is not None:
        q = q.filter(PromptEvent.entity_type == entity_type)
    if entity_id is not None:
        q = q.filter(PromptEvent.entity_id == entity_id)
    events = q.limit(limit).all()
    return {
        "data": [
            {
                "id": e.id,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "action": e.action,
                "client_id": e.client_id,
                "actor_user_id": e.actor_user_id,
                "actor_org_id": e.actor_org_id,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ]
    }
