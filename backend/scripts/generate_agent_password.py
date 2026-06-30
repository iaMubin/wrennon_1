"""
Run once, by hand, to generate the value for AGENT_PASSWORD_HASH in .env.

    python scripts/generate_agent_password.py

It will prompt for a password (input hidden) and print the hash to
paste into .env. The plain password is never written anywhere by this
script — only the hash.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.auth.security import hash_password  # noqa: E402


def main() -> None:
    password = getpass.getpass("Enter the agent password to hash: ")
    confirm = getpass.getpass("Confirm: ")
    if password != confirm:
        print("Passwords did not match. Run the script again.")
        return

    print("\nAdd this line to your .env file:\n")
    print(f"AGENT_PASSWORD_HASH={hash_password(password)}")


if __name__ == "__main__":
    main()
