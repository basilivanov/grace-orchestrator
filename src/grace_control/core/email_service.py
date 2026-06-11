# ############################################################################
# AI_HEADER: email_service
# ROLE: SMTP email sender for password-reset and other transactional emails.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Send transactional emails via SMTP (TLS). Used by the auth router
#          to deliver password-reset links. No-op when smtp_host is empty.
# inputs: recipient email, subject, body text.
# returns: True on success, False on failure.
# side_effects: Opens SMTP connection, sends email.
# emitted_logs: email_sent on success, email_failed on error.
# error_behavior: Logs error, never raises.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: send_email
#   - function: send_password_reset_email
# END_MODULE_MAP

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText

from grace_control.config.settings import settings
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("email_service")


#START_BLOCK_SEND

# START_FUNCTION_CONTRACT
# name: send_email
# purpose: Send an email via SMTP with TLS. No-op if smtp_host is not configured.
# inputs: to_email, subject, body (plain text).
# returns: bool — True if sent, False otherwise.
# side_effects: Connects to SMTP server.
# emitted_logs: email_sent, email_failed.
# error_behavior: Returns False on any error; never raises.
# END_FUNCTION_CONTRACT
def send_email(to_email: str, subject: str, body: str) -> bool:
    if not settings.smtp_host:
        _log.warn("email_not_configured", to=to_email, subject=subject)
        return False

    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = settings.email_from_address
    msg["To"] = to_email

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            if settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.sendmail(settings.email_from_address, [to_email], msg.as_string())
        _log.info("email_sent", to=to_email, subject=subject)
        return True
    except Exception as e:
        _log.error("email_failed", to=to_email, subject=subject, error=str(e)[:200])
        return False

#END_BLOCK_SEND


#START_BLOCK_PASSWORD_RESET

# START_FUNCTION_CONTRACT
# name: send_password_reset_email
# purpose: Send a password-reset email with a signed reset link.
# inputs: to_email, reset_token, base_url (e.g. http://localhost:8042).
# returns: bool — True if sent.
# side_effects: Calls send_email.
# emitted_logs: None (delegates to send_email).
# error_behavior: Returns False on failure.
# END_FUNCTION_CONTRACT
def send_password_reset_email(to_email: str, reset_token: str, base_url: str = "") -> bool:
    base = base_url or f"http://{settings.api_host}:{settings.api_port}"
    reset_link = f"{base}/api/auth/reset-password?token={reset_token}"
    body = (
        f"Hello,\n\n"
        f"A password reset was requested for {to_email}.\n\n"
        f"Click the link below to reset your password:\n{reset_link}\n\n"
        f"If you did not request this, please ignore this email.\n\n"
        f"This link expires in 1 hour."
    )
    return send_email(to_email, "Password Reset Request", body)

#END_BLOCK_PASSWORD_RESET
