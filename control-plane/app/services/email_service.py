"""Bob Manager — Email service using aiosmtplib."""

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from app.config import settings

logger = logging.getLogger(__name__)


def _build_message(to: str, subject: str, html_body: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))
    return msg


async def _send(to: str, subject: str, html_body: str) -> bool:
    if not settings.smtp_host:
        logger.warning("SMTP not configured — skipping email to %s", to)
        return False
    try:
        msg = _build_message(to, subject, html_body)
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            start_tls=settings.smtp_tls,
        )
        logger.info("Email sent to %s — subject: %s", to, subject)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to)
        return False


async def notify_admin_new_trial(name: str, email: str, enterprise: str, role: str, purpose: str) -> bool:
    """Notify the admin that a new trial request was submitted."""
    if not settings.admin_email:
        logger.warning("ADMIN_EMAIL not configured — skipping admin notification")
        return False
    subject = f"[Bob Labs] New trial request from {name}"
    html = f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
      <h2 style="color: #7c3aed;">New Trial Request</h2>
      <table style="width: 100%; border-collapse: collapse;">
        <tr><td style="padding: 8px; font-weight: bold;">Name</td><td style="padding: 8px;">{name}</td></tr>
        <tr style="background: #f5f3ff;"><td style="padding: 8px; font-weight: bold;">Email</td><td style="padding: 8px;">{email}</td></tr>
        <tr><td style="padding: 8px; font-weight: bold;">Company</td><td style="padding: 8px;">{enterprise or '—'}</td></tr>
        <tr style="background: #f5f3ff;"><td style="padding: 8px; font-weight: bold;">Role</td><td style="padding: 8px;">{role or '—'}</td></tr>
        <tr><td style="padding: 8px; font-weight: bold;">Purpose</td><td style="padding: 8px;">{purpose or '—'}</td></tr>
      </table>
      <p style="margin-top: 24px;">
        Log in to the <a href="{settings.app_base_url}/admin" style="color: #7c3aed;">admin panel</a> to review and generate a token.
      </p>
    </div>
    """
    return await _send(settings.admin_email, subject, html)


async def send_token_to_user(email: str, token: str, label: str, expires_at: str) -> bool:
    """Send the generated access token to the user."""
    if not email:
        logger.warning("No email provided — skipping token delivery")
        return False
    subject = "[Bob Labs] Your access token"
    html = f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
      <h2 style="color: #7c3aed;">Your Bob Labs Access Token</h2>
      <p>Hello! Your access to Bob Labs has been approved{f' ({label})' if label else ''}.</p>
      <div style="background: #f5f3ff; border: 1px solid #ede9fe; border-radius: 8px; padding: 16px; margin: 16px 0; font-family: monospace; font-size: 14px; word-break: break-all;">
        {token}
      </div>
      <p><strong>Expires:</strong> {expires_at}</p>
      <p>
        Go to <a href="{settings.app_base_url}/login" style="color: #7c3aed;">{settings.app_base_url}/login</a>
        and paste your token to sign in.
      </p>
      <p style="color: #6b7280; font-size: 12px; margin-top: 24px;">
        Keep this token private. Do not share it with anyone.
      </p>
    </div>
    """
    return await _send(email, subject, html)


async def notify_admin_new_quote(
    name: str, email: str, company: str, phone: str, plan: str, description: str,
) -> bool:
    """Notify the admin that a new quote request was submitted."""
    if not settings.admin_email:
        logger.warning("ADMIN_EMAIL not configured — skipping quote notification")
        return False
    subject = f"[Bob Labs] New quote request from {name}"
    html = f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
      <h2 style="color: #7c3aed;">New Quote Request</h2>
      <table style="width: 100%; border-collapse: collapse;">
        <tr><td style="padding: 8px; font-weight: bold;">Name</td><td style="padding: 8px;">{name}</td></tr>
        <tr style="background: #f5f3ff;"><td style="padding: 8px; font-weight: bold;">Email</td><td style="padding: 8px;">{email}</td></tr>
        <tr><td style="padding: 8px; font-weight: bold;">Company</td><td style="padding: 8px;">{company or '—'}</td></tr>
        <tr style="background: #f5f3ff;"><td style="padding: 8px; font-weight: bold;">Phone</td><td style="padding: 8px;">{phone or '—'}</td></tr>
        <tr><td style="padding: 8px; font-weight: bold;">Plan</td><td style="padding: 8px;">{plan or '—'}</td></tr>
        <tr style="background: #f5f3ff;"><td style="padding: 8px; font-weight: bold;">Description</td><td style="padding: 8px;">{description or '—'}</td></tr>
      </table>
      <p style="margin-top: 24px;">
        Log in to the <a href="{settings.app_base_url}/admin" style="color: #7c3aed;">admin panel</a> to review this request.
      </p>
    </div>
    """
    return await _send(settings.admin_email, subject, html)
