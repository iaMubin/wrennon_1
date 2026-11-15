"""Checks applied to auto-drafted knowledge-base articles before they can be
published into the vector store.

Auto-drafted articles are distilled from real conversations, then retrieved by
the AI agent for every future customer. That is both a PII-leak path and a
persistent prompt-injection ("RAG poisoning") path, so a draft must pass these
checks AND a named reviewer must approve the exact text that gets indexed.
"""

from __future__ import annotations

import re

from app.security.pii import mask_pii
from app.security.sanitize import neutralize_markers

MAX_ARTICLE_CHARS = 4000
MAX_QUESTION_CHARS = 300

_INJECTION = re.compile(
    r"(?i)(ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier)\s+(?:instructions?|rules?|prompts?)"
    r"|disregard\s+(?:the\s+)?(?:system|previous|above)"
    r"|you\s+are\s+now\b|act\s+as\s+(?:an?\s+)?(?:admin|system|developer)"
    r"|(?:reveal|print|show|repeat)\s+(?:your\s+|the\s+)?(?:system\s+)?(?:prompt|instructions)"
    r"|\bsystem\s*prompt\b|<\|[a-z_]+\|>|\[/?INST\]|<<\s*SYS\s*>>"
    r"|always\s+(?:approve|issue|grant)\s+(?:the\s+)?(?:refund|discount|request)s?"
    r"|(?:process|issue)\s+(?:a\s+)?refund\s+without|\bhttps?://\S*(?:\.zip|\.exe|\.scr)\b)"
)
_PII_LABEL = re.compile(r"\[(EMAIL|PHONE|CARD|SSN|IP|ADDRESS|NAME|ID|PASSWORD) HIDDEN\]")


def clean_draft(text: str, max_len: int = MAX_ARTICLE_CHARS) -> str:
    """Mask PII and neutralise markers in model-drafted text before it is stored."""
    return neutralize_markers(mask_pii((text or "")[:max_len]))


def review_findings(text: str) -> list[str]:
    """Reasons this text must not be published as-is (empty list = clean)."""
    findings: list[str] = []
    masked = mask_pii(text)
    if masked != text:
        kinds = sorted(set(_PII_LABEL.findall(masked)))
        findings.append("contains personal data (" + ", ".join(k.lower() for k in kinds) + ")")
    if neutralize_markers(text) != text:
        findings.append("contains prompt-control markers")
    if _INJECTION.search(text):
        findings.append("contains instruction-like text aimed at the AI")
    if len(text) > MAX_ARTICLE_CHARS:
        findings.append(f"longer than {MAX_ARTICLE_CHARS} characters")
    return findings
