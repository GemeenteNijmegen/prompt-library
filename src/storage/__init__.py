from src.config import settings
from src.storage.base import StorageBackend
from src.storage.local import LocalFileSystemBackend


def get_storage_backend() -> StorageBackend:
    if settings.STORAGE_BACKEND == "local":
        return LocalFileSystemBackend(base_path=settings.STORAGE_LOCAL_PATH)
    elif settings.STORAGE_BACKEND == "s3":
        raise NotImplementedError("S3 backend not yet implemented")
    else:
        raise ValueError(f"Unknown storage backend: {settings.STORAGE_BACKEND}")
