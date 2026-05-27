import json

from sqlalchemy.orm import Session

from src.models.prompt_event import PromptEvent


def write_event(
    db: Session,
    *,
    entity_type: str,
    entity_id: str | int,
    action: str,
    caller,
    details: dict | None = None,
) -> None:
    row = PromptEvent(
        entity_type=entity_type,
        entity_id=str(entity_id),
        action=action,
        actor_user_id=caller.id,
        actor_org_id=caller.org_id,
        client_id=caller.azp,
        details=json.dumps(details) if details is not None else None,
    )
    db.add(row)
    db.commit()
