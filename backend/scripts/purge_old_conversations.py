"""
Data-retention purge script.

Supports the "storage limitation" principle (GDPR Art. 5(1)(e)) and the
general CCPA expectation that personal data isn't kept indefinitely:
deletes conversations (and their messages, scorecards, and knowledge-gap
records) older than a configurable retention window, once they're
resolved.

Only RESOLVED conversations are eligible — anything still open or
pending human handoff is left alone regardless of age, since deleting
an in-progress conversation could destroy data a customer or agent is
actively relying on.

There's no background scheduler wired into the app for this (adding one
would be a bigger, riskier change than this task called for) — run it
manually or wire it into whatever your deployment already uses for
scheduled jobs (a Render Cron Job, a GitHub Actions scheduled workflow,
a plain host crontab, etc).

Usage:
    python scripts/purge_old_conversations.py --days 365
        Dry run (default) — reports what WOULD be deleted, deletes nothing.

    python scripts/purge_old_conversations.py --days 365 --confirm
        Actually deletes.
"""

import argparse
import datetime
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.db.models import Conversation, Message, AnalyticsScorecard, KnowledgeGap, AuditLog


def purge(days: int, confirm: bool) -> None:
    cutoff = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(days=days)
    db = SessionLocal()
    try:
        candidates = (
            db.query(Conversation)
            .filter(Conversation.resolved == True)  # noqa: E712
            .filter(Conversation.updated_at < cutoff)
            .all()
        )

        if not candidates:
            print(f"No resolved conversations older than {days} days ({cutoff.isoformat()}). Nothing to do.")
            return

        print(f"Found {len(candidates)} resolved conversation(s) older than {days} days:")
        for c in candidates[:20]:
            print(f"  - {c.id}  (email={c.customer_email or 'n/a'}, updated_at={c.updated_at.isoformat()})")
        if len(candidates) > 20:
            print(f"  ... and {len(candidates) - 20} more")

        if not confirm:
            print("\nDry run only — nothing deleted. Re-run with --confirm to actually purge.")
            return

        conversation_ids = [c.id for c in candidates]

        db.query(Message).filter(Message.conversation_id.in_(conversation_ids)).delete(synchronize_session=False)
        db.query(AnalyticsScorecard).filter(AnalyticsScorecard.conversation_id.in_(conversation_ids)).delete(synchronize_session=False)
        db.query(KnowledgeGap).filter(KnowledgeGap.conversation_id.in_(conversation_ids)).delete(synchronize_session=False)
        db.query(Conversation).filter(Conversation.id.in_(conversation_ids)).delete(synchronize_session=False)

        db.add(AuditLog(
            actor_username="system:retention-job",
            action="purge_old_conversations",
            details=f"{len(conversation_ids)} conversation(s) older than {days} days permanently purged",
        ))
        db.commit()
        print(f"\nDeleted {len(conversation_ids)} conversation(s) and their associated records.")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=365, help="Retention window in days (default: 365)")
    parser.add_argument("--confirm", action="store_true", help="Actually delete. Without this flag, it's a dry run.")
    args = parser.parse_args()
    purge(args.days, args.confirm)
