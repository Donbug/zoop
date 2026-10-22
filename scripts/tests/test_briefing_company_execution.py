"""Partial reruns preserve prior publications; cached completion must identify this request."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('company_execution_review',Path(__file__).parents[1]/'briefing_company_outlook.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)

class CompanyExecutionTest(unittest.TestCase):
    def timeline(self):
        rows=[{'roundId':f'r{i}','date':day,'edition':edition,'marketEnrichment':{'cutoff':cutoff}}
              for i,(day,edition,cutoff) in enumerate([
                ('2026-10-07','evening','2026-10-07T08:30:00Z'),
                ('2026-10-08','morning','2026-10-08T00:20:00Z'),
                ('2026-10-08','evening','2026-10-08T08:30:00Z')])]
        old={r['roundId']:{'roundId':r['roundId'],'status':'PASS','resultVersion':r['roundId'],
             'frozen':{'cutoff':r['marketEnrichment']['cutoff'],'history':[f'r{j}' for j in range(i)]}}
             for i,r in enumerate(rows)}
        return rows,old

    def frozen(self,row,recovery,metadata,history):
        return {'cutoff':row['marketEnrichment']['cutoff'],'history':[r['roundId'] for r in history]}

    def test_oct8_only_reuses_oct7_as_current_history_and_preserves_all_rounds(self):
        rows,old=self.timeline()
        with patch.object(c,'freeze',self.frozen):
            result,count=c.company_plan(rows[1:],rows,old,{r['roundId']:{} for r in rows},{})
        self.assertEqual(['r0','r1','r2'],[r['roundId'] for r in result]);self.assertEqual(0,count)

    def test_changed_predecessor_requires_the_later_rounds_before_any_paid_work(self):
        rows,old=self.timeline();old['r0']['frozen']['history']=['changed']
        with patch.object(c,'freeze',self.frozen):
            with self.assertRaisesRegex(ValueError,'dependent_rounds_must_be_selected'):
                c.company_plan(rows[:1],rows,old,{r['roundId']:{} for r in rows},{})

    def test_a_preserved_round_cannot_silently_keep_changed_inputs(self):
        rows,old=self.timeline();old['r0']['frozen']['history']=['changed']
        with patch.object(c,'freeze',self.frozen):
            with self.assertRaisesRegex(ValueError,'preserved_round_input_changed'):
                c.company_plan(rows[1:],rows,old,{r['roundId']:{} for r in rows},{})

    def test_completion_reuse_rejects_changed_dates_baseline_and_prompts_without_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);baseline=root/'base';baseline.mkdir();output=root/'out';output.mkdir(mode=0o700)
            sources=root/'sources.jsonl';sources.write_text('{"documentId":"authored"}\n')
            rows=[{'roundId':'r'+day,'date':'2026-10-'+day,'marketEnrichment':{'cutoff':'2026-10-'+day+'T00:20:00Z'}} for day in ('07','08')]
            bundle={'sourceFileSha256':c.base.digest(sources.read_bytes()),'presentationEnrichment':{'rounds':rows}}
            raw=c.base.canonical(bundle);(baseline/'bundle-v2.json').write_bytes(raw)
            args=c.parser().parse_args(['--baseline',str(baseline),'--output',str(output),'--sources',str(sources),
                 '--authorization-ref','local:authored','--run-id','authored','--date','2026-10-07','--date','2026-10-08','--max-calls','12','--execute'])
            identity=c.execution_identity(args,raw,sources.read_bytes(),rows)
            (output/'company-execution.json').write_bytes(c.base.canonical(identity))
            (output/'bundle-v2.json').write_bytes(b'{}')
            proof=c.base.canonical({'status':'COMPLETE','bundleSha256':c.base.digest(b'{}')})
            (output/'company-proof.json').write_bytes(proof)
            with patch.object(c,'assess',side_effect=AssertionError('paid work entered')):
                self.assertEqual(0,c.run(args)['newPaidCalls'])
                changed=copy.copy(args);changed.date=['2026-10-08']
                with self.assertRaisesRegex(ValueError,'completed_request_identity_changed'):c.run(changed)
                (baseline/'bundle-v2.json').write_bytes(raw+b'\n')
                with self.assertRaisesRegex(ValueError,'completed_request_identity_changed'):c.run(args)
                (baseline/'bundle-v2.json').write_bytes(raw)
                prompts=root/'prompts';prompts.mkdir();(prompts/'generation.md').write_text('changed prompt')
                with patch.object(c,'PROMPTS',prompts):
                    with self.assertRaisesRegex(ValueError,'completed_request_identity_changed'):c.run(args)
            self.assertEqual(proof,(output/'company-proof.json').read_bytes())

if __name__=='__main__':unittest.main()
