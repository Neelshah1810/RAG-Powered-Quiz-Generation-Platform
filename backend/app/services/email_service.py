"""
Academix AI — Transactional email delivery.

PRD §11 pairs several Notice Board triggers with an email copy, and PRD §7
names "a transactional email provider (e.g. SendGrid/SES) via Celery worker".
Celery and Redis are explicitly out of scope for this build, so delivery here
is a direct SMTP send performed on a background task.

**When no SMTP host is configured this module is a deliberate no-op**: it logs
what it *would* have sent and returns. That is a conscious choice over faking
success — the in-app Notice Board is the surface the product depends on, and
silently pretending mail was delivered would be worse than not sending it.

To turn delivery on, set in backend/.env:

    SMTP_HOST=smtp.your-provider.com
    SMTP_PORT=587
    SMTP_USER=...
    SMTP_PASSWORD=...
    SMTP_FROM="Academix AI <noreply@your-college.edu>"

Without a queue there is no retry-on-failure, so a send that fails is logged
and dropped. Restoring the PRD's reliability guarantee means reinstating the
Celery worker.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Optional

from app.database import get_supabase_admin

logger = logging.getLogger(__name__)


def _smtp_config() -> Optional[dict]:
    """SMTP settings from the environment, or None when unconfigured."""
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ.get("SMTP_USER", "").strip(),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "sender": os.environ.get("SMTP_FROM", "").strip()
        or os.environ.get("SMTP_USER", "").strip(),
        "use_tls": os.environ.get("SMTP_USE_TLS", "true").lower() != "false",
    }


def is_configured() -> bool:
    return _smtp_config() is not None


def _resolve_recipients(notice: dict) -> list[str]:
    """
    Work out who should receive an email copy of a notice.

    Mirrors the visibility rules in `notice_service.list_notices` so the email
    audience can never be wider than the in-app audience.
    """
    supabase = get_supabase_admin()

    if notice.get("target_user_id"):
        result = (
            supabase.table("profiles")
            .select("email")
            .eq("id", notice["target_user_id"])
            .execute()
        )
        return [r["email"] for r in (result.data or []) if r.get("email")]

    if notice.get("course_id"):
        enrollments = (
            supabase.table("enrollments")
            .select("user_id")
            .eq("course_id", notice["course_id"])
            .execute()
        )
        user_ids = [r["user_id"] for r in (enrollments.data or [])]
        if not user_ids:
            return []
        profiles = (
            supabase.table("profiles").select("email").in_("id", user_ids).execute()
        )
        return [r["email"] for r in (profiles.data or []) if r.get("email")]

    roles = notice.get("target_roles") or ["admin", "teacher", "student"]
    profiles = supabase.table("profiles").select("email").in_("role", roles).execute()
    return [r["email"] for r in (profiles.data or []) if r.get("email")]


async def deliver_notice(notice: dict) -> int:
    """
    Email a notice to everyone entitled to see it.

    Returns the number of recipients sent to (0 when email is off).
    """
    recipients = _resolve_recipients(notice)
    if not recipients:
        return 0

    subject = f"[Academix AI] {notice.get('title', 'Notice')}"
    body = (
        f"{notice.get('title', '')}\n\n"
        f"{notice.get('body', '')}\n\n"
        f"--\nYou are receiving this because you are a member of this course or "
        f"institute on Academix AI. Sign in to see the full Notice Board."
    )

    return await send_email(recipients, subject, body)


async def send_email(recipients: list[str], subject: str, body: str) -> int:
    """
    Send one message to many recipients (BCC, so addresses are not disclosed).

    Never raises: callers are notification paths whose primary action has
    already succeeded.
    """
    recipients = [r for r in dict.fromkeys(recipients) if r and "@" in r]
    if not recipients:
        return 0

    config = _smtp_config()
    if config is None:
        logger.info(
            "Email not configured — skipping %r to %d recipient(s). "
            "Set SMTP_HOST in backend/.env to enable delivery.",
            subject,
            len(recipients),
        )
        return 0

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config["sender"] or "noreply@academix.local"
    message["To"] = config["sender"] or "undisclosed-recipients:;"
    message["Bcc"] = ", ".join(recipients)
    message.set_content(body)

    try:
        with smtplib.SMTP(config["host"], config["port"], timeout=20) as server:
            if config["use_tls"]:
                server.starttls()
            if config["user"]:
                server.login(config["user"], config["password"])
            server.send_message(message)
    except Exception as exc:
        # No queue means no retry. Log loudly enough to be noticed in ops.
        logger.error("SMTP delivery of %r failed for %d recipient(s): %s",
                     subject, len(recipients), exc)
        return 0

    logger.info("Emailed %r to %d recipient(s)", subject, len(recipients))
    return len(recipients)
