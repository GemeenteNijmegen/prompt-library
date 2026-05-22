# Embedding model: multilingual default, single env-var override, in-place re-embed

The server owns the embedding model for semantic search (caller-submitted vectors won't work — clients use different models and the vector spaces are incompatible). The default model is `intfloat/multilingual-e5-small` (384-dim, ~120 MB), bundled into the published Docker image. Operators can swap models via the `EMBEDDING_MODEL` env var; switching triggers a one-shot `scripts/reembed.py` to rewrite vectors in-place.

## Why multilingual-e5-small as the default

Prompt content in this gallery is primarily Dutch with English technical terms mixed in. English-only models (e.g. `bge-small-en-v1.5`) collapse on Dutch text. Among small multilingual retrieval models, E5-small has the best published retrieval quality on cross-lingual tasks, fits in the same 384-dim / ~120 MB envelope we'd budgeted for English-only models, and handles mixed-language content gracefully. The cost is that E5 requires `"query: "` / `"passage: "` prefixes — handled centrally in the embedder wrapper.

## Why single env var + closed-ish behavior, not a full registry

An earlier sketch had a closed model registry with metadata, per-prompt `embedding_model` tracking, startup mismatch detection, and a separate download opt-in flag. That was overbuilt for two realistic scenarios: (a) we test the default and decide to switch, (b) someone later spins up an English-only deployment. Both are handled by:

- `EMBEDDING_MODEL` env var (default `intfloat/multilingual-e5-small`).
- A small inline prefix-handling dict in the embedder (E5 needs prefix; BGE/MiniLM don't).
- The published image bundles only the default; setting `EMBEDDING_MODEL` to a non-default value implicitly opts into a first-boot HF download (no separate flag).
- After a model swap, run `scripts/reembed.py` to rewrite all vectors in-place; the corpus is small enough (~10k prompts × ~10 ms) that the migration window is minutes, not a maintenance event.

We do not persist a per-prompt model identifier. The single source of truth is the env var; mismatch means "re-embed now," not "gracefully coexist."

## Consequences

- Changing `EMBEDDING_MODEL` without running `reembed.py` produces silently degraded search quality (queries embedded with new model, stored vectors from old model). Document this in the deploy runbook.
- Operators who want a non-default model in production should rebuild the image with their model baked in, rather than relying on first-boot HF download — but the download path stays available as an escape hatch for experimentation.
