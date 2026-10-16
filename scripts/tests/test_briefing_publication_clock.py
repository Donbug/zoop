"""Synthetic publication metadata and cached proof checks; no network or credentials."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import briefing_publication_clock as clock

URL = "https://example.invalid/article"


def html(value, **fields):
    return ('<html><script type="application/ld+json">' + json.dumps({"@type": "NewsArticle", "url": URL,
            "datePublished": value, **fields}) + '</script></html>').encode()


class PublicationClockTest(unittest.TestCase):
    def test_original_offset_is_converted_without_assuming_local_midnight(self):
        status, value, _ = clock.declaration_status(html("2026-10-02T17:20:03+08:00"), URL)
        self.assertEqual((status, value), ("verified_timestamp", "2026-10-02T09:20:03+00:00"))

    def test_date_only_and_naive_time_are_not_exact_clocks(self):
        self.assertEqual(clock.declaration_status(html("2026-10-02"), URL)[:2], ("date_only", None))
        self.assertEqual(clock.declaration_status(html("2026-10-02T09:20:00"), URL)[:2], ("unverified", None))

    def test_modified_time_search_date_and_related_articles_are_not_publication_proof(self):
        for raw in [html("2026-10-02T09:00:00Z", url="https://example.invalid/related"),
                    b'<meta property="article:modified_time" content="2026-10-02T09:00:00Z">',
                    b'<p>2026-10-02 09:20</p>']:
            self.assertEqual(clock.declaration_status(raw, URL)[:2], ("unverified", None))

    def test_conflicting_publication_instants_hold_but_equivalent_offsets_agree(self):
        first = html("2026-10-02T09:00:00Z")
        equivalent = b'<meta property="article:published_time" content="2026-10-02T18:00:00+09:00">'
        self.assertEqual(clock.declaration_status(first + equivalent, URL)[0], "verified_timestamp")
        later = b'<meta property="article:published_time" content="2026-10-02T10:00:00Z">'
        self.assertEqual(clock.declaration_status(first + later, URL)[:2], ("conflicting", None))

    def test_other_receipt_query_or_page_cannot_supply_clock(self):
        self.assertFalse(clock.same_page(URL, URL + "?receipt=other"))
        self.assertFalse(clock.same_page(URL, "https://other.invalid/article"))
        self.assertTrue(clock.same_page(URL, "https://www.example.invalid/article/"))

    def test_private_destinations_are_rejected_before_http(self):
        with patch.object(clock.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 80))]):
            with self.assertRaises(clock.ReplayError):
                clock.public_url(URL)

    def test_existing_html_requires_matching_receipt_and_remains_hash_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "previous" / "original-html"; previous.mkdir(parents=True)
            metadata = previous.parent / "original-publication"; metadata.mkdir()
            raw = html("2026-10-02T09:00:00Z")
            (previous / "authored.html").write_bytes(raw)
            (metadata / "authored.json").write_text(json.dumps({"documentId": "authored", "url": URL,
                "finalUrl": URL, "htmlSha256": clock.digest(raw), "checkedAt": "2026-10-16T00:00:00Z"}))
            row = {"documentId": "authored", "url": URL, "bodySha256": "b" * 64, "sourceKind": "news"}
            collector = clock.ClockCollector(root / "output", "a" * 64, reuse_dirs=[previous])
            observed = collector.collect(row)
            self.assertEqual(observed["status"], "verified_timestamp")
            self.assertEqual(collector.network_requests, 0)
            self.assertEqual(collector.collect(row), observed)
            (collector.output / "html" / (observed["htmlSha256"] + ".html")).write_bytes(b"tampered")
            with self.assertRaises(clock.ReplayError):
                collector.collect(row)

    def test_provider_timestamp_and_dart_reception_day_never_become_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = clock.ClockCollector(Path(directory) / "output", "a" * 64)
            common = {"bodySha256": "b" * 64, "url": URL, "originalPublicationVerified": True,
                      "providerBodyDate": "2026-10-02T09:00:00Z"}
            news = collector.collect({**common, "documentId": "news", "sourceKind": "news"})
            dart = collector.collect({**common, "documentId": "dart", "sourceKind": "disclosure", "receptionDate": "20261002"})
            self.assertEqual((news["status"], news["publishedAt"]), ("not_observed", None))
            self.assertEqual((dart["status"], dart["publishedAt"]), ("date_only", None))


if __name__ == "__main__":
    unittest.main()
