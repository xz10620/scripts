#!/usr/bin/env python3
"""Send an email via Gmail SMTP.

Required environment variables:
    EMAIL_USER   — sender Gmail address
    EMAIL_PASS   — Gmail App Password (not your account password)
                   Generate at: https://myaccount.google.com/apppasswords

Usage:
    python3 send_email.py --to recipient@example.com \
                          --subject "Hello" \
                          --body "Message body"

    # With optional attachment:
    python3 send_email.py --to recipient@example.com \
                          --subject "Report" \
                          --body "See attached." \
                          --attach /path/to/file.pdf
"""

import argparse
import mimetypes
import os
import smtplib
import sys
from email.message import EmailMessage
from typing import Optional


SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465  # SSL


def build_message(sender: str, to: str, subject: str, body: str, attach: Optional[str]) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    if attach:
        mime_type, _ = mimetypes.guess_type(attach)
        maintype, subtype = (mime_type or "application/octet-stream").split("/", 1)
        with open(attach, "rb") as f:
            msg.add_attachment(f.read(), maintype=maintype, subtype=subtype,
                               filename=os.path.basename(attach))

    return msg


def send(msg: EmailMessage, user: str, password: str) -> None:
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)


def main() -> None:
    parser = argparse.ArgumentParser(description="Send an email via Gmail")
    parser.add_argument("--to",      required=True, help="Recipient email address")
    parser.add_argument("--subject", required=True, help="Email subject")
    parser.add_argument("--body",    required=True, help="Email body text")
    parser.add_argument("--attach",  default=None,  help="Path to file to attach (optional)")
    args = parser.parse_args()

    user = os.environ.get("EMAIL_USER")
    password = os.environ.get("EMAIL_PASS")

    if not user or not password:
        sys.exit("Error: EMAIL_USER and EMAIL_PASS environment variables must be set.")

    if args.attach and not os.path.isfile(args.attach):
        sys.exit(f"Error: attachment not found: {args.attach}")

    msg = build_message(user, args.to, args.subject, args.body, args.attach)

    try:
        send(msg, user, password)
        print(f"Email sent to {args.to}")
    except smtplib.SMTPAuthenticationError:
        sys.exit("Error: Authentication failed. Check EMAIL_USER and EMAIL_PASS.")
    except smtplib.SMTPException as e:
        sys.exit(f"Error: SMTP failure — {e}")


if __name__ == "__main__":
    main()
