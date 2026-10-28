"""Review counterexamples through real runners and immutable, synthetic provider recordings."""
import copy
import multiprocessing
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))
import briefing_reading_evaluation as evaluation

reading = evaluation.reading
company = reading.company
base = evaluation.base


def response(answer):
    return 200, base.canonical({'id': 'authored-local-only', 'status': 'completed',
        'usage': {'input_tokens': 10, 'output_tokens': 5},
        'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': base.canonical(answer).decode()}]}]})


def reading_transport(encoded):
    request = base.strict_load(encoded)
    data = base.strict_load(request['input'].encode())
    stage = request['text']['format']['name']
    if stage.endswith('generation'):
        return response({'companies': [
            {'companyId': t['companyId'], **{k: {'text': t['companyId']+' 확인 조건', 'evidenceIds': t['sourceIds']}
                                           for k in ('brief', 'watch', 'change')}} for t in data['frozen']['targets']]})
    if stage.endswith('verification'):
        return response({'checks': [{'companyId': t['companyId'], 'supported': True, 'reason': '합성 원문 일치'}
                                    for t in data['frozen']['targets']]})
    return response({'checks': [{'companyId': c['companyId'], 'supportedA': True, 'supportedB': True,
        **{k: 'tie' for k in evaluation.CRITERIA}, 'reason': '동일 단일 이슈'} for c in data['companies']]})


def concurrent_runner(args, entered, release, pipe):
    def transport(encoded):
        if not entered.is_set():
            entered.set()
            if not release.wait(15):
                raise RuntimeError('test owner timeout')
        return reading_transport(encoded)
    try:
        pipe.send(('ok', evaluation.run(args, transport)['status']))
    except Exception as error:
        pipe.send(('error', repr(error)))
    finally:
        pipe.close()


