from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.dependencies import get_db, get_current_user
from src.schemas.user import UserProfile
from src.models.user import User

router = APIRouter(tags=["auth"])


@router.get("/me", response_model=dict)
def get_me(db: Session = Depends(get_db), caller=Depends(get_current_user)):
    user = db.query(User).filter(User.external_id == caller.external_id).first()
    if not user:
        user = User(external_id=caller.external_id, name=caller.name, email=caller.email)
        db.add(user)
        db.commit()
        db.refresh(user)
    return {"data": UserProfile.model_validate(user).model_dump()}
