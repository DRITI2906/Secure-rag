"""Retrieval + the out-of-scope gate. Embed the query, search FAISS, return top-k chunks
with scores. If the best score < MIN_RELEVANCE_SCORE, the caller MUST refuse the question
(out of scope) rather than hallucinate from general knowledge — this is a core AI-security
control."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import faiss

from app.config import settings
from app.embeddings import embed

# Must match the locations written by app/ingest.py. Kept inline rather than imported
# from ingest.py so retrieval doesn't drag pypdf into the API process at import time.
_INDEX_DIR = Path("index")
_INDEX_FILE = _INDEX_DIR / "faiss.bin"
_CHUNKS_FILE = _INDEX_DIR / "chunks.json"


@dataclass
class Chunk:
    text: str
    source: str
    page: int
    score: float


# Lazy-loaded singletons — the index can be tens of MB; load once per process.
_index: faiss.Index | None = None
_records: list[dict] | None = None


def _load() -> tuple[faiss.Index, list[dict]]:
    global _index, _records
    if _index is None or _records is None:
        if not _INDEX_FILE.exists() or not _CHUNKS_FILE.exists():
            raise RuntimeError(
                f"index not found in {_INDEX_DIR.resolve()}; "
                "run `python -m app.ingest data/` first"
            )
        _index = faiss.read_index(str(_INDEX_FILE))
        with _CHUNKS_FILE.open("r", encoding="utf-8") as f:
            _records = json.load(f)
    return _index, _records


def retrieve(query: str, top_k: int | None = None) -> list[Chunk]:
    """Return up to top_k most-similar chunks for `query`, ordered by descending score.
    Scores are cosine similarity (since embeddings are L2-normalized and the index is IP)."""
    query = query.strip()
    if not query:
        return []

    k = top_k if top_k is not None else settings.top_k
    index, records = _load()

    qv = embed([query])  # shape (1, dim), float32, L2-normalized
    scores, ids = index.search(qv, k)

    results: list[Chunk] = []
    for score, row_id in zip(scores[0].tolist(), ids[0].tolist()):
        # FAISS uses -1 for "no result" when the index has fewer than k vectors.
        if row_id < 0 or row_id >= len(records):
            continue
        rec = records[row_id]
        results.append(
            Chunk(text=rec["text"], source=rec["source"], page=rec["page"], score=float(score))
        )
    return results


def is_in_scope(chunks: list[Chunk]) -> bool:
    """True iff at least one chunk meets the relevance threshold. When this is False the
    caller MUST refuse the question rather than feed unrelated context to the LLM."""
    return any(c.score >= settings.min_relevance_score for c in chunks)
