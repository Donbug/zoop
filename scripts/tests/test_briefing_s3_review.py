"""Offline bridge regressions: public/native version identity and exact source-bound offsets."""
import unittest
try:
    import briefing_s3_review as review
except ModuleNotFoundError:
    review=None

@unittest.skipIf(review is None,'native pipeline dependencies not installed')
class ReviewBridgeTest(unittest.TestCase):
    def source(self):
        return {('doc','a'*64):{'quote':'A😀 contract signed.','bodyContext':{'text':'A😀 contract signed.','start':100,'end':119}}}

    def test_lossless_version_wrapper(self):
        self.assertEqual(review.native_version('sha256-'+'a'*64),'a'*64)
        with self.assertRaises(RuntimeError):review.native_version('unrelated-version')

    def test_null_offsets_are_resolved_from_literal_context(self):
        q={'documentId':'doc','documentVersion':'sha256-'+'a'*64,'quote':'contract signed.','start':None,'end':None}
        fixed=review.normalize_answer({'supporting':[q]},self.source())['supporting'][0]
        self.assertEqual(fixed['start'],3)
        self.assertEqual(fixed['end'],19)
        self.assertEqual(q['documentVersion'],'sha256-'+'a'*64)
        self.assertIsNone(q['start'])

    def test_wrong_document_or_quote_cannot_be_normalized(self):
        q={'documentId':'other','documentVersion':'a'*64,'quote':'contract signed.','start':None,'end':None}
        with self.assertRaises(KeyError):review.normalize_answer(q,self.source())
        q['documentId']='doc';q['quote']='not in the preserved text'
        with self.assertRaises(review.CitationFailure):review.normalize_answer(q,self.source())

    def test_ambiguous_quote_or_wrong_supplied_offsets_are_refused(self):
        sources=self.source();sources[('doc','a'*64)]['bodyContext']['text']='repeat repeat'
        q={'documentId':'doc','documentVersion':'a'*64,'quote':'repeat','start':None,'end':None}
        with self.assertRaises(review.CitationFailure):review.normalize_answer(q,sources)
        q.update(quote='contract signed.',start=0,end=16)
        with self.assertRaises(review.CitationFailure):review.normalize_answer(q,self.source())
