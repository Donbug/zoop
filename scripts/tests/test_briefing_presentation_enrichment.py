"""Negative source-binding checks; never submit real data or model calls."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("presentation", Path(__file__).resolve().parents[1] / "briefing_presentation_enrichment.py")
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)


class ContextTest(unittest.TestCase):
    def source(self, body, quote):
        sha = p.base.digest(body.encode())
        start = body.index(quote)
        return {"bodySha256": sha, "documentVersion": "sha256-" + sha, "quote": quote,
                "start": start, "end": start + len(quote), "offsetUnit": "unicode_code_point"}

    def test_astral_codepoint_and_literal_context(self):
        body = "앞😀본문" * 600 + "검증된 약 10억원" + "뒤🍀본문" * 600
        source = self.source(body, "검증된 약 10억원")
        context = p.source_context(source, body)
        self.assertEqual(1800, len(context["text"]))
        self.assertEqual(body[context["start"]:context["end"]], context["text"])
        self.assertEqual(source["quote"], context["text"][source["start"]-context["start"]:source["end"]-context["start"]])

    def test_changed_same_length_body_rejected(self):
        source = self.source("가나다 검증 원문", "검증")
        with self.assertRaisesRegex(p.base.ReplayError, "version_mismatch"):
            p.source_context(source, "라마바 검증 원문")

    def test_quote_edit_and_utf16_offset_rejected(self):
        body = "😀 출처의 약 10억원 자료"
        source = self.source(body, "약 10억원")
        for wrong in ({**source, "quote": "10억원"}, {**source, "start": source["start"]+1}):
            with self.assertRaisesRegex(p.base.ReplayError, "quote_not_exact"):
                p.source_context(wrong, body)

    def test_missing_cache_cannot_refetch(self):
        with self.assertRaisesRegex(p.base.ReplayError, "network_forbidden"):
            p.offline_only("https://example.invalid")


if __name__ == "__main__":
    unittest.main()
