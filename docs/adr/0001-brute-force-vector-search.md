# Brute-force vector search in Python, no pgvector or sqlite-vec

Semantic search over prompt embeddings runs as an in-process NumPy cosine similarity over the full filtered candidate set. We deliberately do **not** use `pgvector`, `sqlite-vec`, or any external vector database, despite those being the obvious choices.

## Why

The corpus is small (prompts are short, write volume is low, realistic library size is well under 10⁵ items). At 384-dim float32 vectors, NumPy scores ~1–2 µs per comparison, so even scoring 10k vectors fits comfortably inside a search request. SQL filters (visibility, status, soft-delete, category, tag) run first in the DB, so the vector path only scores the candidates that already passed those filters — which is typically a small fraction of the corpus.

The project ships both SQLite (dev/test) and PostgreSQL (prod). Using `pgvector` would mean a Postgres extension that isn't universally available on managed providers, plus a separate code path or extension dependency (`sqlite-vec`) for SQLite. Brute-force NumPy works identically on both DBs with one code path and adds no runtime dependency beyond `numpy` (already pulled in via the embedding library).

## Considered alternatives

- **`pgvector` + `sqlite-vec`.** Native vector indexes on both. Rejected for the dependency cost and divergent code paths at the scale we operate at.
- **`pgvector` on Postgres, brute-force on SQLite.** Two code paths to maintain for a problem brute-force handles on both.
- **External vector DB (Pinecone, Qdrant, Weaviate).** A whole additional service to deploy and operate; massively disproportionate to the corpus size.

## Upgrade path

If the corpus ever grows past the point where brute-force is too slow (rough threshold: ~10⁵ prompts, or filter selectivity drops such that single requests routinely score >50k vectors), migrate to `pgvector` via Alembic: change `embedding_vector` from JSONB to `vector(384)`, add an HNSW index, swap the scoring function behind the `Embedder` / search-service abstraction. The change is localized; making it now is YAGNI.
