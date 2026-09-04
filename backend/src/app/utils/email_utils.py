from dataclasses import dataclass
from pathlib import Path
from typing import Any

from emails.message import Message
from jinja2 import Template

from app.core.config import settings


@dataclass
class EmailData:
    html_content: str
    subject: str


def _render_email_template(*, template_name: str, context: dict[str, Any]) -> str:
    template_str = (Path(__file__).parent.parent / "templates" / "email" / template_name).read_text()
    template: Template = Template(template_str)
    return template.render(context)


def generate_new_account_email(username: str) -> EmailData:
    """Generate a 'new account' email.

    SECURITY WARNING: This function sends the plain text password via email,
    which is a security risk. Emails are typically:
    - Transmitted over potentially unencrypted channels
    - Stored in plaintext on email servers
    - Accessible to email administrators
    - Susceptible to interception

    Consider using a password reset link instead,
    allowing users to set their own password on first login.

    Args:
        email_to: Recipient email address.
        username: Username for the new account.
        password: Plain text password (SECURITY RISK).

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
    """
    assert settings.emails_enabled, "no provided configuration for email variables"
    # emails_enabled already implies this, but it is not something mypy can narrow.
    assert settings.EMAILS_FROM_EMAIL is not None

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

    message.send(to=email_to, smtp=smtp_options)


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
