"""Source-bound citation context: no live calls and no inferred direction."""
import unittest
import briefing_s3_citation_context as context


class CitationContextTest(unittest.TestCase):
    def source(self, text, quote, base=100):
        return {'id':'e','documentId':'doc','documentVersion':'sha256-'+'a'*64,
                'title':'Source','url':'https://example.test','publishedAt':'2026-10-22T00:00:00Z',
                'quote':quote,'bodyContext':{'text':text,'start':base,'end':base+len(text)}}

    def test_subject_action_and_conditions_stay_in_one_exact_paragraph(self):
        text='cut fragment\n\nCompany A announced the project. It may open in 2028, subject to final agreement.\n\nunfinished'
        e=self.source(text,'It may open in 2028, subject to final agreement.')
        f=context.source_facts(e,[e['quote']])[0]
        self.assertEqual(f['quote'],'Company A announced the project. It may open in 2028, subject to final agreement.')
        self.assertEqual(text[f['start']-100:f['end']-100],f['quote'])

    def test_abstention_still_has_literal_facts_without_effect_labels(self):
        e=self.source('fragment\n\nCompany A plans equipment for approximately $10 in 2028.\n\ncut', 'Company A plans equipment for approximately $10 in 2028.')
        case={'basis':{'evidence':[e],'companies':[{'id':'test','name':'Company A'}]}}
        facts=context.expanded_facts(case,{'impacts':[{'supporting':[],'opposing':[]}]})
        self.assertEqual(len(facts),1)
        self.assertNotIn('effect',facts[0]);self.assertIn('approximately',facts[0]['quote'])

    def test_contract_qualification_is_kept_even_on_a_separate_line(self):
        e=self.source('Company A expands up to 84 MW.\nThe companies said the projects remain subject to final agreements.\ncut', 'Company A expands up to 84 MW.',0)
        facts=context.source_facts(e,[e['quote']])
        self.assertEqual(len(facts),2);self.assertIn('subject to final agreements',facts[1]['quote'])

    def test_clipped_anchor_cannot_be_presented_as_complete(self):
        for text,anchor in [('partial company plans 2028.','company plans 2028.'),('fragment\n\nCompany plans 2028, subject to','Company plans 2028, subject to')]:
            with self.assertRaisesRegex(RuntimeError,'paragraph_incomplete'):
                context.source_facts(self.source(text,anchor),[anchor])

    def test_duplicate_and_fabricated_quotes_fail_closed(self):
        for text,anchor in [('fragment\nA signs.\nA signs.','A signs.'),('fragment\nA signs.','B signs.')]:
            with self.assertRaisesRegex(RuntimeError,'anchor_not_unique'):
                context.source_facts(self.source(text,anchor),[anchor])

    def test_omitted_board_subject_is_retained_from_adjacent_complete_sentence(self):
        e=self.source("cut\n\nThe Board approved a new class for January 2027.\n\nMeta's Board followed the committee recommendation. More reasons include:\ncut", 'The Board approved a new class for January 2027.')
        facts=context.source_facts(e,[e['quote']])
        full=context.named_context(e,facts,['Meta'])
        self.assertIn("Meta's Board",full[0]['quote'])
        self.assertIn('January 2027',full[0]['quote'])
        self.assertNotIn('More reasons',full[0]['quote'])

    def test_korean_company_name_with_particle_is_not_dropped(self):
        e=self.source('fragment\n\n삼성SDS는 공공 고객을 확보했다.\ncut', '공공 고객을 확보했다.')
        facts=context.source_facts(e,[e['quote']])
        self.assertEqual(context.named_context(e,facts,['삼성SDS']),facts)

    def test_unicode_offsets_preserve_exact_source(self):
        e=self.source('fragment\n\nA😀 company may open in 2028.\ncut','A😀 company may open in 2028.')
        fact=context.source_facts(e,[e['quote']])[0]
        self.assertEqual(fact['end']-fact['start'],len(fact['quote']))


if __name__=='__main__':unittest.main()
