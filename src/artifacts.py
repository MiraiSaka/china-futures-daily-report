# -*- coding: utf-8 -*-
"""Generate full and compact HTML artifacts.

Delivery integrations are intentionally outside the public project.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compact_report as compact
import report


def build(date=None, min_oi=10000, prep=None):
    """Return ``(report_date, full_html, compact_html)`` after validation."""
    prepared = prep or report.prepare(date, min_oi)
    if date is not None and prepared["D"] != report.as_date(date):
        raise RuntimeError(
            "Requested date %s is incomplete; refusing to render fallback date %s"
            % (report.as_date(date).date(), prepared["D"].date())
        )
    report.validate_report_ready(prepared)
    compact_path = compact.build_compact_report(prep=prepared)
    full_path = report.build_report(prep=prepared)
    stamp = prepared["D"].strftime("%Y%m%d")
    return stamp, full_path, compact_path


if __name__ == "__main__":
    requested = sys.argv[1] if len(sys.argv) > 1 else None
    date, full, small = build(requested)
    print("report_date=%s\nfull=%s\ncompact=%s" % (date, full, small))
