"""Positive controls and explicit scope checks for the published archive audit."""
import copy
import gzip
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
import zipfile

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('archive_audit', SCRIPTS/'briefing_data_archive_audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class ArchiveAuditTest(unittest.TestCase):
    def inspector(self):
        return audit.Inspector(json.loads(audit.POLICY.read_bytes()))

    def test_known_signature_families_and_credential_fields_have_positive_controls(self):
        samples = [b'sk-'+b'A'*40, b'ghp_'+b'B'*30, b'AKIA'+b'C'*16,
                   b'-----BEGIN '+b'PRIVATE KEY-----', b'Bearer '+b'D'*30,
                   b'eyJabc.eyJdef.signature', b'{"password":"fixture-sensitive-value"}',
                   b'api_key=fixture-sensitive-value']
        for raw in samples:
            with self.subTest(raw=raw[:8]):
                inspector = self.inspector();inspector.inspect(raw, 'fixture')
                self.assertTrue(inspector.findings)

    def test_redaction_markers_public_urls_and_numeric_token_usage_are_not_credentials(self):
        inspector = self.inspector()
        inspector.inspect(b'{"apiKey":"[REDACTED_CREDENTIAL]","password":"", "token":120,"url":"https://example.com/sk-hynix-news","model":"gpt-6-luna"}', 'fixture')
        self.assertFalse(inspector.findings)

    def test_jsonl_nested_fields_and_utf16_are_inspected(self):
        for raw in [b'{"data":{"refresh_token":"fixture-sensitive-value"}}\n{}\n',
                    '{"api_key":"fixture-sensitive-value"}'.encode('utf-16')]:
            inspector = self.inspector();inspector.inspect(raw, 'fixture')
            self.assertTrue(inspector.findings)

    def test_zip_members_comments_names_and_gzip_are_data_only(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.comment = b'Bearer '+b'A'*30
            archive.writestr('ghp_'+ 'B'*30, gzip.compress(b'{"access_token":"fixture-sensitive-value"}'))
        inspector = self.inspector();inspector.inspect(stream.getvalue(), 'fixture')
        self.assertEqual(1, inspector.zip_objects);self.assertEqual(1, inspector.zip_members)
        self.assertEqual(1, inspector.gzip_objects);self.assertGreaterEqual(len(inspector.findings), 3)

    def test_expansion_limit_fails_instead_of_silently_skipping(self):
        inspector = self.inspector();inspector.policy = copy.deepcopy(inspector.policy)
        inspector.policy['maximumExpandedBytesPerObject'] = 80
        with self.assertRaises(ValueError): inspector.inspect(gzip.compress(b'A'*100), 'fixture')

    def test_unapproved_tables_columns_and_admin_email_are_rejected(self):
        policy = self.inspector().policy
        for table, value in [('accounts', {}), ('articles', {'password': 'x'}),
                             ('graph_activations', {'admin_email_snapshot': 'person@private-domain.org'})]:
            with self.subTest(table=table):
                with self.assertRaises(ValueError): audit.check_columns(table, json.dumps(value).encode(), policy)
        rows, actors = audit.check_columns('graph_activations', b'{"admin_email_snapshot":"system"}', policy)
        self.assertEqual(1, rows);self.assertEqual({'system':1}, dict(actors))

    def test_metadata_exception_requires_exact_object_pointer_and_sibling_types(self):
        value = {'entityID': 1, 'rank': '1', 'score': 0.5, 'token': 'Article label'}
        item = {'objectSha256': 'reviewed', 'pointer': '/entities/0/token',
                'requiredSiblingKeys': list(value),
                'requiredValueTypes': {k:type(v).__name__ for k,v in value.items()}}
        for digest, document, permitted in [
            ('reviewed', {'entities':[value]}, True),
            ('other', {'entities':[value]}, False),
            ('reviewed', {'other':[value]}, False),
            ('reviewed', {'entities':[{**value, 'entityID':'changed'}]}, False)]:
            inspector = self.inspector();inspector.policy['reviewedFieldExceptions'] = [item]
            inspector.structured(document, digest)
            self.assertEqual(permitted, bool(inspector.reviewed_fields))
            self.assertEqual(not permitted, bool(inspector.findings))

    def test_publisher_redactor_preserves_surrounding_bytes_and_rejects_ambiguity(self):
        from briefing_archive_redaction import redact_publisher_config, MARKER
        value = {'analytics':{'tags':{'permutive':{'workspace_api_key':'fixture-browser-config'}}}}
        line = json.dumps(value).encode()+b'\r\n'
        raw = b'<html>\r\n'+line+b'</html>\n'
        updated = redact_publisher_config(raw)
        self.assertEqual(raw.replace(b'fixture-browser-config', MARKER.encode()), updated)
        for invalid in [b'no config', line+line,
                        json.dumps({**value, 'duplicate':'fixture-browser-config'}).encode()]:
            with self.assertRaises(ValueError): redact_publisher_config(invalid)


if __name__ == '__main__': unittest.main()
