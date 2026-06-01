# Python 3.11 slim — small base, no shell tooling
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.hf-cache

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first so a code change doesn't reinstall everything
COPY requirements-runtime.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements-runtime.txt

# Source + corpus
COPY app/ ./app/
COPY data/ ./data/

# Bake the FAISS index into the image (also caches the embedding model in /app/.hf-cache),
# so container cold-start at runtime doesn't have to download anything.
RUN python -m app.ingest data/

# Non-root user for runtime
RUN useradd -m -u 10001 app && chown -R app:app /app
USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]