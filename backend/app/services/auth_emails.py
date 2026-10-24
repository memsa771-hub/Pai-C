# -*- coding: utf-8 -*-
"""The account emails: verify your email, reset your password, new sign-in, account deleted.

One place for all of them, each as simple branded HTML with a plain-text twin,
in English, sent through Resend. Firebase never sends its own emails.
"""

import html
from urllib.parse import urlencode

from app.config import config
from app.services.email import send_email

_BRAND = "Placement AI"
_BLUE = "#155eef"


def action_link(mode: str, code: str) -> str:
    """Our own page for a Firebase action code: /auth/action?mode=…&oobCode=…"""
    return f"{config.APP_URL.rstrip('/')}/auth/action?{urlencode({'mode': mode, 'oobCode': code})}"


def _html(title: str, paragraphs: list[str], button: tuple[str, str] | None, footer: str) -> str:
    body = "".join(f'<p style="margin:0 0 16px;font-size:15px;line-height:1.55;color:#344054">{html.escape(p)}</p>'
                   for p in paragraphs)
    cta = ""
    if button:
        label, url = button
        cta = (f'<p style="margin:24px 0"><a href="{html.escape(url, quote=True)}" '
               f'style="display:inline-block;background:{_BLUE};color:#ffffff;text-decoration:none;'
               f'font-weight:600;font-size:15px;padding:12px 22px;border-radius:12px">{html.escape(label)}</a></p>'
               f'<p style="margin:0 0 16px;font-size:12px;line-height:1.5;color:#667085">'
               f'If the button does not work, copy this link into your browser:<br>'
               f'<span style="word-break:break-all">{html.escape(url)}</span></p>')
    return (
        '<!doctype html><html><body style="margin:0;background:#f4f7fc;padding:24px 12px;'
        'font-family:Manrope,Segoe UI,Helvetica,Arial,sans-serif">'
        '<div style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:20px;padding:32px 28px;'
        'border:1px solid #e1e9f5">'
        f'<p style="margin:0 0 24px;font-size:16px;font-weight:700;color:{_BLUE}">{_BRAND}</p>'
        f'<h1 style="margin:0 0 16px;font-size:22px;line-height:1.3;color:#0f172a">{html.escape(title)}</h1>'
        f'{body}{cta}'
        f'<p style="margin:24px 0 0;font-size:12px;line-height:1.5;color:#667085">{html.escape(footer)}</p>'
        '</div></body></html>'
    )


def _text(title: str, paragraphs: list[str], button: tuple[str, str] | None, footer: str) -> str:
    parts = [_BRAND, "", title, "", *[p + "\n" for p in paragraphs]]
    if button:
        parts += [f"{button[0]}: {button[1]}", ""]
    parts.append(footer)
    return "\n".join(parts)


def _send(to: str, subject: str, title: str, paragraphs: list[str],
          button: tuple[str, str] | None, footer: str) -> bool:
    return send_email(to, subject, _html(title, paragraphs, button, footer),
                      text_body=_text(title, paragraphs, button, footer))


def send_verification_email(to: str, code: str) -> bool:
    return _send(
        to, "Verify your email for Placement AI", "Verify your email",
        ["Welcome to Placement AI. Please confirm this is your email address so you can start with PAI."],
        ("Verify email", action_link("verifyEmail", code)),
        "If you did not create an account, you can ignore this email.",
    )


def send_password_reset_email(to: str, code: str) -> bool:
    return _send(
        to, "Reset your Placement AI password", "Reset your password",
        ["We received a request to reset the password for your Placement AI account.",
         "This link works once and expires soon."],
        ("Choose a new password", action_link("resetPassword", code)),
        "If you did not ask to reset your password, you can ignore this email. Your password stays the same.",
    )


def send_new_sign_in_email(to: str, device: str, when: str) -> bool:
    return _send(
        to, "New sign-in to your Placement AI account", "New sign-in to your account",
        [f"Your Placement AI account was just signed in to from a new device: {device}.",
         f"Time: {when}.",
         "If this was you, there is nothing to do."],
        ("Reset your password", f"{config.APP_URL.rstrip('/')}/forgot-password"),
        "If this was not you, reset your password now to keep your account safe.",
    )


def send_account_deleted_email(to: str) -> bool:
    return _send(
        to, "Your Placement AI account has been deleted", "Your account has been deleted",
        ["Your Placement AI account and all your data have been permanently deleted, as you asked.",
         "You can no longer sign in with this email."],
        None,
        "If you did not ask for this, reply to this email.",
    )
