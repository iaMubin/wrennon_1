"""Delete uploads older than the retention window (default UPLOAD_RETENTION_DAYS).

Usage:  python scripts/purge_old_uploads.py [days]
"""
import sys

from app.services.uploads import purge_expired_uploads

if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else None
    print(f"removed {purge_expired_uploads(days)} file(s)")
