"""The Java reader's frozen question policy must stay identical to the native owner.

Read literals with AST so bare tooling CI needs neither model SDKs nor pydantic.
"""
import ast
import hashlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]


class NativeImpactPolicyParityTest(unittest.TestCase):
    def test_java_policy_matches_native_identity_questions_criteria_and_thresholds(self):
        source=ROOT/'ai/pipeline/src/zoop_ai_pipeline/live_jev.py'
        literals={}
        for node in ast.parse(source.read_text()).body:
            if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
                try:literals[node.targets[0].id]=ast.literal_eval(node.value)
                except (ValueError,TypeError):pass
        c=literals
        identity={'revision':c['ADAPTER_REVISION'],'api':c['API'],'model':c['MODEL'],
            'policy':{'choiceProbability':c['CHOICE_PROBABILITY'],'choiceConfidence':c['CHOICE_CONFIDENCE'],
                      'distributionTolerance':c['DISTRIBUTION_TOLERANCE']},
            'task':c['TASK'],'typeText':c['TYPE_TEXT'],'claimCriteria':c['CLAIM_CRITERIA'],'claimTemplates':c['CLAIM_TEMPLATES'],
            'targetQuestion':c['TARGET_QUESTION'],'targetCriteria':c['TARGET_CRITERIA'],
            'effectQuestion':c['EFFECT_QUESTION'],'effectCriteria':c['EFFECT_CRITERIA'],
            'options':[c[k] for k in ['CLAIM_OPTIONS','REVERSIBLE_OPTIONS','TARGET_OPTIONS','EFFECT_OPTIONS']]}
        raw=json.dumps(identity,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        policy=json.loads((ROOT/'api/src/main/resources/briefing/native-impact-policy-v1.json').read_text())
        self.assertEqual(hashlib.sha256(raw).hexdigest(),policy['adapterIdentity'])
        for field in ['task','targetQuestion','targetCriteria','effectQuestion','effectCriteria']:
            self.assertEqual(identity[field],policy[field])


if __name__=='__main__':unittest.main()
