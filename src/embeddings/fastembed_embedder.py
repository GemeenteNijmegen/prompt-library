from __future__ import annotations

# Prefix map for models that require query/passage prefixes
_PREFIXES: dict[str, tuple[str, str]] = {
    "intfloat/multilingual-e5-small": ("query: ", "passage: "),
    "intfloat/multilingual-e5-base": ("query: ", "passage: "),
    "intfloat/multilingual-e5-large": ("query: ", "passage: "),
}


class FastembedEmbedder:
    """fastembed-backed embedder; lazy-loads model on first use."""

    def __init__(self, model_name: str = "intfloat/multilingual-e5-small") -> None:
        self.model_name = model_name
        query_prefix, passage_prefix = _PREFIXES.get(model_name, ("", ""))
        self._query_prefix = query_prefix
        self._passage_prefix = passage_prefix
        self._model = None
        # dimension is determined after first use; default to 384 for E5-small
        self.dimension: int = 384

    def _get_model(self):
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def embed_query(self, text: str) -> list[float]:
        model = self._get_model()
        prefixed = f"{self._query_prefix}{text}"
        result = list(model.embed([prefixed]))
        vec = result[0].tolist()
        self.dimension = len(vec)
        return vec

    def embed_passage(self, text: str) -> list[float]:
        model = self._get_model()
        prefixed = f"{self._passage_prefix}{text}"
        result = list(model.embed([prefixed]))
        vec = result[0].tolist()
        self.dimension = len(vec)
        return vec
