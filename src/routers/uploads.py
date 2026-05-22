from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status

from src.config import settings
from src.middleware.auth import get_current_user, AuthenticatedUser
from src.storage import get_storage_backend
from src.storage.base import StorageBackend

router = APIRouter(tags=["uploads"])


def _require_scope(scope: str):
    def dep(user: AuthenticatedUser = Depends(get_current_user)):
        if not user.has_scope(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "FORBIDDEN", "message": f"Requires {scope}"}},
            )
        return user
    return dep


@router.post("/uploads/images", status_code=201)
async def upload_image(
    file: UploadFile = File(...),
    backend: StorageBackend = Depends(get_storage_backend),
    _user: AuthenticatedUser = Depends(_require_scope("prompt:image")),
):
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"error": {"code": "PAYLOAD_TOO_LARGE", "message": "File exceeds maximum upload size"}},
        )
    result = await backend.upload(
        content,
        file.filename or "upload",
        file.content_type or "application/octet-stream",
    )
    return {"data": result}


@router.delete("/uploads/images/{key:path}", status_code=204)
async def delete_image(
    key: str,
    backend: StorageBackend = Depends(get_storage_backend),
    _user: AuthenticatedUser = Depends(_require_scope("prompt:image")),
):
    try:
        await backend.delete(key)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "File not found"}},
        )
    return Response(status_code=204)
