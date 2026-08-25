# -*- coding: utf-8 -*-
"""Optional 163 Mail delivery through SMTP using zmail.

No address or credential has a built-in default.  Delivery is available only
when the caller explicitly requests it and supplies all three environment
variables: ``MAIL_USER``, ``MAIL_PASS``, and ``MAIL_TO``.
"""
from __future__ import annotations

import os
from pathlib import Path


SMTP = {"smtp_host": "smtp.163.com", "smtp_port": 465, "smtp_ssl": True}


def _required_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError("Required environment variable is missing: %s" % name)
    return value


def send(report_date, full_html, compact_html):
    """Send validated HTML artifacts and return the report date."""
    sender = _required_env("MAIL_USER")
    authorization_code = _required_env("MAIL_PASS")
    recipients = [item.strip() for item in _required_env("MAIL_TO").split(",") if item.strip()]
    if not recipients:
        raise RuntimeError("MAIL_TO does not contain a recipient")

    full_html = Path(full_html)
    compact_html = Path(compact_html)
    message = {
        "subject": "China Futures Daily Report - %s-%s-%s"
        % (report_date[:4], report_date[4:6], report_date[6:]),
        "content_html": compact_html.read_text(encoding="utf-8"),
        "attachments": [str(full_html.resolve())],
    }

    import zmail

    server = zmail.server(sender, authorization_code, **SMTP)
    server.send_mail(recipients, message)
    return report_date
