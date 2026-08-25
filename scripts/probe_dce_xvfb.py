"""Probe whether a headed Chrome under Xvfb can pass DCE's challenge.

This script is intentionally read-only: it requests one known trading day,
validates the futures and options JSON responses, and writes no market data.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request

import websocket


DCE_PAGE = "http://www.dce.com.cn/dce/channel/list/164.html"
DCE_API = "http://www.dce.com.cn/dcereport/publicweb/dailystat/dayQuotes"
REQUIRED_FIELDS = {
    "contractId", "open", "high", "low", "close", "lastClear",
    "clearPrice", "volumn", "openInterest", "diffI", "turnover",
}


class ChromeProbe:
    def __init__(self, port: int = 9222):
        self.port = port
        self.chrome = (
            shutil.which("google-chrome")
            or shutil.which("google-chrome-stable")
            or shutil.which("chromium")
            or shutil.which("chromium-browser")
        )
        if not self.chrome:
            raise RuntimeError("Google Chrome/Chromium was not found")
        self.profile = Path(tempfile.mkdtemp(prefix="dce-probe-"))
        self.proc: subprocess.Popen[bytes] | None = None
        self.ws = None
        self.message_id = 0

    def start(self) -> None:
        args = [
            self.chrome,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-popup-blocking",
            "--disable-dev-shm-usage",
            "--window-size=1200,860",
            "about:blank",
        ]
        self.proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        version_url = f"http://127.0.0.1:{self.port}/json/version"
        for _ in range(80):
            try:
                urllib.request.urlopen(version_url, timeout=1).read()
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("Chrome did not expose its debugging endpoint")

        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/json/new?about:blank",
            data=b"",
            method="PUT",
        )
        target = json.loads(urllib.request.urlopen(request, timeout=10).read())
        self.ws = websocket.create_connection(
            target["webSocketDebuggerUrl"],
            timeout=180,
            suppress_origin=True,
            enable_multithread=True,
        )
        self._send("Page.enable")
        self._send("Runtime.enable")

    def close(self) -> None:
        try:
            self._send("Browser.close")
        except Exception:
            pass
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        if self.proc:
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)

    def _send(self, method: str, **params):
        self.message_id += 1
        current_id = self.message_id
        self.ws.send(json.dumps({"id": current_id, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == current_id:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})

    def _javascript(self, expression: str, timeout: int = 120):
        result = self._send(
            "Runtime.evaluate",
            expression=expression,
            awaitPromise=True,
            returnByValue=True,
            timeout=timeout * 1000,
        )
        if result.get("exceptionDetails"):
            raise RuntimeError("JavaScript evaluation failed")
        return result["result"].get("value")

    def warm(self, wait: int = 50) -> int:
        self._send("Page.navigate", url=DCE_PAGE)
        for _ in range(wait):
            time.sleep(1)
            try:
                length = self._javascript(
                    "document.body ? document.body.innerText.length : 0"
                )
            except Exception:
                continue
            if isinstance(length, int) and length > 300:
                return length
        raise RuntimeError("DCE challenge did not produce a usable page")

    def post(self, trade_date: str, trade_type: str) -> list[dict]:
        payload = {
            "contractId": "",
            "lang": "zh",
            "optionSeries": "",
            "statisticsType": "0",
            "tradeDate": trade_date,
            "tradeType": trade_type,
            "varietyId": "all",
        }
        expression = (
            "(async()=>{const r=await fetch(%s,{method:'POST',headers:{"
            "'Accept':'application/json, text/plain, */*',"
            "'Content-Type':'application/json'},credentials:'same-origin',"
            "body:JSON.stringify(%s)});const text=await r.text();"
            "return {status:r.status,text};})()"
            % (json.dumps(DCE_API), json.dumps(payload, ensure_ascii=False))
        )
        response = self._javascript(expression)
        if not isinstance(response, dict) or response.get("status") != 200:
            raise RuntimeError(f"DCE returned HTTP {response!r}")
        document = json.loads(response.get("text") or "")
        if document.get("success") is not True or document.get("code") != 200:
            raise RuntimeError("DCE returned an unsuccessful JSON envelope")
        rows = document.get("data")
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("DCE returned no rows for the probe trading day")
        return rows


def validate_rows(rows: list[dict], option: bool) -> int:
    contracts = []
    for row in rows:
        contract = str(row.get("contractId") or "").strip()
        if not contract or "小计" in contract or "总计" in contract:
            continue
        is_option = bool(re.search(r"[-_]?[CP][-_]?\d", contract, re.I))
        if is_option == option:
            contracts.append(row)
    if not contracts:
        raise RuntimeError("No contracts of the expected type were returned")
    missing = REQUIRED_FIELDS - set(contracts[0])
    if missing:
        raise RuntimeError(f"DCE response is missing fields: {sorted(missing)}")
    return len(contracts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("trade_date", help="Known trading day in YYYYMMDD form")
    args = parser.parse_args()
    if not re.fullmatch(r"20\d{6}", args.trade_date):
        parser.error("trade_date must use YYYYMMDD")

    probe = ChromeProbe()
    started = time.perf_counter()
    try:
        probe.start()
        body_length = probe.warm()
        futures = validate_rows(probe.post(args.trade_date, "1"), option=False)
        options = validate_rows(probe.post(args.trade_date, "2"), option=True)
    finally:
        probe.close()
    print(json.dumps({
        "ok": True,
        "trade_date": args.trade_date,
        "body_length": body_length,
        "futures_contracts": futures,
        "options_contracts": options,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "display": os.environ.get("DISPLAY", ""),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