class Review309Test(unittest.TestCase):
    def evaluation_fixture(self, root, multi=False):
        source = root/'source'
        base.private_dir(source)
        fulls, rows = [], []
        for rid in ('r1', 'r2'):
            targets = [{'companyId': cid, 'issueIds': ['issue-'+cid], 'sourceIds': ['source-'+cid]} for cid in ('A', 'B', 'C')]
            full = {'roundId': rid, 'edition': 'evening', 'cutoff': '2026-10-22T08:30:00Z',
                'resultVersion': 'full-'+rid, 'status': 'PASS', 'draft': {'companies': [{'companyId': t['companyId']} for t in targets]},
                'frozen': {'targets': targets, 'sources': {'source-'+c: {'quote': c+' 고정 원문'} for c in ('A', 'B', 'C')}}}
            fulls.append(full)
            rows.append({'roundId': rid, 'status': 'PASS', 'frozen': reading.freeze(full, reading.V2),
                'draft': {'companies': [{'companyId': c, **{k: {'text': c+' 개선 문안', 'evidenceIds': ['source-'+c]}
                                                         for k in ('brief', 'fact', 'watch', 'background', 'change')}} for c in ('A', 'B', 'C')]}})
        bundle = {'presentationEnrichment': {'companyOutlookLayer': {'rounds': fulls},
            'companyReadingLayer': {'schemaVersion': reading.SCHEMA_V2, 'rounds': rows}}}
        base.write_once(source/'bundle-v2.json', base.canonical(bundle))
        return SimpleNamespace(improved=str(source), output=str(root/'output'), round_id='r1', multi_round=multi,
            authorization_ref='authored-only', key_file=None, max_calls=4, execute=True), bundle

    def test_both_modes_hold_process_lock_before_first_request_through_completion(self):
        ctx = multiprocessing.get_context('fork')
        for multi in (False, True):
            with self.subTest(multi=multi), tempfile.TemporaryDirectory() as temp:
                args, _ = self.evaluation_fixture(Path(temp), multi)
                entered, release = ctx.Event(), ctx.Event()
                parent, child = ctx.Pipe(duplex=False)
                worker = ctx.Process(target=concurrent_runner, args=(args, entered, release, child))
                worker.start()
                try:
                    self.assertTrue(entered.wait(10))
                    other = copy.copy(args); other.round_id = 'r2'
                    sent = []
                    with self.assertRaises(FileExistsError):
                        evaluation.run(other, lambda encoded: sent.append(encoded))
                    self.assertEqual([], sent)
                    self.assertEqual(1, len(list((Path(args.output)/'calls').glob('*.pending.json'))))
                    release.set()
                    self.assertTrue(parent.poll(15))
                    self.assertEqual(('ok', 'COMPLETE'), parent.recv())
                    worker.join(5)
                    self.assertEqual(0, worker.exitcode)
                    self.assertFalse((Path(args.output)/'.reading-evaluation.lock').exists())
                finally:
                    release.set()
                    worker.join(5)
                    if worker.is_alive():
                        worker.terminate(); worker.join()
                    parent.close(); child.close()

    def test_unknown_call_releases_owner_but_keeps_reservation_without_resending(self):
        with tempfile.TemporaryDirectory() as temp:
            args, _ = self.evaluation_fixture(Path(temp))
            sent = []
            def unknown(encoded):
                sent.append(encoded)
                raise RuntimeError('authored lost response')
            with self.assertRaisesRegex(base.ReplayError, 'transport_unknown'):
                evaluation.run(args, unknown)
            self.assertFalse((Path(args.output)/'.reading-evaluation.lock').exists())
            with self.assertRaisesRegex(base.ReplayError, 'unresolved_paid_reservation'):
                evaluation.run(args, unknown)
            self.assertEqual(1, len(sent))

    def test_ambiguous_company_prose_cannot_claim_three_issues_in_either_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            args, bundle = self.evaluation_fixture(Path(temp))
            layer = bundle['presentationEnrichment']['companyReadingLayer']
            for row in layer['rounds']:
                for t in row['frozen']['targets']:
                    t['issueIds'] = ['shared', 'second', 'third']
            (Path(args.improved)/'bundle-v2.json').write_bytes(base.canonical(bundle))
            for multi in (False, True):
                args.multi_round = multi
                with self.assertRaisesRegex(ValueError, 'evaluation_three_'):
                    evaluation.run(args, lambda _: self.fail('no provider request permitted'))
            self.assertFalse((Path(args.output)/'calls').exists())

    def test_selected_issue_is_bound_to_both_order_reversed_requests_and_resume(self):
        for multi in (False, True):
            with self.subTest(multi=multi), tempfile.TemporaryDirectory() as temp:
                args, _ = self.evaluation_fixture(Path(temp), multi)
                requests = []
                def capture(encoded):
                    requests.append(base.strict_load(encoded))
                    return reading_transport(encoded)
                proof = evaluation.run(args, capture)
                judges = [base.strict_load(r['input'].encode()) for r in requests
                          if r['text']['format']['name'] == 'company_reading_pairwise']
                self.assertEqual(2, len(judges))
                for judge in judges:
                    self.assertEqual({('A', 'issue-A'), ('B', 'issue-B'), ('C', 'issue-C')},
                                     {(c['companyId'], c['issueId']) for c in judge['companies']})
                self.assertEqual(judges[0]['companies'][0]['A'], judges[1]['companies'][0]['B'])
                self.assertEqual(evaluation.SAMPLE_POLICY, proof['identity']['samplePolicy'])
                self.assertEqual(0, evaluation.run(args, lambda _: self.fail('completed result must be reused'))['newPaidCalls'])

    def test_v1_to_v4_runner_keeps_old_prompt_and_receipt_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); baseline = root/'baseline'; base.private_dir(baseline/'company-prompts')
            source = {'documentId': 'doc', 'evidenceId': 'e', 'bodySha256': 'a'*64, 'quote': 'A가 도입을 계획한다.',
                      'publishedAt': '2026-10-22T07:00:00Z'}
            row = {'roundId': 'r', 'date': '2026-10-22', 'edition': 'evening', 'marketEnrichment': {'cutoff': '2026-10-22T08:30:00Z'}}
            effective = {'resultSha256': 'b'*64, 'selected': [{'issueId': 'i', 'companyLinks': [{'companyId': 'A', 'name': 'A'}], 'sources': [source]}],
                         'result': {'items': [{'issueId': 'i', 'claims': [{'text': '도입 계획', 'evidenceIds': ['e']}]}]}}
            metadata = {'documentId': 'doc', 'title': '합성 원문', 'url': 'https://example.test/source'}
            sources = root/'sources.jsonl'; sources.write_bytes(base.canonical(metadata)+b'\n')
            previous = {'roundId': 'r', 'status': 'PASS', 'date': row['date'], 'edition': row['edition'],
                        'frozen': company.freeze(row, effective, {'doc': metadata}, []), 'attempts': []}
            old = {'schemaVersion': company.SCHEMA, 'rounds': [previous], 'receipts': []}
            bundle = {'sourceFileSha256': base.digest(sources.read_bytes()),
                      'presentationEnrichment': {'rounds': [row], 'companyOutlookLayer': old}, 'briefingRecovery': {'rounds': [dict(effective, roundId='r')]}}
            base.write_once(baseline/'bundle-v2.json', base.canonical(bundle))
            for name in ('generation.md', 'verification.md'):
                base.write_once(baseline/'company-prompts'/name, base.regular(company.PROMPTS/name))
            base.private_dir(baseline/'calls'); base.write_once(baseline/'calls/old-recording.json', b'{"authored":"preserved"}')
            before = {str(p.relative_to(baseline)): p.read_bytes() for p in baseline.rglob('*') if p.is_file()}
            args = SimpleNamespace(baseline=str(baseline), sources=str(sources), output=str(root/'output'), date=['2026-10-22'],
                prompt_version='company-outlook-v4', max_calls=2, run_id='authored-v4', authorization_ref='authored-only', execute=True, key_file=None)
            sent = []
            def transport(encoded):
                request = base.strict_load(encoded); sent.append(request)
                if request['text']['format']['name'].endswith('generation'):
                    stmt = {'text': 'A 도입 일정 확인', 'evidenceIds': ['e']}
                    return response({'companies': [{'companyId': 'A', 'assessment': 'watch', 'impact': stmt, 'outlook': stmt,
                        'conditions': [stmt], 'risks': [stmt], 'comparison': {**stmt, 'status': 'unavailable', 'previousResultVersion': None}}]})
                return response({'checks': [{'companyId': 'A', 'supported': True, 'reason': '합성 원문 일치'}]})
            proof = company.run(args, transport)
            self.assertEqual(1, proof['pass']); self.assertEqual(2, len(sent))
            output = Path(args.output)
            for path, content in before.items():
                self.assertEqual(content, (baseline/path).read_bytes())
                if path != 'bundle-v2.json':
                    self.assertEqual(content, (output/path).read_bytes())
            for name, request in zip(('generation.md', 'verification.md'), sent):
                current = base.regular(company.PROMPTS.with_name('company-outlook-v4')/name)
                self.assertEqual(current, (output/'company-prompts/company-outlook-v4'/name).read_bytes())
                self.assertEqual(current.decode(), request['instructions'])
            saved = base.strict_load(base.regular(output/'bundle-v2.json'))['presentationEnrichment']['companyOutlookLayer']
            self.assertEqual(old, saved['previousRuns'][0])
            self.assertEqual(0, company.run(args, lambda _: self.fail('completed runner must not resend'))['newPaidCalls'])


if __name__ == '__main__':
    unittest.main()
