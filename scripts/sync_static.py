#!/usr/bin/env python3
"""Keep backend/app/static (shipped in the Docker image) identical to frontend/.

frontend/ is the single source of truth. Never edit backend/app/static by hand.

    python scripts/sync_static.py           # copy frontend/ -> backend/app/static/
    python scripts/sync_static.py --check   # exit 1 if they differ (used in CI)

Only web assets are mirrored; *.py and dotfiles are never copied.
"""
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC, DST = ROOT / "frontend", ROOT / "backend" / "app" / "static"
SKIP_SUFFIXES = {".py", ".pyc"}


def files():
    for p in sorted(SRC.rglob("*")):
        if p.is_file() and p.suffix not in SKIP_SUFFIXES and not p.name.startswith("."):
            yield p.relative_to(SRC)


def main() -> int:
    check = "--check" in sys.argv
    drift = [rel for rel in files()
             if not (DST / rel).exists() or not filecmp.cmp(SRC / rel, DST / rel, shallow=False)]
    if check:
        if drift:
            print("static mirror is out of sync with frontend/:")
            for rel in drift:
                print("  ", rel)
            print("Run: python scripts/sync_static.py")
            return 1
        print("static mirror in sync")
        return 0
    for rel in drift:
        (DST / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SRC / rel, DST / rel)
        print("synced", rel)
    print(f"{len(drift)} file(s) synced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
