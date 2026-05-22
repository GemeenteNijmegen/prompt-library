FROM python:3.11-slim AS app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY migrations/ migrations/
COPY src/ src/
COPY scripts/ scripts/

RUN mkdir -p data uploads

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn src.main:app --host 0.0.0.0 --port 8000"]

# Image with real ML embeddings. Model weights are NOT baked in; they are
# downloaded on first start and cached in the fastembed_cache Docker volume
# (see docker-compose.yml). Rebuilds are fast; only the first ever start
# downloads from the network.
FROM app AS app-with-embeddings

ARG EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
ENV FASTEMBED_CACHE_PATH=/cache/fastembed
ENV EMBEDDING_MODEL=${EMBEDDING_MODEL}
