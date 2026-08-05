"""Inbox processing pipeline — Phase 6 Stage 3.

Flow per run:

    fetch new messages (connector)
        → persist each (dedup by sender+subject+body)
            → for every UNPROCESSED row:
                match lead (matcher) → create ReplyAnalysis → run the AI
                reply classifier → apply CRM actions → mark processed.

Matched emails are fully processed (``processed=True`` with the matched
lead / originating message / analysis linked). Unmatched emails are left
``processed=False`` so an operator can review them in the unprocessed list.
"""
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models.incoming_email import IncomingEmail
from app.outreach.inbox import matcher
from app.outreach.inbox.connector import EmailInboxConnector, InboxMessage, get_inbox_connector


def persist_message(db: Session, msg: InboxMessage) -> Tuple[IncomingEmail, bool]:
    """Insert a fetched message unless it is a duplicate; returns (row, is_new)."""
    dup = (
        db.query(IncomingEmail)
        .filter(
            IncomingEmail.sender_email == (msg.sender_email or ""),
            IncomingEmail.subject == (msg.subject or ""),
            IncomingEmail.body == (msg.body or ""),
        )
        .first()
    )
    if dup is not None:
        return dup, False
    row = IncomingEmail(
        external_id=msg.external_id,
        sender_email=msg.sender_email,
        sender_name=msg.sender_name,
        subject=msg.subject,
        body=msg.body,
        received_at=msg.received_at or datetime.now(timezone.utc),
        processed=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, True


def process_inbox(
    db: Session, *, connector: Optional[EmailInboxConnector] = None
) -> dict:
    """Run the full inbox pipeline; returns a summary dict."""
    connector = connector or get_inbox_connector()
    summary = {
        "fetched": 0,
        "new_emails": 0,
        "duplicates": 0,
        "processed": 0,
        "matched": 0,
        "unmatched": 0,
        "analyzed": 0,
    }

    try:
        fetched = connector.fetch_new_messages()
    except Exception as exc:
        # Connector-level failure (e.g. IMAP down / auth error): surface the
        # error in the summary and stop — existing rows are untouched.
        summary["error"] = str(exc)
        return summary
    summary["fetched"] = len(fetched)
    for msg in fetched:
        row, is_new = persist_message(db, msg)
        if not is_new:
            summary["duplicates"] += 1
            continue
        summary["new_emails"] += 1

    unprocessed = (
        db.query(IncomingEmail)
        .filter(IncomingEmail.processed.is_(False))
        .order_by(IncomingEmail.received_at)
        .all()
    )
    for row in unprocessed:
        summary["processed"] += 1
        match = matcher.match_incoming_email(db, row)
        if match is None:
            summary["unmatched"] += 1
            continue  # left unprocessed for operator review

        lead, message = match
        try:
            from app.outreach import reply_ai

            analysis, _actions = reply_ai.analyze_reply(
                db,
                lead,
                reply_text=row.body or "",
                message_id=message.id if message is not None else None,
            )
            row.matched_lead_id = lead.id
            row.message_id = message.id if message is not None else None
            row.analysis_id = analysis.id
            row.processed = True
            db.add(row)
            db.commit()
            summary["matched"] += 1
            summary["analyzed"] += 1
        except Exception:
            # Per-email isolation: leave unprocessed; retried on the next run.
            db.rollback()
            continue

        if row.external_id:
            try:
                connector.mark_processed(row.external_id)
            except Exception:
                pass

    return summary
