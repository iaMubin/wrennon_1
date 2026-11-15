"""PII masking applied to every piece of text that leaves for an LLM provider
(and, in a lighter form, to log lines).

Coverage notes
--------------
* Bangladeshi mobile numbers (``01712345678``, ``01912-345678``,
  ``+8801712345678``, ``+880 1712-345678``) are matched BEFORE the generic
  card rule. Previously ``+880…`` (13 digits) was swallowed by the card regex
  and mislabelled ``[CARD HIDDEN]`` while ``017…`` was not masked at all.
* Addresses: the US street pattern is kept, and a Bangladeshi/South-Asian
  pattern (House/Road/Block/Sector/Ward/Village/Thana… including Bengali
  keywords) plus "my address is …" style triggers were added.
* Names: explicit triggers ("my name is", "name:", "আমার নাম") are masked
  regardless of case; ambiguous triggers ("I am", "this is") still require a
  capitalised name so ordinary sentences are not mangled.
* Passport / national-ID numbers (contextual, plus the common letter+7-8
  digit passport shape).

Masking is heuristic. It is defence in depth, not a guarantee, which is why
the callers also minimise *what* is sent (e.g. internal notes are never sent
to QA / copilot prompts).
"""

from __future__ import annotations

import re

_W = r"[\w\u0980-\u09ff\u200c\u200d]"          # word char incl. Bengali marks
_NAME_STOP = {"and", "but", "or", "i", "my", "is", "from", "the", "to", "in", "at", "for", "and,"}

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_BD_PHONE = re.compile(r"(?<!\d)(?:\+?880[-\s]?|0)1[3-9](?:[-\s]?\d){8}(?!\d)")
_CARD = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
_PHONE = re.compile(r"\b(?:\+\d{1,3}[- ]?)?\(?\d{3}\)?[- ]?\d{3}[- ]?\d{4}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_IPV4 = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")
_PASSWORD = re.compile(r"(?i)(password\s+is|pwd\s+is|password:|pwd:)\s+([^\s]+)")
_ID_CONTEXT = re.compile(
    r"(?i)(passport|nid|national\s+id|এনআইডি|জাতীয়\s+পরিচয়(?:পত্র)?|পাসপোর্ট)"
    r"(?:\s*(?:no\.?|number|num|#|নং|নম্বর))?\s*(?:is|:|-|হলো|হল)?\s*[A-Z]{0,2}[\d][\d -]{5,20}"
)
_PASSPORT_SHAPE = re.compile(r"\b[A-Z]{1,2}\d{7,8}\b")

_US_ADDRESS = re.compile(
    r"\b\d{1,5}\s+(?:[A-Z][a-z0-9]*\s+){1,3}(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Court|Ct|Way|Circle|Cir)\b(?:.*?,\s*[A-Z]{2}\s+\d{5})?",
    re.IGNORECASE,
)
_ADDR_KW = (
    r"house|holding|flat|plot|road|rd|block|sector|lane|ward|village|upazila|thana|mouza"
    r"|বাসা|বাড়ি|রোড|ব্লক|সড়ক|সেক্টর|গ্রাম|থানা|উপজেলা|ওয়ার্ড|ফ্ল্যাট"
)
_SA_ADDRESS = re.compile(
    rf"(?i)(?<!\w)(?:{_ADDR_KW})(?!\w)[^,\n]{{0,25}}(?:,\s*[^,\n]{{1,35}}){{1,5}}"
)
_ADDR_TRIGGER = re.compile(
    r"(?i)(?:my\s+address\s+is|address\s*[:\-]|deliver(?:y)?\s+(?:to|at)\s+address|ঠিকানা\s*[:\-]?|আমার\s+ঠিকানা)\s*[^\n]{3,160}"
)

_NAME_EXPLICIT = re.compile(
    rf"(?i)\b(my\s+name\s+is|name\s*:|amar\s+nam(?:\s+(?:holo|hocche))?|আমার\s+নাম(?:\s+(?:হলো|হল|হচ্ছে))?|নাম\s*:)\s+({_W}+)(?:\s+({_W}+))?"
)
_NAME_CONTEXT = re.compile(
    r"\b((?i:i\s+am|i'm|this\s+is|shipping\s+to|ship\s+to|deliver\s+to|account\s+under))\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b"
)

# Secrets that must never reach logs or a model.
_JWT = re.compile(r"eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]*")
_BEARER = re.compile(r"(?i)(bearer\s+)[\w.~+/=-]{12,}")
_QS_TOKEN = re.compile(r"(?i)([?&](?:token|access_token|api_key|key|email)=)[^&\s\"']+")
_API_KEY = re.compile(r"wk_live_[\w-]{8,}")


def _name_sub(m: re.Match) -> str:
    second = m.group(3)
    tail = f" {second}" if second and second.lower() in _NAME_STOP else ""
    return f"{m.group(1)} [NAME HIDDEN]{tail}"


def mask_pii(text: str, *, mask_ips: bool = True) -> str:
    """Mask PII in *text*. Order matters: more specific shapes first."""
    if not text:
        return text
    text = _EMAIL.sub("[EMAIL HIDDEN]", text)
    text = _ID_CONTEXT.sub(lambda m: f"{m.group(1)} [ID HIDDEN]", text)
    text = _BD_PHONE.sub("[PHONE HIDDEN]", text)
    text = _CARD.sub("[CARD HIDDEN]", text)
    text = _PHONE.sub("[PHONE HIDDEN]", text)
    text = _SSN.sub("[SSN HIDDEN]", text)
    if mask_ips:
        text = _IPV4.sub("[IP HIDDEN]", text)
    text = _PASSWORD.sub(r"\1 [PASSWORD HIDDEN]", text)
    text = _PASSPORT_SHAPE.sub("[ID HIDDEN]", text)
    text = _ADDR_TRIGGER.sub("[ADDRESS HIDDEN]", text)
    text = _US_ADDRESS.sub("[ADDRESS HIDDEN]", text)
    text = _SA_ADDRESS.sub("[ADDRESS HIDDEN]", text)
    text = _NAME_EXPLICIT.sub(_name_sub, text)
    text = _NAME_CONTEXT.sub(r"\1 [NAME HIDDEN]", text)
    return text


def redact_secrets(text: str) -> str:
    """Strip credentials (JWTs, bearer tokens, ?token= params, API keys)."""
    if not text:
        return text
    text = _JWT.sub("[JWT REDACTED]", text)
    text = _API_KEY.sub("[API KEY REDACTED]", text)
    text = _BEARER.sub(r"\1[REDACTED]", text)
    return _QS_TOKEN.sub(r"\1[REDACTED]", text)


def redact_for_log(text: str) -> str:
    """Log-line variant: secrets and personal data out, IPs kept (needed for ops)."""
    return mask_pii(redact_secrets(text), mask_ips=False)
