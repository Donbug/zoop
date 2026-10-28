"""Real producer requests with authored responses; no provider, key, or database."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS/'tests'))
import briefing_usage_run as runner
import briefing_price_aware_prompt as price
import test_briefing_company_outlook as outlook_fixtures
import test_briefing_price_aware_prompt as price_fixtures
from test_briefing_round_simulation import response
from test_briefing_usage import Pipe


class UsagePromptVersionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.requests = []
        self.pipe = Pipe()
        self.output = self.root/'output'

    def job(self, version):
        if version == 'company-outlook-v5':
            frozen = price.freeze(price_fixtures.PriceAwarePromptTest().response())
        else:
            frozen = outlook_fixtures.CompanyOutlookTest().frozen()
            frozen.update(roundId='r', date='2026-10-22', cutoff='2026-10-22T00:20:00Z')
            if version != 'omitted':
                frozen['promptVersion'] = version
        raw = json.dumps(frozen, ensure_ascii=False).encode()
        (self.root/'input.json').write_bytes(raw)
        job = {'schemaVersion': 'briefing-recorded-producer-v1', 'operation': 'outlook',
               'round': {'id': frozen['roundId'], 'date': frozen['date'], 'edition': frozen['edition'],
                         'scheduledAt': frozen['cutoff'], 'windowFrom': None, 'windowTo': frozen['cutoff']},
               'requestKey': 'authored-prompt-check', 'trigger': 'scheduler', 'adminId': None,
               'inputArtifactId': None, 'inputFile': 'input.json',
               'inputSha256': runner.digest(raw), 'maxCalls': 4, 'authorizationRef': 'authored-no-network'}
        path = self.root/'job.json'
        path.write_text(json.dumps(job))
        return path

    def transport(self, raw):
        request = json.loads(raw)
        self.requests.append(request)
        targets = json.loads(request['input'])['frozen']['targets']
        if request['text']['format']['name'].endswith('generation'):
            companies = []
            for t in targets:
                s = {'text': '합성 검토 조건', 'evidenceIds': [t['sourceIds'][0]]}
                companies.append({'companyId': t['companyId'], 'assessment': 'watch', 'impact': s,
                                  'outlook': s, 'conditions': [s], 'risks': [s],
                                  'comparison': {**s, 'status': 'unavailable', 'previousResultVersion': None}})
            draft = {'companies': companies}
        else:
            draft = {'checks': [{'companyId': t['companyId'], 'supported': True,
                                 'reason': 'authored response'} for t in targets]}
        return response(draft, raw)

    def execute(self, path, pipe=None):
        return runner.run(path, self.output, execute=True, transport=self.transport, pipe=pipe or self.pipe)

    def check_version(self, version):
        result = self.execute(self.job(version))
        self.assertEqual('COMPLETE', result['status'])
        self.assertEqual(2, result['newModelCalls'])  # In-memory authored transport only.
        self.assertEqual(2, len(self.requests))
        root = price.company.PROMPTS.with_name(version)
        for request, phase in zip(self.requests, ('generation', 'verification')):
            self.assertEqual((root/(phase+'.md')).read_bytes().decode('utf-8'), request['instructions'])
        binding = json.loads((self.output/'outlook-prompts.json').read_bytes())
        self.assertEqual(version, binding['promptVersion'])
        self.assertEqual({n: runner.digest((root/n).read_bytes()) for n in ('generation.md','verification.md')},
                         binding['promptArtifacts'])

    def test_v1_uses_both_v1_prompt_files(self):
        self.check_version('company-outlook-v1')

    def test_v4_uses_both_v4_prompt_files(self):
        self.check_version('company-outlook-v4')

    def test_v5_keeps_real_price_inputs_and_uses_both_v5_prompt_files(self):
        self.check_version('company-outlook-v5')
        frozen = json.loads(self.requests[0]['input'])['frozen']
        self.assertEqual('available', frozen['targets'][0]['observedMovement']['status'])

    def test_omitted_version_preserves_legacy_v1_behavior(self):
        self.execute(self.job('omitted'))
        self.assertEqual((price.company.PROMPTS/'generation.md').read_bytes().decode('utf-8'), self.requests[0]['instructions'])

    def test_unknown_and_nonstring_versions_fail_before_ledger_or_transport(self):
        for version in ('company-outlook-v999', '../company-outlook-v5', None, [], 5):
            with self.subTest(version=version):
                with self.assertRaisesRegex(ValueError, 'usage_outlook_prompt_version'):
                    self.execute(self.job(version))
        self.assertFalse(self.requests)
        self.assertFalse(self.pipe.events)

    def test_completed_results_reuse_without_another_ledger_claim_or_model(self):
        path = self.job('company-outlook-v5')
        self.execute(path)
        preserved = {p: p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        second = Pipe()
        self.assertEqual('REUSED_COMPLETE', self.execute(path, second)['status'])
        self.assertFalse(second.events)
        self.assertEqual(2, len(self.requests))
        self.assertEqual(preserved, {p: p.read_bytes() for p in self.output.rglob('*') if p.is_file()})

    def test_changed_input_version_does_not_replace_completed_records(self):
        self.execute(self.job('company-outlook-v4'))
        preserved = {p: p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        second = Pipe()
        with self.assertRaisesRegex(ValueError, 'ledger_event_identity_conflict'):
            self.execute(self.job('company-outlook-v5'), second)
        self.assertFalse(second.events)
        self.assertEqual(2, len(self.requests))
        self.assertEqual(preserved, {p: p.read_bytes() for p in self.output.rglob('*') if p.is_file()})

    def test_changed_prompt_bytes_do_not_reuse_or_overwrite_completed_results(self):
        producer = runner.helper('briefing_company_outlook')
        prompts = self.root/'prompts'
        source = producer.PROMPTS.with_name('company-outlook-v4')
        shutil.copytree(source, prompts/source.name)
        producer.PROMPTS = prompts/'company-outlook-v1'
        path = self.job('company-outlook-v4')
        with patch.object(runner, 'helper', return_value=producer):
            self.execute(path)
            original = (self.output/'result.json').read_bytes()
            with (prompts/source.name/'generation.md').open('a') as out:
                out.write('\nAuthored mutation.\n')
            second = Pipe()
            with self.assertRaisesRegex(ValueError, 'ledger_event_identity_conflict'):
                self.execute(path, second)
        self.assertFalse(second.events)
        self.assertEqual(original, (self.output/'result.json').read_bytes())
        self.assertEqual(2, len(self.requests))

    def test_unbound_old_v1_completion_is_preserved(self):
        path = self.job('omitted')
        self.execute(path)
        (self.output/'outlook-prompts.json').unlink()  # Authored legacy fixture only.
        before = (self.output/'result.json').read_bytes()
        second = Pipe()
        self.assertEqual('REUSED_COMPLETE', self.execute(path, second)['status'])
        self.assertEqual(before, (self.output/'result.json').read_bytes())
        self.assertFalse(second.events)

    def test_unbound_non_v1_completion_is_not_relabelled_as_a_correct_version(self):
        for version in ('company-outlook-v4', 'company-outlook-v5'):
            with self.subTest(version=version):
                self.output = self.root/version
                path = self.job(version)
                self.execute(path)
                (self.output/'outlook-prompts.json').unlink()
                before = (self.output/'result.json').read_bytes()
                second = Pipe()
                with self.assertRaisesRegex(ValueError, 'usage_legacy_outlook_prompt_binding_missing'):
                    self.execute(path, second)
                self.assertFalse(second.events)
                self.assertEqual(before, (self.output/'result.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
