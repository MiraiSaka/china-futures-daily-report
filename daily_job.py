# -*- coding: utf-8 -*-
"""Update the latest complete trading day and generate validated HTML reports.

This public entry point performs no message or email delivery.  Pass an optional
``YYYYMMDD`` date; without one it uses the previous weekday.  Exchange holidays
and incomplete six-exchange data are rejected by the report quality gate.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import sys
import traceback
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)

BASE = Path(__file__).resolve().parent
NOTEBOOK = BASE / "exchange_downloaders.ipynb"
os.environ.setdefault("FUTURES_REPORT_BASE", str(BASE))


def log(message=""):
    print("%s  %s" % (dt.datetime.now().strftime("%H:%M:%S"), message))


def previous_weekday(today=None):
    day = (today or dt.date.today()) - dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day


def parse_target(value=None):
    if value is None:
        return previous_weekday()
    return dt.datetime.strptime(value, "%Y%m%d").date()


def load_notebook():
    """Load notebook definitions without executing non-code cells."""
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    namespace = {"__name__": "__daily_job__"}
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] == "code":
            source = "".join(cell["source"])
            exec(compile(source, "<cell %d>" % index, "exec"), namespace)
    return namespace


def run(target, skip_options=False, send_email=False):
    target = parse_target(target) if isinstance(target, str) else target
    log("target trading date: %s" % target)
    pipeline = load_notebook()
    pipeline["daily_update"](
        int(target.strftime("%Y%m%d")),
        rebuild_dominant=False,
        dominant_csv=True,
        render_report=False,
    )

    sys.path.insert(0, str(BASE / "src"))
    import artifacts
    import report

    loaded = report.load_all()
    futures = loaded[0]
    actual = report.pick_date(futures, target)
    if actual.date() != target:
        raise RuntimeError(
            "Requested date %s did not pass the exact-date completeness gate; latest complete date is %s"
            % (target, actual.date())
        )
    prepared = report.prepare(target, loaded=loaded)
    report.validate_report_ready(prepared)
    stamp, full, compact = artifacts.build(target, prep=prepared)
    log("generated %s" % stamp)
    log("full report: %s" % full)
    log("compact report: %s" % compact)

    if send_email:
        import delivery

        delivery.send(stamp, full, compact)
        log("optional email delivery completed")

    if not skip_options:
        result = pipeline["refresh_options"](int(target.strftime("%Y%m%d")))
        log("options refresh: %s" % result)
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Generate a validated China futures daily report")
    parser.add_argument("date", nargs="?", help="Trading date in YYYYMMDD format")
    parser.add_argument("--skip-options", action="store_true", help="Skip the optional options refresh")
    parser.add_argument(
        "--send-email",
        action="store_true",
        help="Send through 163 SMTP using MAIL_USER, MAIL_PASS, and MAIL_TO",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    return run(
        parse_target(args.date),
        skip_options=args.skip_options,
        send_email=args.send_email,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        log("failed")
        traceback.print_exc()
        raise SystemExit(1)
