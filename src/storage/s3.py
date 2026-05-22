import uuid
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


class S3Backend:
    def __init__(self, bucket: str, region: str, access_key: str, secret_key: str):
        self.bucket = bucket
        self.region = region
        self._client = boto3.client(
            "s3",
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def _public_url(self, key: str) -> str:
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}"

    async def upload(self, file: bytes, filename: str, content_type: str) -> dict:
        suffix = Path(filename).suffix
        key = f"{uuid.uuid4()}{suffix}"
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=file,
            ContentType=content_type,
        )
        return {"url": self._public_url(key), "key": key}

    async def get_url(self, file_key: str) -> str:
        return self._public_url(file_key)

    async def delete(self, file_key: str) -> None:
        try:
            self._client.head_object(Bucket=self.bucket, Key=file_key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "404":
                raise FileNotFoundError(f"File not found: {file_key}") from exc
            raise
        self._client.delete_object(Bucket=self.bucket, Key=file_key)
