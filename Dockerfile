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

# Production image with model weights bundled — avoids HuggingFace download at boot
FROM app AS app-with-embeddings

ARG EMBEDDING_MODEL=intfloat/multilingual-e5-small
ENV FASTEMBED_CACHE_PATH=/root/.cache/fastembed
ENV EMBEDDING_MODEL=${EMBEDDING_MODEL}

RUN python3 -c "from fastembed import TextEmbedding; list(TextEmbedding('${EMBEDDING_MODEL}').embed(['warmup']))"
