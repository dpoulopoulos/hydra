import smtplib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from emails.message import Message
from jinja2 import Template

from app.core.config import settings
from app.logging import get_logger

logger = get_logger(__name__)

# What a provider that is down, rate limiting us or misaddressed looks like:
# an HTTP error from Resend, an SMTP refusal, or a socket that never connected.
# Anything else is a bug in our own code and has no business being logged as a
# delivery problem.
DELIVERY_ERRORS = (httpx.HTTPError, smtplib.SMTPException, OSError)


@dataclass
class EmailData:
    html_content: str
    subject: str


def _render_email_template(*, template_name: str, context: dict[str, Any]) -> str:
    template_str = (Path(__file__).parent.parent / "templates" / "email" / template_name).read_text()
    template: Template = Template(template_str)
    return template.render(context)


# Fixed width, so the mask says nothing about how long the local part is.
MASK = "*" * 5


def mask_email(email: str) -> str:
    """Hide most of an email address, leaving it recognisable to its owner.

    Used where an address has to be shown to somebody who may not own it, so
    the reader can tell whether it is theirs without learning what to type
    somewhere else.

    Args:
        email: The address to mask.

    Returns:
        The first character of the local part, a fixed mask, and the domain.
    """
    local, _, domain = email.partition("@")

    if not domain:
        return MASK

    return f"{local[:1] if len(local) > 1 else ''}{MASK}@{domain}"


def generate_new_account_email(username: str) -> EmailData:
    """Generate a 'new account' email.

    The message welcomes the user and links to the front end. It carries no credentials.

    Args:
        username: Username for the new account.

    Returns:
        EmailData object with HTML content and subject.
    """
    subject = f"Welcome to {settings.PROJECT_NAME}!"
    html_content = _render_email_template(
        template_name="new_account.html",
        context={
            "project_name": settings.PROJECT_NAME,
            "username": username,
            "link": settings.FRONTEND_HOST,
            "assets_base_url": settings.assets_base_url,
        },
    )
    return EmailData(html_content=html_content, subject=subject)


def generate_password_reset_email(email: str, token: str) -> EmailData:
    """Generate a password reset email.

    Args:
        email: Recipient email address.
        token: The password reset token.

    Returns:
        EmailData object with HTML content and subject.
    """
    subject = f"Password Reset - {settings.PROJECT_NAME}"
    html_content = _render_email_template(
        template_name="password_reset.html",
        context={
            "project_name": settings.PROJECT_NAME,
            "email": email,
            "token": token,
            "link": f"{settings.FRONTEND_HOST}/reset-password?token={token}",
            "assets_base_url": settings.assets_base_url,
        },
    )
    return EmailData(html_content=html_content, subject=subject)


def generate_email_verification_email(email: str, token: str) -> EmailData:
    """Generate an email verification email.

    Args:
        email: Recipient email address.
        token: The email verification token.

    Returns:
        EmailData object with HTML content and subject.
    """
    subject = f"Verify Your Email - {settings.PROJECT_NAME}"
    html_content = _render_email_template(
        template_name="email_verification.html",
        context={
            "project_name": settings.PROJECT_NAME,
            "email": email,
            "token": token,
            "link": f"{settings.FRONTEND_HOST}/verify-email?token={token}",
            "assets_base_url": settings.assets_base_url,
        },
    )
    return EmailData(html_content=html_content, subject=subject)


def _send_email_via_resend(
    *,
    email_to: str,
    subject: str,
    html_content: str,
) -> None:
    """Post one email to the Resend API.

    Some hosts block outgoing SMTP, so mail has to leave over HTTPS instead.

    Args:
        email_to: The recipient's email address.
        subject: The subject of the email.
        html_content: The HTML content of the email.

    Raises:
        HTTPStatusError: If Resend rejects the request.
    """
    # emails_enabled already implies both, but it is not something mypy can narrow.
    assert settings.RESEND_API_KEY is not None
    assert settings.EMAILS_FROM_EMAIL is not None

    # Resend takes the sender as one header value, so the display name, when
    # there is one, is folded into it the way a mail client would write it.
    mail_from = (
        f"{settings.EMAILS_FROM_NAME} <{settings.EMAILS_FROM_EMAIL}>"
        if settings.EMAILS_FROM_NAME
        else settings.EMAILS_FROM_EMAIL
    )

    response = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
        json={"from": mail_from, "to": [email_to], "subject": subject, "html": html_content},
        timeout=10,
    )
    response.raise_for_status()


def send_email(
    *,
    email_to: str,
    subject: str,
    html_content: str,
) -> None:
    """Send an email to a recipient.

    Args:
        email_to: The recipient's email address.
        subject: The subject of the email.
        html_content: The HTML content of the email.

    Raises:
        AssertionError: If email sending is not enabled in the settings.
        HTTPStatusError: If Resend rejects the request.
        SMTPException: If the mail server did not accept the message.
    """
    assert settings.emails_enabled, "no provided configuration for email variables"
    # emails_enabled already implies this, but it is not something mypy can narrow.
    assert settings.EMAILS_FROM_EMAIL is not None

    if settings.EMAIL_PROVIDER == "resend":
        _send_email_via_resend(email_to=email_to, subject=subject, html_content=html_content)
        return

    message = Message(
        subject=subject,
        html=html_content,
        mail_from=(settings.EMAILS_FROM_NAME, settings.EMAILS_FROM_EMAIL),
    )

    smtp_options = {"host": settings.SMTP_HOST, "port": settings.SMTP_PORT}

    if settings.SMTP_TLS:
        smtp_options["tls"] = True
    elif settings.SMTP_SSL:
        smtp_options["ssl"] = True
    if settings.SMTP_USER:
        smtp_options["user"] = settings.SMTP_USER
    if settings.SMTP_PASSWORD:
        smtp_options["password"] = settings.SMTP_PASSWORD

    response = message.send(to=email_to, smtp=smtp_options)

    # The library answers a refused or unreachable server with an unsuccessful
    # response rather than an exception, so a message that never left would
    # otherwise be indistinguishable from a delivered one.
    if not response.success:
        raise response.error or smtplib.SMTPException(
            f"The mail server did not accept the message: {response.status_code} {response.status_text}"
        )


def generate_household_invite_email(email: str, token: str, household_name: str, inviter_name: str) -> EmailData:
    """Generate a household invitation email.

    Args:
        email: Recipient email address.
        token: The invite token.
        household_name: The name of the household they are being invited to.
        inviter_name: Who is inviting them.

    Returns:
        EmailData object with HTML content and subject.
    """
    # The household name is whatever the owner chose, and often already ends
    # in "household", so the subject must not add the word itself.
    subject = f"You have been invited to {household_name} - {settings.PROJECT_NAME}"
    html_content = _render_email_template(
        template_name="household_invite.html",
        context={
            "project_name": settings.PROJECT_NAME,
            "email": email,
            "token": token,
            "household_name": household_name,
            "inviter_name": inviter_name,
            "expire_hours": settings.HOUSEHOLD_INVITE_TOKEN_EXPIRE_HOURS,
            "link": f"{settings.FRONTEND_HOST}/join-household?token={token}",
            "assets_base_url": settings.assets_base_url,
        },
    )
    return EmailData(html_content=html_content, subject=subject)
