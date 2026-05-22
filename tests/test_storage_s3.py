import pytest
import boto3
from moto import mock_aws

from src.storage.s3 import S3Backend
from src.storage.base import StorageBackend

BUCKET = "test-bucket"
REGION = "eu-west-1"


@pytest.fixture
def s3_backend():
    with mock_aws():
        boto3.client("s3", region_name=REGION).create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
        yield S3Backend(
            bucket=BUCKET,
            region=REGION,
            access_key="test",
            secret_key="test",
        )


@pytest.mark.asyncio
async def test_upload_returns_url_and_key(s3_backend):
    result = await s3_backend.upload(b"hello s3", "image.png", "image/png")
    assert "url" in result
    assert "key" in result
    assert result["key"].endswith(".png")
    assert BUCKET in result["url"]
    assert result["key"] in result["url"]


@pytest.mark.asyncio
async def test_upload_content_stored_in_bucket(s3_backend):
    content = b"binary content"
    result = await s3_backend.upload(content, "file.bin", "application/octet-stream")
    stored = s3_backend._client.get_object(Bucket=BUCKET, Key=result["key"])["Body"].read()
    assert stored == content


@pytest.mark.asyncio
async def test_get_url_returns_public_url(s3_backend):
    result = await s3_backend.upload(b"data", "img.jpg", "image/jpeg")
    url = await s3_backend.get_url(result["key"])
    assert url == result["url"]
    assert result["key"] in url


@pytest.mark.asyncio
async def test_delete_removes_object(s3_backend):
    result = await s3_backend.upload(b"to delete", "del.txt", "text/plain")
    await s3_backend.delete(result["key"])
    import botocore.exceptions
    with pytest.raises(botocore.exceptions.ClientError):
        s3_backend._client.head_object(Bucket=BUCKET, Key=result["key"])


@pytest.mark.asyncio
async def test_delete_missing_key_raises_file_not_found(s3_backend):
    with pytest.raises(FileNotFoundError):
        await s3_backend.delete("nonexistent-key.txt")


def test_s3_backend_satisfies_protocol(s3_backend):
    assert isinstance(s3_backend, StorageBackend)


def test_factory_raises_when_s3_vars_missing(monkeypatch):
    import src.storage as storage_module
    from src.config import Settings

    monkeypatch.setattr(
        storage_module,
        "settings",
        Settings(STORAGE_BACKEND="s3", S3_BUCKET="", S3_ACCESS_KEY="", S3_SECRET_KEY=""),
    )
    with pytest.raises(ValueError, match="S3 backend requires env vars"):
        storage_module.get_storage_backend()
