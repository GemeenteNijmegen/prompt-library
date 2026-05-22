# Embedding model: multilingual default, single env-var override, in-place re-embed

The server owns the embedding model for semantic search (caller-submitted vectors won't work — clients use different models and the vector spaces are incompatible). The default model is `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384-dim, ~220 MB), bundled into the published Docker image. Operators can swap models via the `EMBEDDING_MODEL` env var; switching triggers a one-shot `scripts/reembed.py` to rewrite vectors in-place.

## Why paraphrase-multilingual-MiniLM-L12-v2 as the default

Prompt content in this gallery is primarily Dutch with English technical terms mixed in. English-only models (e.g. `BAAI/bge-small-en-v1.5`) collapse on Dutch text.

The original design targeted `intfloat/multilingual-e5-small`, but fastembed 0.8.0 (the current stable release) does not include that model. Among the multilingual models fastembed actually ships at 384-dim, `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` is the best fit:

- 384-dim output, same vector space size as the original target
- ~220 MB — compact enough to bundle in the Docker image
- Symmetric model: no asymmetric query/passage prefixes required (unlike E5)
- Well-tested on Dutch and cross-lingual retrieval tasks

If a future fastembed release adds `intfloat/multilingual-e5-small` or `intfloat/multilingual-e5-base`, switching is a one-line config change plus `scripts/reembed.py`.

## Why single env var + closed-ish behavior, not a full registry

An earlier sketch had a closed model registry with metadata, per-prompt `embedding_model` tracking, startup mismatch detection, and a separate download opt-in flag. That was overbuilt for two realistic scenarios: (a) we test the default and decide to switch, (b) someone later spins up an English-only deployment. Both are handled by:

- `EMBEDDING_MODEL` env var (default `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`).
- A small inline prefix-handling dict in the embedder (E5-style models need a prefix; MiniLM and BGE don't).
- The published image bundles only the default; setting `EMBEDDING_MODEL` to a non-default value implicitly opts into a first-boot HF download (no separate flag).
- After a model swap, run `scripts/reembed.py` to rewrite all vectors in-place; the corpus is small enough (~10k prompts × ~10 ms) that the migration window is minutes, not a maintenance event.

We do not persist a per-prompt model identifier. The single source of truth is the env var; mismatch means "re-embed now," not "gracefully coexist."

## Consequences

- Changing `EMBEDDING_MODEL` without running `reembed.py` produces silently degraded search quality (queries embedded with new model, stored vectors from old model). Document this in the deploy runbook.
- Operators who want a non-default model in production should rebuild the image with their model baked in, rather than relying on first-boot HF download — but the download path stays available as an escape hatch for experimentation.
