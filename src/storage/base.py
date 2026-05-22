from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    async def upload(self, file: bytes, filename: str, content_type: str) -> dict:
        """Returns {"url": "...", "key": "..."}"""
        ...

    async def get_url(self, file_key: str) -> str: ...

    async def delete(self, file_key: str) -> None: ...
