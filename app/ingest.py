"""Ingestion: load PDFs -> extract text -> sanitize -> chunk -> embed locally -> FAISS index.
Run offline: `python -m app.ingest data/`.

SECURITY NOTES
- Extracted PDF text is treated as UNTRUSTED — we never exec/eval it; we unicode-normalize
  and strip control characters before indexing, which defeats some homoglyph and
  zero-width-character injection tricks. (Defending the full indirect-injection threat is
  noted in THREAT_MODEL.md as the unfinished item.)
- Path is restricted to *.pdf directly under the docs root; symlinks are skipped to prevent
  reading files outside the intended directory.
- We never print chunk text — only filenames and counts — because logs are a PII surface.
- The persisted index goes to ./index/ which is git-ignored.
"""

from __future__ import annotations

import json
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

import faiss
import numpy as np
from pypdf import PdfReader

from app.config import settings
from app.embeddings import embed

INDEX_DIR = Path("index")
INDEX_FILE = INDEX_DIR / "faiss.bin"
CHUNKS_FILE = INDEX_DIR / "chunks.json"

CHUNK_SIZE = 2000      # characters; coarse but no extra tokenizer dependency
CHUNK_OVERLAP = 200    # carry-over so a sentence split across chunks is still findable
EMBED_BATCH = 64       # batch size for the embedding model


@dataclass
class Chunk:
    text: str
    source: str   # file name only, not the absolute path (don't leak filesystem layout)
    page: int     # 1-based page number for citations


def _sanitize(text: str) -> str:
    """Normalize and strip control chars from PDF-extracted text."""
    # NFKC collapses width variants, ligatures, and many homoglyph tricks into a canonical form.
    text = unicodedata.normalize("NFKC", text)
    # Keep printable + common whitespace; drop everything else (including zero-width chars).
    return "".join(c for c in text if c >= " " or c in "\n\t")


def _chunk_text(text: str, source: str, page: int) -> list[Chunk]:
    text = text.strip()
    if not text:
        return []
    chunks: list[Chunk] = []
    step = CHUNK_SIZE - CHUNK_OVERLAP
    start = 0
    while start < len(text):
        piece = text[start : start + CHUNK_SIZE].strip()
        if piece:
            chunks.append(Chunk(text=piece, source=source, page=page))
        if start + CHUNK_SIZE >= len(text):
            break
        start += step
    return chunks


def _load_pdf_chunks(pdf_path: Path) -> list[Chunk]:
    reader = PdfReader(str(pdf_path))
    chunks: list[Chunk] = []
    for page_num, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception:
            # A single malformed page shouldn't abort the whole ingest.
            raw = ""
        chunks.extend(_chunk_text(_sanitize(raw), source=pdf_path.name, page=page_num))
    return chunks


def build_index(docs_dir: str = "data/") -> None:
    docs_root = Path(docs_dir).resolve()
    if not docs_root.is_dir():
        raise SystemExit(f"docs dir not found: {docs_root}")

    # Top-level *.pdf only; skip symlinks so a symlinked file outside data/ can't be read.
    pdfs = sorted(p for p in docs_root.glob("*.pdf") if p.is_file() and not p.is_symlink())
    if not pdfs:
        raise SystemExit(f"no PDFs in {docs_root}")

    print(f"indexing {len(pdfs)} PDFs from {docs_root} with model={settings.embedding_model}")
    all_chunks: list[Chunk] = []
    for pdf in pdfs:
        added = _load_pdf_chunks(pdf)
        all_chunks.extend(added)
        print(f"  {pdf.name}: {len(added)} chunks")

    if not all_chunks:
        raise SystemExit("no extractable text found in PDFs")

    print(f"embedding {len(all_chunks)} chunks ...")
    batches = []
    for i in range(0, len(all_chunks), EMBED_BATCH):
        texts = [c.text for c in all_chunks[i : i + EMBED_BATCH]]
        batches.append(embed(texts))
    vectors = np.vstack(batches).astype(np.float32, copy=False)

    dim = vectors.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(vectors)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_FILE))
    with CHUNKS_FILE.open("w", encoding="utf-8") as f:
        json.dump([asdict(c) for c in all_chunks], f, ensure_ascii=False)

    print(f"indexed {len(all_chunks)} chunks from {len(pdfs)} files -> {INDEX_DIR}")


if __name__ == "__main__":
    build_index(sys.argv[1] if len(sys.argv) > 1 else "data/")
