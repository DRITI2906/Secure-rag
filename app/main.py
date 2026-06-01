"""FastAPI entrypoint. Request flow for /query:

  auth -> rate limit -> input_guard -> retrieve -> in-scope gate
       -> Groq generate -> output_guard -> respond

SECURITY NOTES
- Auth required. Locally a static X-API-Key header (settings.api_key); in Azure prefer
  Easy Auth / Entra in front of the Container App. If neither is configured, startup logs
  a warning — the service still runs but is unauthenticated (intended for first-run dev
  only).
- Per-client rate limit via slowapi. Cost ceiling also enforced by max_output_tokens in
  llm.py and by Groq's own free-tier rate limit.
- Refusals are always safe and generic — internal guard category codes never reach the
  client text.
- OpenAPI / docs endpoints disabled to reduce attack surface.
- Logging uses logging_setup (hashed qid + metadata only). Raw query/answer never logged.
"""

from __future__ import annotations

import hmac
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings
from app.guards.input_guard import check_input
from app.guards.output_guard import filter_output
from app.llm import REFUSAL_NO_CONTEXT, generate
from app.logging_setup import configure_logging, hash_query, logger
from app.retrieval import is_in_scope, retrieve

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    if not settings.api_key and not settings.key_vault_uri:
        logger.warning(
            "API_KEY is empty and KEY_VAULT_URI is unset — /query is UNAUTHENTICATED. "
            "Set API_KEY in .env for local dev, or rely on Easy Auth in Azure."
        )
    yield


app = FastAPI(
    title="Secure RAG",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Constant-time API-key check. If no key is configured (settings.api_key empty),
    we allow — the startup warning already flagged this state."""
    expected = settings.api_key
    if not expected:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid api key")


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[str] = []
    blocked: bool = False
    reason: str | None = None


def _safe_refusal(reason: str) -> str:
    """Public-facing refusal text. Never echoes internal guard category codes."""
    if reason == "empty_query":
        return "Please ask a question."
    if reason == "too_long":
        return "Your question is too long. Please shorten it."
    return "I can't answer that."


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/query", response_model=QueryResponse, dependencies=[Depends(require_api_key)])
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
def query(request: Request, body: QueryRequest) -> QueryResponse:
    qid = hash_query(body.question)
    t0 = time.perf_counter()

    # 1. Input guard.
    g_in = check_input(body.question)
    if not g_in.allowed:
        logger.info(
            "qid=%s blocked=in_guard reason=%s latency_ms=%.0f",
            qid, g_in.reason, (time.perf_counter() - t0) * 1000,
        )
        return QueryResponse(
            answer=_safe_refusal(g_in.reason),
            blocked=True,
            reason=g_in.reason,
        )

    # 2. Retrieve.
    chunks = retrieve(body.question)

    # 3. Scope gate.
    if not is_in_scope(chunks):
        logger.info(
            "qid=%s blocked=scope latency_ms=%.0f",
            qid, (time.perf_counter() - t0) * 1000,
        )
        return QueryResponse(
            answer=REFUSAL_NO_CONTEXT,
            blocked=True,
            reason="out_of_scope",
        )

    # 4. Generate.
    raw_answer = generate(body.question, chunks)

    # 5. Output guard.
    allowed_sources = list({c.source for c in chunks})
    filtered = filter_output(raw_answer, allowed_sources)

    citations = sorted({f"{c.source} p.{c.page}" for c in chunks})

    logger.info(
        "qid=%s in_scope=1 blocked=%d guard_notes=%s latency_ms=%.0f",
        qid,
        int(filtered.blocked),
        filtered.notes or "-",
        (time.perf_counter() - t0) * 1000,
    )

    return QueryResponse(
        answer=filtered.text,
        citations=citations,
        blocked=filtered.blocked,
        reason=filtered.notes if filtered.blocked else None,
    )
