"""Citation preparation works in a fresh interpreter without provider packages."""
import subprocess
import sys
from pathlib import Path
import unittest


class SourceOfflineImportTest(unittest.TestCase):
    def test_exact_source_facts_without_site_packages_or_provider_imports(self):
        program = r'''
import sys
sys.path.insert(0, sys.argv[1])
import briefing_impact_evidence_plan as plan
import briefing_s3_citation_context as context
text = 'Company A😀 may open in 2028, subject to agreement.'
source = {'id':'e','documentId':'d','documentVersion':'sha256-'+'a'*64,
          'title':'Source','url':'https://example.test','publishedAt':'2026-10-21T00:00:00Z',
          'bodySha256':'a'*64}
fact = plan.excerpt(source, text, 'may open')
assert text[fact['start']:fact['end']] == fact['quote'] == text
evidence = {**source, 'quote':text, 'bodyContext':{'text':text,'start':0,'end':len(text)}}
facts = context.source_facts(evidence, ['may open'])
assert facts[0]['quote'] == text
assert not {'dotenv','httpx','pydantic','zoop_ai_pipeline.live_runtime'} & sys.modules.keys()
'''
        result = subprocess.run(
            [sys.executable, '-S', '-c', program, str(Path(__file__).resolve().parents[1])],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
