"""Local embeddings via sentence-transformers. Runs in-process so the corpus is never
sent to a third party during ingestion. The same model is used for query embedding,
which is required: query and document vectors must come from the same space."""

from __future__ import annotations

import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import settings

# Module-level singleton. The model is ~130 MB on disk and takes ~1-2 s to load;
# pay that cost exactly once per process. Lazy-loaded so importing this module is
# cheap (matters for tests and CLI tools that don't actually embed).
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(settings.embedding_model)
    return _model


def embed(texts: list[str]) -> np.ndarray:
    """Embed a batch of texts and return float32 vectors of shape (N, dim), L2-normalized.

    Normalization is deliberate: with FAISS IndexFlatIP (inner product) and unit-norm
    vectors, the inner product equals cosine similarity. That keeps retrieval math simple
    and avoids a per-query normalization step at search time.

    NOTE: bge-small-en-v1.5 does NOT need the legacy "Represent this sentence for
    searching relevant passages:" query prefix — the v1.5 release dropped that
    requirement. Do not re-add it; it slightly degrades quality.
    """
    if not texts:
        dim = _get_model().get_sentence_embedding_dimension()
        return np.empty((0, dim), dtype=np.float32)

    vectors = _get_model().encode(
        texts,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    # sentence-transformers may return float32 already, but be explicit so downstream
    # FAISS code never sees float64 (which IndexFlatIP doesn't accept).
    return vectors.astype(np.float32, copy=False)
