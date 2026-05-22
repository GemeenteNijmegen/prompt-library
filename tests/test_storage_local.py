import pytest
from pathlib import Path

from src.storage.local import LocalFileSystemBackend
from src.storage.base import StorageBackend


def make_backend(tmp_path: Path) -> LocalFileSystemBackend:
    return LocalFileSystemBackend(base_path=tmp_path)


@pytest.mark.asyncio
async def test_upload_stores_file_and_returns_url_and_key(tmp_path):
    backend = make_backend(tmp_path)
    content = b"hello world"
    result = await backend.upload(content, "test.txt", "text/plain")
    assert "url" in result
    assert "key" in result
    stored = (tmp_path / result["key"]).read_bytes()
    assert stored == content


@pytest.mark.asyncio
async def test_upload_preserves_extension(tmp_path):
    backend = make_backend(tmp_path)
    result = await backend.upload(b"img", "photo.png", "image/png")
    assert result["key"].endswith(".png")


@pytest.mark.asyncio
async def test_get_url_returns_correct_url(tmp_path):
    backend = make_backend(tmp_path)
    result = await backend.upload(b"data", "img.png", "image/png")
    url = await backend.get_url(result["key"])
    assert url == result["url"]


@pytest.mark.asyncio
async def test_delete_removes_file(tmp_path):
    backend = make_backend(tmp_path)
    result = await backend.upload(b"data", "del.txt", "text/plain")
    file_path = tmp_path / result["key"]
    assert file_path.exists()
    await backend.delete(result["key"])
    assert not file_path.exists()


@pytest.mark.asyncio
async def test_delete_missing_key_raises_file_not_found(tmp_path):
    backend = make_backend(tmp_path)
    with pytest.raises(FileNotFoundError):
        await backend.delete("nonexistent-key.txt")


def test_storage_backend_protocol_satisfied(tmp_path):
    backend = make_backend(tmp_path)
    assert isinstance(backend, StorageBackend)
