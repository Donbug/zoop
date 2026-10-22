"""Authored offline evidence: no keys, external requests, or paid calls."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("briefing_http_recovery", Path(__file__).resolve().parents[1] / "briefing_http_recovery.py")
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.calls = Path(self.temp.name)
        self.request = {"model": "authored-model", "input": "{\"documents\":[]}",
                        "text": {"format": {"name": "authored-selection"}}}
        self.key = sha(encoded(self.request))
        self.raw = b"<html>authored gateway error</html>"
        self.pending = {"stage": "authored-selection", "model": "authored-model", "requestDigest": self.key}
        self.receipt = {**self.pending, "responseSha256": sha(self.raw), "httpStatus": 502,
                        "status": "unknown", "usageKnown": False, "inputTokens": None, "outputTokens": None}
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        for suffix, value in (("request", encoded(self.request)), ("response", self.raw),
                              ("pending", encoded(self.pending)), ("complete", encoded(self.receipt))):
            (self.calls / (self.key + "." + suffix + ".json")).write_bytes(value)

    def inspect(self, ref="inbox/authored-operator.md"):
        return recovery.inspect_transient_failure(self.calls, self.key, ref)

    def test_html_502_unknown_usage_keeps_original_files_byte_identical(self):
        before = {p.name: p.read_bytes() for p in self.calls.iterdir()}
        value = self.inspect()
        self.assertEqual(1, value["attempt"])
        self.assertFalse(value["originalUsageKnown"])
        self.assertEqual(self.key, value["originalRequestSha256"])
        self.assertEqual(sha(self.raw), value["originalResponseSha256"])
        self.assertEqual(sha(encoded(self.receipt)), value["originalReceiptSha256"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.calls.iterdir()})

    def test_only_inspected_transient_http_statuses_allowed(self):
        for status in (500, 502, 503, 504):
            with self.subTest(status=status):
                self.receipt["httpStatus"] = status
                self.save()
                self.assertEqual(status, self.inspect()["originalHttpStatus"])
        for status in (200, 401, 403, 408, 429, 501, True, "502"):
            with self.subTest(status=status):
                self.receipt["httpStatus"] = status
                self.save()
                with self.assertRaises(recovery.RecoveryError):
                    self.inspect()

    def test_missing_raw_receipt_or_pending_is_unresolved(self):
        for suffix in ("response", "complete", "pending"):
            with self.subTest(suffix=suffix):
                self.save()
                (self.calls / (self.key + "." + suffix + ".json")).unlink()
                with self.assertRaises(recovery.RecoveryError):
                    self.inspect()

    def test_changed_request_hash_rejected(self):
        self.request["model"] = "changed"
        self.save()
        with self.assertRaisesRegex(recovery.RecoveryError, "request_digest_mismatch"):
            self.inspect()

    def test_changed_response_hash_rejected(self):
        self.raw += b"changed"
        self.save()
        with self.assertRaisesRegex(recovery.RecoveryError, "response_digest_mismatch"):
            self.inspect()

    def test_pending_identity_must_match_receipt(self):
        for field in ("stage", "model", "requestDigest"):
            with self.subTest(field=field):
                original = self.pending[field]
                self.pending[field] = "changed"
                self.save()
                with self.assertRaisesRegex(recovery.RecoveryError, "reservation_receipt_identity"):
                    self.inspect()
                self.pending[field] = original

    def test_request_identity_must_match_receipt(self):
        for field in ("stage", "model", "requestDigest"):
            with self.subTest(field=field):
                pending, receipt = deepcopy(self.pending), deepcopy(self.receipt)
                self.pending[field] = self.receipt[field] = "changed"
                self.save()
                with self.assertRaises(recovery.RecoveryError):
                    self.inspect()
                self.pending, self.receipt = pending, receipt

    def test_missing_request_identity_in_both_records_fails_closed(self):
        del self.pending["requestDigest"]
        del self.receipt["requestDigest"]
        self.save()
        with self.assertRaises(recovery.RecoveryError):
            self.inspect()

    def test_known_usage_is_preserved_only_with_exact_provider_counts(self):
        self.raw = encoded({"status": "failed", "usage": {"input_tokens": 20, "output_tokens": 3}})
        self.receipt.update(responseSha256=sha(self.raw), status="failed", usageKnown=True, inputTokens=20, outputTokens=3)
        self.save()
        self.assertTrue(self.inspect()["originalUsageKnown"])
        self.receipt["inputTokens"] = 21
        self.save()
        with self.assertRaisesRegex(recovery.RecoveryError, "usage_counts_mismatch"):
            self.inspect()

    def test_receipt_cannot_hide_valid_provider_usage(self):
        self.raw = encoded({"usage": {"input_tokens": 20, "output_tokens": 3}})
        self.receipt["responseSha256"] = sha(self.raw)
        self.save()
        with self.assertRaisesRegex(recovery.RecoveryError, "usage_known_mismatch"):
            self.inspect()

    def test_unknown_usage_cannot_be_zero_or_missing(self):
        for bad in (0, 5, False):
            with self.subTest(bad=bad):
                self.receipt["inputTokens"] = bad
                self.save()
                with self.assertRaisesRegex(recovery.RecoveryError, "unknown_usage_must_remain_null"):
                    self.inspect()
        del self.receipt["inputTokens"]
        self.save()
        with self.assertRaises(recovery.RecoveryError):
            self.inspect()

    def test_partial_or_boolean_usage_stays_unknown(self):
        for usage in ({"input_tokens": 5}, {"input_tokens": True, "output_tokens": 2}):
            with self.subTest(usage=usage):
                self.raw = encoded({"usage": usage})
                self.receipt["responseSha256"] = sha(self.raw)
                self.save()
                self.assertFalse(self.inspect()["originalUsageKnown"])

    def test_malformed_usage_is_not_treated_as_empty(self):
        for usage in ([], False, 0, ""):
            with self.subTest(usage=usage):
                self.raw = encoded({"usage": usage})
                self.receipt["responseSha256"] = sha(self.raw)
                self.save()
                with self.assertRaisesRegex(recovery.RecoveryError, "provider_usage_invalid"):
                    self.inspect()

    def test_completed_incomplete_refusal_and_error_200_are_not_recoverable(self):
        for body in ({"status": "completed"}, {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
                     {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal"}]}]},
                     {"error": {"code": "authored-error"}}):
            with self.subTest(body=body):
                self.raw = encoded(body)
                self.receipt.update(httpStatus=200, responseSha256=sha(self.raw), status=body.get("status", "unknown"))
                self.save()
                with self.assertRaisesRegex(recovery.RecoveryError, "transient_http_status"):
                    self.inspect()

    def test_duplicate_json_usage_and_status_mismatch_rejected(self):
        self.raw = b'{"usage":null,"usage":{"input_tokens":2,"output_tokens":1}}'
        self.receipt["responseSha256"] = sha(self.raw)
        self.save()
        with self.assertRaisesRegex(recovery.RecoveryError, "duplicate_json_key"):
            self.inspect()
        self.raw = encoded({"status": "failed"})
        self.receipt["responseSha256"] = sha(self.raw)
        self.save()
        with self.assertRaisesRegex(recovery.RecoveryError, "response_status_mismatch"):
            self.inspect()

    def test_symlinked_evidence_rejected(self):
        path = self.calls / (self.key + ".response.json")
        target = self.calls / "raw-copy"
        path.rename(target)
        path.symlink_to(target)
        with self.assertRaises(recovery.RecoveryError):
            self.inspect()

    def test_operator_inbox_and_digest_are_required(self):
        for ref in (None, "", "report.md", "../inbox/a.md", "inbox/../a.md", "/inbox/a.md"):
            with self.subTest(ref=ref), self.assertRaises(recovery.RecoveryError):
                self.inspect(ref)
        with self.assertRaises(recovery.RecoveryError):
            recovery.inspect_transient_failure(self.calls, "../bad", "inbox/authored.md")

    def test_recovery_data_is_copied_and_changes_request_digest(self):
        data = {"documents": [{"id": "authored"}]}
        descriptor = self.inspect()
        result = recovery.recovery_data(data, descriptor)
        original_request = {**self.request, "input": encoded(data).decode()}
        corrected_request = {**self.request, "input": encoded(result).decode()}
        self.assertNotEqual(sha(encoded(original_request)), sha(encoded(corrected_request)))
        self.assertEqual(descriptor, result["recoveryAttempt"])
        result["documents"][0]["id"] = "changed"
        result["recoveryAttempt"]["attempt"] = 99
        self.assertEqual("authored", data["documents"][0]["id"])
        self.assertEqual(1, descriptor["attempt"])
        with self.assertRaises(recovery.RecoveryError):
            recovery.recovery_data(result, descriptor)

    def test_one_paid_recovery_per_original_even_with_changed_operator_ref(self):
        descriptor = self.inspect()
        recovery.validate_recovery_budget(descriptor, [])
        recovery.validate_recovery_budget(descriptor, ["a" * 64])
        for previous in ([descriptor], [descriptor["originalRequestDigest"]]):
            with self.subTest(previous=previous), self.assertRaisesRegex(recovery.RecoveryError, "already_attempted"):
                recovery.validate_recovery_budget({**descriptor, "operatorInboxRef": "inbox/another.md"}, previous)

    def test_forged_attempt_or_invalid_history_rejected(self):
        descriptor = self.inspect()
        for change in ({"attempt": 2}, {"attempt": True}, {"policy": "automatic-retry"},
                       {"originalUsageKnown": 0}, {"originalRequestSha256": "a" * 64}):
            with self.subTest(change=change), self.assertRaises(recovery.RecoveryError):
                recovery.validate_recovery_budget({**descriptor, **change}, [])
        for history in (None, self.key, [{}], [None]):
            with self.subTest(history=history), self.assertRaises(recovery.RecoveryError):
                recovery.validate_recovery_budget(descriptor, history)

    def test_recovery_of_recovery_request_is_forbidden(self):
        self.request["input"] = encoded({"recoveryAttempt": {"attempt": 1}}).decode()
        self.key = sha(encoded(self.request))
        self.pending["requestDigest"] = self.receipt["requestDigest"] = self.key
        self.save()
        with self.assertRaisesRegex(recovery.RecoveryError, "recovery_chain_forbidden"):
            self.inspect()


if __name__ == "__main__":
    unittest.main()
