from src.embeddings.base import Embedder
from src.embeddings.fake import FakeEmbedder

__all__ = ["Embedder", "FakeEmbedder", "get_embedder"]


def get_embedder() -> Embedder:
    from src.config import settings

    if settings.EMBEDDING_USE_FAKE:
        return FakeEmbedder()

    from src.embeddings.fastembed_embedder import FastembedEmbedder
    return FastembedEmbedder(model_name=settings.EMBEDDING_MODEL)
