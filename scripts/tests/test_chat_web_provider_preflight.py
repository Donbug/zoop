from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "chat_web_provider_preflight", ROOT / "scripts" / "chat_web_provider_preflight.py"
)
assert SPEC and SPEC.loader
preflight = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = preflight
SPEC.loader.exec_module(preflight)

ENV = {
    "ZOOP_CHAT_WEB_NAVER_API_HUB_CLIENT_ID": "client-id",
    "ZOOP_CHAT_WEB_NAVER_API_HUB_CLIENT_SECRET": "client-secret",
}


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class ChatWebProviderPreflightTest(unittest.TestCase):
    def test_probe_records_only_content_free_contract_evidence(self):
        seen = {}

        def open_url(request, timeout):
            seen["request"] = request
            seen["timeout"] = timeout
            return Response(json.dumps({"items": [{"title": "제목", "link": "https://example.com"}]}).encode())

        result = preflight.probe(
            ENV, "a" * 40, "naver-key-v1", open_url,
            lambda: datetime(2026, 11, 2, tzinfo=timezone.utc),
        )
        self.assertEqual("passed", result["status"])
        self.assertEqual(1, result["itemCount"])
        self.assertEqual(preflight.KEYS, set(result))
        encoded = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("client-id", encoded)
        self.assertNotIn("client-secret", encoded)
        self.assertNotIn("제목", encoded)
        self.assertNotIn(preflight.FIXED_QUERY, encoded)
        self.assertEqual(7, seen["timeout"])
        self.assertEqual("client-id", seen["request"].get_header("X-ncp-apigw-api-key-id"))

    def test_oversize_or_invalid_contract_fails_closed(self):
        too_big = lambda request, timeout: Response(b"x" * (preflight.MAX_RESPONSE_BYTES + 1))
        result = preflight.probe(ENV, "a" * 40, "naver-key-v1", too_big)
        self.assertEqual("failed", result["status"])

        invalid = lambda request, timeout: Response(b'{"items":[{"title":1,"link":"x"}]}')
        result = preflight.probe(ENV, "a" * 40, "naver-key-v1", invalid)
        self.assertEqual("failed", result["status"])

    def test_credentials_and_identity_are_required_before_the_call(self):
        called = False

        def open_url(request, timeout):
            nonlocal called
            called = True
            return Response(b'{"items":[]}')

        with self.assertRaises(preflight.PreflightError):
            preflight.probe({}, "a" * 40, "naver-key-v1", open_url)
        with self.assertRaises(preflight.PreflightError):
            preflight.probe(ENV, "short", "naver-key-v1", open_url)
        self.assertFalse(called)

    def test_evidence_loader_rejects_failed_or_extra_fields(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            path = Path(folder) / "evidence.json"
            value = preflight.probe(ENV, "a" * 40, "naver-key-v1",
                                    lambda request, timeout: Response(b'{"items":[]}'))
            path.write_text(json.dumps(value), encoding="utf-8")
            self.assertEqual(value, preflight.load(path))
            value["query"] = "must not be stored"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(preflight.PreflightError):
                preflight.load(path)
            del value["query"]
            value["status"] = "failed"
            value["responseContractObserved"] = False
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(preflight.PreflightError):
                preflight.load(path)

    def test_cli_requires_explicit_call_approval_before_network(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            output = Path(folder) / "evidence.json"
            capture, saved = io.StringIO(), sys.stdout
            try:
                sys.stdout = capture
                code = preflight.main([
                    "--candidate-commit", "a" * 40,
                    "--credential-revision", "naver-key-v1",
                    "--output", str(output),
                ])
            finally:
                sys.stdout = saved
            self.assertEqual(2, code)
            self.assertFalse(output.exists())
            self.assertIn("approved", capture.getvalue())


if __name__ == "__main__":
    unittest.main()
