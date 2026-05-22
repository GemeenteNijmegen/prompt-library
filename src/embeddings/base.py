from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    dimension: int

    def embed_passage(self, text: str) -> list[float]: ...
    def embed_query(self, text: str) -> list[float]: ...
