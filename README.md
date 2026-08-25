# China Futures Daily Report

An end-to-end six-exchange China futures pipeline that downloads and validates
market data, tracks dominant contracts, generates HTML reports, and optionally
delivers them through 163 Mail SMTP.

中国六家期货交易所数据下载与完整性校验、主力合约跟踪、HTML 日报生成，以及可选的
163 邮箱自动发送工具。

## Scope

- Downloads and normalizes daily futures data from China's six futures exchanges.
- Maintains main and secondary dominant-contract series.
- Validates exact-date completeness, field coverage, duplicate keys, and exchange coverage.
- Produces a full HTML report and a compact mobile-friendly HTML report.
- Optionally sends the validated report through 163 Mail SMTP using zmail.
- Optionally refreshes daily options data after the futures report is ready.
- Includes a manual GitHub Actions probe for the DCE browser challenge.

## Privacy boundary

This public repository contains no real address, credential, local state,
downloaded market data, generated report, or private execution history.  The
optional delivery module has no defaults and reads configuration only from
environment variables.

## Project layout

```text
exchange_downloaders.ipynb  Exchange download and normalization pipeline
daily_job.py                 Generation-only daily entry point
src/report.py                Validation, analytics, and full HTML rendering
src/compact_report.py        Compact HTML rendering
src/artifacts.py             Validated artifact builder
src/delivery.py              Optional generic 163 SMTP delivery
scripts/probe_dce_xvfb.py    Read-only DCE browser probe
tests/                       Lightweight and optional local-artifact tests
```

Downloaded and generated directories are excluded by `.gitignore`.

## Installation

Use Python 3.11 or newer in a virtual environment:

```bash
python -m pip install -r requirements.txt
```

Chrome or Chromium is required for endpoints protected by browser challenges.

## Usage

Generate the latest previous-weekday report:

```bash
python daily_job.py --skip-options
```

Generate an exact trading date:

```bash
python daily_job.py YYYYMMDD --skip-options
```

The exact-date quality gate refuses to render an older report under a requested
date when the six-exchange dataset is incomplete.

## Optional 163 Mail delivery

163 Mail exposes SMTP rather than a dedicated report API. zmail is a Python
wrapper around that SMTP service. Use a **client authorization code**, never the
webmail login password.

1. Sign in to 163 Mail in the browser.
2. Open settings for POP3/SMTP/IMAP services.
3. Enable SMTP and complete the account security verification.
4. Generate a client authorization code and store it privately.
5. Set the following variables in the current PowerShell session:

```powershell
$env:MAIL_USER = '<your-163-mail-address>'
$env:MAIL_PASS = '<your-smtp-authorization-code>'
$env:MAIL_TO = '<recipient-address>'
```

Then explicitly enable delivery:

```powershell
python daily_job.py YYYYMMDD --skip-options --send-email
```

Without `--send-email`, the program only generates report files. Do not put
addresses or authorization codes into source code, notebooks, committed config
files, screenshots, or logs. For GitHub Actions, use encrypted repository
secrets with the same three names.

## Tests

```bash
python -m unittest discover -s tests -v
```

Tests that require local market-data artifacts are skipped when those files are
not installed.

## GitHub Actions

`.github/workflows/probe-dce-xvfb.yml` is a manually triggered, read-only probe.
It does not download persistent datasets, generate reports, or deliver messages.
Hosted-runner access to DCE may still be blocked by network or browser challenges.

## License

No license has been selected yet. Add one before inviting third-party reuse or
contributions.
