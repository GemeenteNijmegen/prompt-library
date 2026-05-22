import numpy as np


class FakeEmbedder:
    """Deterministic fake embedder for testing. Same input → same unit vector."""

    dimension: int = 384

    def _make_vector(self, text: str) -> list[float]:
        seed = hash(text) % (2**32)
        rng = np.random.default_rng(seed)
        vec = rng.standard_normal(self.dimension).astype(np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec.tolist()

    def embed_passage(self, text: str) -> list[float]:
        return self._make_vector(f"passage:{text}")

    def embed_query(self, text: str) -> list[float]:
        return self._make_vector(f"query:{text}")
