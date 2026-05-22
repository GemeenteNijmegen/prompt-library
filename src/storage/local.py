import uuid
from pathlib import Path


class LocalFileSystemBackend:
    def __init__(self, base_path: str | Path = "./uploads"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def upload(self, file: bytes, filename: str, content_type: str) -> dict:
        suffix = Path(filename).suffix
        key = f"{uuid.uuid4()}{suffix}"
        (self.base_path / key).write_bytes(file)
        return {"url": f"file://{self.base_path / key}", "key": key}

    async def get_url(self, file_key: str) -> str:
        return f"file://{self.base_path / file_key}"

    async def delete(self, file_key: str) -> None:
        path = self.base_path / file_key
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_key}")
        path.unlink()
