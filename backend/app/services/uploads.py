"""Customer / agent file uploads: storage layout, content checks, signed URLs,
quotas and retention.

Layout:  ``uploads/<session_id>/<uuid><ext>``  (one directory per conversation,
so ownership is structural and a GDPR erase is a single directory removal).

Access: ``GET /uploads/<session_id>/<file>?exp=<unix>&sig=<hmac>``. The
signature covers the path and the expiry, so a leaked link stops working after
``upload_url_ttl_seconds`` and cannot be rewritten to point at another file.
Links stored in message history are re-signed every time history is served
(see ``resign_text``), so they never go stale for legitimate readers.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import shutil
import time

from app.config import settings
from app.logger import logger
from app.services import ratelimit

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "audio/webm", "audio/mp3", "audio/wav", "audio/mpeg", "audio/ogg", "audio/m4a",
    "application/pdf", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
ALLOWED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".webm", ".mp3", ".wav", ".mpeg", ".m4a", ".ogg",
    ".pdf", ".doc", ".docx",
}
INLINE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".webm", ".mp3", ".wav", ".mpeg", ".m4a", ".ogg"}
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
FILENAME_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}\.[A-Za-z0-9]{2,5}$")

# --- content sniffing ---------------------------------------------------------

def _looks_like(ext: str, data: bytes) -> bool:
    h = data[:16]
    if ext in (".jpg", ".jpeg"):
        return h.startswith(b"\xff\xd8\xff")
    if ext == ".png":
        return h.startswith(b"\x89PNG\r\n\x1a\n")
    if ext == ".gif":
        return h.startswith((b"GIF87a", b"GIF89a"))
    if ext == ".webp":
        return h[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if ext == ".pdf":
        return b"%PDF-" in data[:1024]
    if ext == ".wav":
        return h[:4] == b"RIFF" and data[8:12] == b"WAVE"
    if ext == ".ogg":
        return h.startswith(b"OggS")
    if ext == ".webm":
        return h.startswith(b"\x1a\x45\xdf\xa3")
    if ext in (".mp3", ".mpeg"):
        return h.startswith(b"ID3") or (len(h) > 1 and h[0] == 0xFF and (h[1] & 0xE0) == 0xE0)
    if ext == ".m4a":
        return data[4:8] == b"ftyp"
    if ext == ".docx":
        return h.startswith(b"PK\x03\x04")
    if ext == ".doc":
        return h.startswith(b"\xd0\xcf\x11\xe0")
    return False


def content_matches_extension(ext: str, data: bytes) -> bool:
    return bool(data) and _looks_like(ext, data)


# --- signed URLs --------------------------------------------------------------

def _key() -> bytes:
    return hashlib.sha256(b"wrennon-uploads-v1:" + settings.jwt_secret_key.encode()).digest()


def _sig(path_key: str, exp: int) -> str:
    return hmac.new(_key(), f"{path_key}|{exp}".encode(), hashlib.sha256).hexdigest()[:40]


def sign_path(path_key: str, ttl: int | None = None) -> str:
    exp = int(time.time()) + (ttl or settings.upload_url_ttl_seconds)
    return f"exp={exp}&sig={_sig(path_key, exp)}"


def verify_signature(path_key: str, exp: str | None, sig: str | None) -> bool:
    try:
        exp_i = int(exp or "")
    except ValueError:
        return False
    if exp_i < time.time() or not sig:
        return False
    return hmac.compare_digest(sig, _sig(path_key, exp_i))


_URL_RE = re.compile(
    r"(?P<base>https?://[^\s)\]\"'<>]*?)?/uploads/"
    r"(?P<key>(?:[A-Za-z0-9_-]{1,80}/)?[A-Za-z0-9_-]{8,64}\.[A-Za-z0-9]{2,5})"
    r"(?:\?[^\s)\]\"'<>]*)?"
)


def resign_text(text: str) -> str:
    """Replace every upload link in *text* with a freshly signed one."""
    if not text or "/uploads/" not in text:
        return text
    return _URL_RE.sub(lambda m: f"{m.group('base') or ''}/uploads/{m.group('key')}?{sign_path(m.group('key'))}", text)


def public_url(request_base: str, session_id: str, filename: str) -> str:
    base = (settings.public_base_url or request_base).rstrip("/")
    key = f"{session_id}/{filename}"
    return f"{base}/uploads/{key}?{sign_path(key)}"


# --- paths --------------------------------------------------------------------

def resolve_path(session_id: str | None, filename: str) -> str | None:
    """Absolute path of an upload, or None if the reference is malformed or
    escapes the upload directory. ``session_id=None`` addresses the legacy flat
    layout (files uploaded before per-session directories existed)."""
    if not FILENAME_RE.match(filename) or os.path.splitext(filename)[1].lower() not in ALLOWED_EXTENSIONS:
        return None
    if session_id is not None and not SESSION_ID_RE.match(session_id):
        return None
    base = os.path.realpath(UPLOAD_DIR)
    path = os.path.realpath(os.path.join(base, session_id or "", filename))
    return path if path.startswith(base + os.sep) else None


_REF_RE = re.compile(r"/uploads/(?:(?P<sid>[A-Za-z0-9_-]{1,80})/)?(?P<name>[A-Za-z0-9_-]{8,64}\.[A-Za-z0-9]{2,5})")


def resolve_own_upload(url: str, session_id: str) -> str | None:
    """Path of the file *url* points at, but only if it belongs to *session_id*
    (used before the server reads a file on a customer's behalf, so a customer
    cannot make the model describe or transcribe someone else's upload)."""
    m = _REF_RE.search(url or "")
    if not m or m.group("sid") != session_id:
        return None
    return resolve_path(session_id, m.group("name"))


# --- quotas -------------------------------------------------------------------

_disk_cache: tuple[float, int] = (0.0, 0)


def total_bytes_used(max_age: float = 60.0) -> int:
    global _disk_cache
    if time.time() - _disk_cache[0] < max_age:
        return _disk_cache[1]
    total = 0
    for root, _dirs, files in os.walk(UPLOAD_DIR):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    _disk_cache = (time.time(), total)
    return total


async def check_quota(session_id: str, client_ip: str, size: int) -> str | None:
    """Return an error message if this upload would exceed a quota, else None.
    Counters are only advanced for uploads that are about to be stored."""
    if total_bytes_used() + size > settings.upload_max_total_bytes:
        logger.error("Upload volume is at its global disk cap; rejecting uploads")
        return "Uploads are temporarily unavailable."
    if await ratelimit.hit(f"up_ip:{client_ip}", 3600) > settings.upload_max_per_ip_per_hour:
        return "Too many uploads from your network. Please try again later."
    if await ratelimit.hit(f"up_files:{session_id}", 86400) > settings.upload_max_files_per_session:
        return "Upload limit reached for this conversation."
    if await ratelimit.hit(f"up_bytes:{session_id}", 86400, size) > settings.upload_max_bytes_per_session:
        return "Upload size limit reached for this conversation."
    return None


def note_stored(size: int) -> None:
    global _disk_cache
    _disk_cache = (_disk_cache[0], _disk_cache[1] + size)


# --- retention ----------------------------------------------------------------

def purge_expired_uploads(retention_days: int | None = None) -> int:
    """Delete uploads older than the retention window; prune empty directories."""
    days = settings.upload_retention_days if retention_days is None else retention_days
    if days <= 0:
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for root, _dirs, files in os.walk(UPLOAD_DIR, topdown=False):
        for f in files:
            if f == ".gitkeep":
                continue
            p = os.path.join(root, f)
            try:
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)
                    removed += 1
            except OSError:
                pass
        if root != UPLOAD_DIR:
            try:
                os.rmdir(root)  # only succeeds when empty
            except OSError:
                pass
    if removed:
        logger.info(f"Upload retention: removed {removed} file(s) older than {days} days")
    return removed


def delete_session_uploads(session_id: str) -> None:
    if SESSION_ID_RE.match(session_id or ""):
        shutil.rmtree(os.path.join(UPLOAD_DIR, session_id), ignore_errors=True)
