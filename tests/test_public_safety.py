from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import artifacts  # noqa: E402
import daily_job  # noqa: E402
import delivery  # noqa: E402


class PublicSafetyTests(unittest.TestCase):
    def test_delivery_has_no_builtin_identity(self):
        source = (ROOT / "src" / "delivery.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", source, re.I))

    def test_delivery_requires_environment(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "MAIL_USER"):
                delivery.send("20260102", "missing.html", "missing.html")

    def test_no_email_addresses_or_delivery_secrets_in_public_text(self):
        text_extensions = {".py", ".md", ".txt", ".cmd", ".yml", ".yaml"}
        combined = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in ROOT.rglob("*")
            if path.is_file()
            and path.name != Path(__file__).name
            and path.suffix.lower() in text_extensions
        )
        self.assertIsNone(re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", combined, re.I))
        for forbidden in (".last_sent",):
            self.assertNotIn(forbidden, combined)

    def test_generic_date_parsing(self):
        self.assertEqual(str(daily_job.parse_target("20260102")), "2026-01-02")


if __name__ == "__main__":
    unittest.main()
