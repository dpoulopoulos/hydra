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

# The HTTP statuses a mail API answers a request it will not accept with, minus
# the ones that are not about the message. A rate limit clears and a request the
# provider timed out was never read, so both say "not now" rather than "not
# ever"; 401 and 403 are our credential, which somebody can rotate while the
# queue waits.
_RETRYABLE_HTTP_STATUSES = frozenset({401, 403, 408, 429})

# The 5xx replies an SMTP server refuses our credential with, rather than the
# message: authentication required, failed, or with a mechanism too weak
# (RFC 4954). The message was never offered, and the setting can still be fixed.
_CREDENTIAL_SMTP_CODES = frozenset({530, 534, 535, 538})


def is_permanent_rejection(error: Exception) -> bool:
    """Say whether sending the same message again could ever go differently.

    A provider that is down, throttling us or unreachable refuses mail it
    would take later, and the message is worth another attempt. A provider
    that rejected the message itself - an address that does not exist, a
    payload it will not accept - will reject it again just as fast, and
    retrying only keeps the row alive for hours saying so.

    Anything we do not recognise counts as temporary: the cost of retrying a
    message that was never going to leave is an hour of a queue row, and the
    cost of giving up on one that would have left is somebody's mail.

    Args:
        error: What the provider, the library or the network raised.

    Returns:
        True if the message cannot be delivered by trying it again.
    """
    if isinstance(error, smtplib.SMTPAuthenticationError):
        # Our own credential, not this message: every queued row would fail
        # alike, and rotating the key makes all of them sendable again.
        return False

    if isinstance(error, smtplib.SMTPSenderRefused):
        # The address we send *from*, which is one setting for the whole
        # queue: a relay that will not carry us, or a domain nobody has
        # verified yet, refuses MAIL FROM before the message is offered.
        return False

    if isinstance(error, (smtplib.SMTPConnectError, smtplib.SMTPHeloError)):
        # The refusal came before the conversation reached our message: a
        # server that will not take the connection, or will not answer the
        # greeting, has said nothing about what we were about to send.
        return False

    if isinstance(error, smtplib.SMTPRecipientsRefused):
        # Every address has to be beyond hope: one that was only refused for
        # now is a message that still has somewhere to go.
        return bool(error.recipients) and all(_is_permanent_smtp_code(code) for code, _ in error.recipients.values())

    if isinstance(error, smtplib.SMTPResponseException):
        return _is_permanent_smtp_code(error.smtp_code)

    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        return 400 <= status < 500 and status not in _RETRYABLE_HTTP_STATUSES

    # A transport error, a socket that never connected, or a bug of our own:
    # nothing was said about the message.
    return False


def _is_permanent_smtp_code(code: int) -> bool:
    """Read an SMTP reply code as a permanent refusal or a transient one.

    Args:
        code: The numeric reply the server gave.

    Returns:
        True for the 5xx range, which RFC 5321 defines as permanent, except
        the codes that refuse our credential rather than the message.
    """
    return 500 <= code < 600 and code not in _CREDENTIAL_SMTP_CODES


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


def generate_email_verification_email(email: str, token: str, invite_unusable: bool = False) -> EmailData:
    """Generate an email verification email.

    Args:
        email: Recipient email address.
        token: The email verification token.
        invite_unusable: Whether the signup carried an invitation that could not be applied. When it
            did, this message says so too, rather than a second message being sent: each send blocks
            on an HTTPS call to the mail provider, so a signup that posted two of them would take
            visibly longer than one that posted one, and the clock would answer the question the
            shared reply refuses. The paragraph lists the possible reasons rather than naming the
            one that applied, and does not repeat the invite token.

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
            "invite_unusable": invite_unusable,
            "link": f"{settings.FRONTEND_HOST}/verify-email?token={token}",
            "assets_base_url": settings.assets_base_url,
        },
    )
    return EmailData(html_content=html_content, subject=subject)


def generate_signup_attempt_email(email: str, invited: bool = False) -> EmailData:
    """Generate a 'someone signed up with your address' email.

    Signup answers the same way for a registered and an unregistered address, so the fact that an
    address already has an account is told to the address itself and to nobody else. The message
    carries no token: it only points at sign-in and password reset, which the holder could have
    reached on their own.

    Args:
        email: Recipient email address, which already has an account.
        invited: Whether the attempt followed a household invitation. When it did, the message says
            the invitation is still waiting, since an unauthenticated signup cannot accept it. The
            invitation link is not repeated here, so the message still carries no token.

    Returns:
        EmailData object with HTML content and subject.
    """
    subject = f"Your Account - {settings.PROJECT_NAME}"
    html_content = _render_email_template(
        template_name="signup_attempt.html",
        context={
            "project_name": settings.PROJECT_NAME,
            "email": email,
            "invited": invited,
            "login_link": f"{settings.FRONTEND_HOST}/login",
            "reset_link": f"{settings.FRONTEND_HOST}/forgot-password",
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
