"""Input guard — runs BEFORE retrieval/generation. Layered and fail-closed.

Layers, cheap to expensive (short-circuit on first refusal):
1. Empty / whitespace-only check.
2. Length cap (settings.max_query_chars) — bounds cost and parser load.
3. Control-character ratio — catches obfuscation tricks (zero-width chars, RLO/LRO marks,
   bell/null/etc.). Sanitized text from ingestion never has these; legitimate user queries
   shouldn't either.
4. Regex heuristics — common direct-injection / system-prompt-extraction patterns. Cheap,
   high-precision, low-recall (real attackers paraphrase; that's what layer 5 catches).
5. Model-based moderation — Llama Prompt Guard 2 (86M) via Groq. This is a specialized
   prompt-injection classifier that returns p(injection) as a float; we refuse when that
   probability exceeds settings.prompt_guard_threshold. Fail-CLOSED on errors / unparseable
   output. Note Prompt Guard 2 does NOT classify unsafe topics (e.g. "how to build a bomb")
   as injection — that axis is handled by the out-of-scope grounding gate in retrieval,
   which refuses anything not in the corpus.

The `reason` field never echoes the raw query; it's a short category code suitable for
logs (the redaction policy in logging_setup keeps queries out of logs entirely).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from groq import Groq

from app.config import settings
from app.secrets import get_groq_api_key


@dataclass
class GuardResult:
    allowed: bool
    reason: str = ""


# Compiled once. These target common English-language jailbreak / system-prompt-extraction
# attempts. They are deliberately not exhaustive — real attackers paraphrase — so this layer
# is for cheap, high-precision short-circuit refusals. Layer 5 (Llama Guard) is the catchall.
_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore (?:all |the )?(?:previous|prior|above|earlier) (?:instructions|context|prompts|rules)",
        r"disregard (?:all |the )?(?:previous|prior|above|earlier) (?:instructions|context|prompts|rules)",
        r"forget (?:everything|all|previous|prior|the above)",
        r"(?:reveal|print|show|repeat|tell me) (?:the |your |full )?(?:system|developer|original|initial) (?:prompt|instructions|message|rules)",
        r"what (?:are|were) your (?:instructions|system prompt|original instructions)",
        r"jailbreak",
        r"developer mode",
        r"override (?:your |the |all )?(?:safety|rules|instructions|guidelines)",
        r"act as (?:if you are )?(?:an? )?(?:unrestricted|uncensored|jailbroken)",
        r"do anything now",
        r"<\s*system\s*>",
        r"\[\s*system\s*\]",
    )
]

# Sanitized text shouldn't contain any control chars; allow a small budget for unusual but
# legitimate punctuation that may decompose oddly under NFKC.
_MAX_CONTROL_RATIO = 0.05


_guard_client: Groq | None = None


def _client() -> Groq:
    global _guard_client
    if _guard_client is None:
        _guard_client = Groq(api_key=get_groq_api_key())
    return _guard_client


def _control_ratio(s: str) -> float:
    if not s:
        return 0.0
    bad = sum(1 for c in s if c < " " and c not in "\n\t")
    return bad / len(s)


def _moderate(query: str) -> GuardResult:
    """Call Llama Prompt Guard 2 via Groq. The model returns p(injection) as a string-
    encoded float. Fail-CLOSED on errors or unparseable output."""
    try:
        resp = _client().chat.completions.create(
            model=settings.groq_guard_model,
            messages=[{"role": "user", "content": query}],
            max_tokens=20,
            temperature=0,
        )
    except Exception:
        return GuardResult(False, "moderation:unavailable")

    raw = (resp.choices[0].message.content or "").strip()
    try:
        p_injection = float(raw)
    except ValueError:
        return GuardResult(False, "moderation:unparseable")

    if p_injection >= settings.prompt_guard_threshold:
        return GuardResult(False, "moderation:injection")
    return GuardResult(True)


def check_input(query: str) -> GuardResult:
    if not query or not query.strip():
        return GuardResult(False, "empty_query")

    q = query.strip()

    if len(q) > settings.max_query_chars:
        return GuardResult(False, "too_long")

    if _control_ratio(q) > _MAX_CONTROL_RATIO:
        return GuardResult(False, "suspicious_control_chars")

    for pat in _INJECTION_PATTERNS:
        if pat.search(q):
            return GuardResult(False, "injection_pattern")

    return _moderate(q)
