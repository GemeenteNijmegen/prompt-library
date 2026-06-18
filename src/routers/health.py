from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from src.dependencies import get_db

router = APIRouter(tags=["infrastructure"])


@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    """Check service availability. Returns 200 with version info when the API and database are reachable; 503 when the database is down. No authentication required."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "SERVICE_UNAVAILABLE", "message": "Database unavailable"}},
        )
    return {"data": {"status": "ok", "version": "0.1.0"}}
