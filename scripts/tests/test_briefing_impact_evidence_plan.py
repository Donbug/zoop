import unittest
import briefing_impact_evidence_plan as plan

class EvidencePlanTest(unittest.TestCase):
    def source(self):
        return {'id':'e','documentId':'d','documentVersion':'sha256-'+'a'*64,'title':'T','url':'https://example.test',
                'publishedAt':'2026-10-21T00:00:00Z','bodySha256':'a'*64}

    def test_exact_paragraph_preserves_unicode_terms_and_source_identity(self):
        body='Intro.\nCompany A😀 may deploy up to 84 units in 2028, subject to agreement.\nEnd.'
        q=plan.excerpt(self.source(),body,'up to 84')
        self.assertEqual(body[q['start']:q['end']],q['quote'])
        self.assertIn('subject to agreement',q['quote']);self.assertNotIn('effect',q)

    def test_nonunique_unavailable_and_clipped_anchors_are_refused(self):
        for body,anchor in [('A. A.','A.'),('A.','B.'),('Company A plans up to','plans up to')]:
            with self.assertRaises(ValueError):plan.excerpt(self.source(),body,anchor)

    def test_multiline_heading_does_not_replace_a_complete_fact(self):
        q=plan.excerpt(self.source(),'Heading\nCompany A plans a conditional dividend.\nNext.','conditional dividend')
        self.assertEqual(q['quote'],'Company A plans a conditional dividend.')

if __name__=='__main__':unittest.main()
