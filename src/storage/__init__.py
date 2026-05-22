from src.config import settings
from src.storage.base import StorageBackend
from src.storage.local import LocalFileSystemBackend


def get_storage_backend() -> StorageBackend:
    if settings.STORAGE_BACKEND == "local":
        return LocalFileSystemBackend(base_path=settings.STORAGE_LOCAL_PATH)
    elif settings.STORAGE_BACKEND == "s3":
        from src.storage.s3 import S3Backend

        missing = [
            v
            for v in ("S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY")
            if not getattr(settings, v)
        ]
        if missing:
            raise ValueError(f"S3 backend requires env vars: {', '.join(missing)}")
        return S3Backend(
            bucket=settings.S3_BUCKET,
            region=settings.S3_REGION,
            access_key=settings.S3_ACCESS_KEY,
            secret_key=settings.S3_SECRET_KEY,
        )
    else:
        raise ValueError(f"Unknown storage backend: {settings.STORAGE_BACKEND}")
