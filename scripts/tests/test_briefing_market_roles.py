"""Role-specific schema/repair contracts. Authored model decisions are NOT accuracy tests."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('roles_fixture', Path(__file__).with_name('test_briefing_market_context.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
c = f.context


class RoleTransport(f.ContextTransport):
    def __init__(self, reject_first=False, failed_flag='factUnitAppropriate'):
        self.verifications = 0
        self.generations = 0
        self.reject_first = reject_first
        self.failed_flag = failed_flag
        super().__init__(self.roles)

    def roles(self, stage, answer):
        if stage == 'market_summary_generation':
            self.generations += 1
            if self.generations > 1:
                answer['claims'][0]['text'] = '합성 근거의 미확정 공급 계약 계획을 별도 사실로 보완했습니다.'
            slots, optional = {}, []
            for claim in answer['claims']:
                kind = claim['kind']
                if kind == 'forecast':
                    claim.update(conditions=[], direction='uncertain', text='합성 근거가 엇갈려 잠정 방향은 불확실합니다.')
                if kind in {'forecast', 'forecast_update', 'result_comparison'} and kind not in slots:
                    slots[kind] = claim
                else:
                    optional.append(claim)
            answer.update(claims=optional, requiredClaims=slots)
        else:
            self.verifications += 1
            for check in answer['checks'].values():
                check.update({flag: True for flag in c.ROLE_FLAGS})
            if self.reject_first and self.verifications == 1:
                check = next(iter(answer['checks'].values()))
                check.update(verdict='UNSUPPORTED', reason='Authored role rejection')
                check[self.failed_flag] = False


class MarketRoleTest(unittest.TestCase):
    def setUp(self):
        self.old = c.PROMPTS
        c.PROMPTS = c.PROMPTS.with_name(c.ROLE_VERSION)

    def tearDown(self):
        c.PROMPTS = self.old

    def data(self, morning=False, previous=False):
        old = f.prior()
        if morning:
            old.update(edition='evening', cutoff='2026-10-07T17:30:00+09:00')
        data, _, _ = f.input_data(morning=morning, records=[old] if previous else [])
        data['marketContext']['forecastTargets'] = [f.target()]
        data['context'].update(summaryPromptVersion=c.ROLE_VERSION,
            marketContextSha256=c.base.digest(c.base.canonical(data['marketContext'])))
        data['contextSha256'] = c.base.digest(c.base.canonical(data['context']))
        return data

    def test_required_forecast_slot_exists_on_both_initial_and_repair_requests(self):
        data = self.data(previous=True)
        before = copy.deepcopy(data)
        with tempfile.TemporaryDirectory() as directory:
            transport = RoleTransport(reject_first=True)
            client = c.legacy.MarketSummaryClient(Path(directory), transport, 8, prompt_root=c.PROMPTS)
            result = c.generate_market_summary(client, data, 1)
        self.assertEqual('PASS', result['verification']['status'])
        self.assertEqual(['WITHHELD', 'PASS'], [a['verification']['status'] for a in result['attempts']])
        requests = [c.base.strict_load(r) for r in transport.requests]
        generations = [r for r in requests if r['text']['format']['name'] == 'market_summary_generation']
        self.assertEqual(2, len(generations))
        for request in generations:
            schema = request['text']['format']['schema']
            slots = schema['properties']['requiredClaims']
            self.assertEqual(['forecast', 'result_comparison'], slots['required'])
            self.assertEqual(['forecast'], slots['properties']['forecast']['properties']['kind']['enum'])
        initial, repair = [c.base.strict_load(r['input']) for r in generations]
        self.assertEqual(initial['frozenInputSha256'], repair['frozenInputSha256'])
        self.assertEqual('WITHHELD', repair['priorValidation']['status'])
        self.assertIn('forecast', repair['priorDraft']['requiredClaims'])
        self.assertEqual(4, len(result['usage']))
        self.assertEqual(before, data)

    def test_morning_update_and_evening_comparison_have_different_required_slots(self):
        for morning, role in [(True, 'forecast_update'), (False, 'result_comparison')]:
            with self.subTest(role=role):
                values = c._prepare(self.data(morning=morning, previous=True))
                schema = c._schema(*values[:5])
                self.assertEqual(['forecast', role], schema['properties']['requiredClaims']['required'])
                self.assertNotIn('atomicClaim', c.base.strict_load((c.PROMPTS/'verification.schema.json').read_bytes())['properties']['checks']['items']['required'])

    def test_missing_required_forecast_is_never_restored_from_previous_draft(self):
        frozen, *rest = c._prepare(self.data())
        with self.assertRaisesRegex(c.ContextError, 'required_slots'):
            c._claims({'claims': [], 'requiredClaims': {}}, frozen, *rest[:4])
        schema = c._schema(frozen, *rest[:4])
        with self.assertRaises(Exception):
            c.base.validate_schema({'claims': [], 'requiredClaims': {}}, schema)

    def test_comparison_requires_matching_server_evaluation_even_when_unavailable(self):
        values = c._prepare(self.data(previous=True))
        frozen, evidence, _, prior, evaluations, _ = values
        forecast = f.claim('合成限定見通し', list(evidence)[:1], kind='forecast', targetId=f.target()['targetId'],
            direction='uncertain', counterFactors=['合成限定要因'])
        compare = f.claim('이전 모의 전망과 현재 미관측·서버 unavailable을 함께 설명합니다.',
            kind='result_comparison', previousForecastIds=list(prior), evaluationIds=list(evaluations))
        draft = {'claims': [], 'requiredClaims': {'forecast': forecast, 'result_comparison': compare}}
        self.assertEqual(2, len(c._claims(draft, *values[:5])))
        draft['requiredClaims']['result_comparison']['evaluationIds'] = []
        with self.assertRaisesRegex(c.ContextError, 'comparison_evaluations'):
            c._claims(draft, *values[:5])

    def test_new_role_check_failures_are_not_overridden_by_old_atomic_flag(self):
        for flag in c.ROLE_FLAGS:
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as directory:
                transport = RoleTransport(reject_first=True, failed_flag=flag)
                client = c.legacy.MarketSummaryClient(Path(directory), transport, 8, prompt_root=c.PROMPTS)
                result = c.generate_market_summary(client, self.data(), 0)
                self.assertEqual('WITHHELD', result['verification']['status'])
                self.assertIsNone(result['summary'])

    def test_no_previous_forecast_or_target_does_not_create_fake_required_roles(self):
        data, _, _ = f.input_data()
        data['context']['summaryPromptVersion'] = c.ROLE_VERSION
        data['contextSha256'] = c.base.digest(c.base.canonical(data['context']))
        values = c._prepare(data)
        schema = c._schema(*values[:5])
        self.assertEqual([], schema['properties']['requiredClaims']['required'])
        self.assertNotIn('forecast', schema['properties']['claims']['items']['properties']['kind']['enum'])


if __name__ == '__main__':
    unittest.main()
