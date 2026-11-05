"""Literal preparation only; company roles and importance still require native verification."""
import copy
import unittest
from briefing_company_names import catalogue_companies, matches


class NewsLanguageTests(unittest.TestCase):
    def companies(self):
        return catalogue_companies({'companies': [
            {'company_id': 'NASDAQ:AAPL', 'name': 'Apple', 'aliases': [], 'ticker': 'AAPL'},
            {'company_id': 'NASDAQ:GOOGL', 'name': 'Alphabet', 'aliases': ['Google', '구글'], 'ticker': 'GOOGL'},
            {'company_id': 'KRX:005380', 'name': '현대자동차', 'aliases': ['Hyundai Motor'], 'ticker': '005380'},
            {'company_id': 'KRX:000270', 'name': '기아', 'aliases': ['Kia'], 'ticker': '000270'}]})

    def test_existing_korean_short_names_and_particles_are_not_silently_dropped(self):
        companies = self.companies()
        self.assertEqual(['NASDAQ:AAPL'], matches('애플이 합성 제품을 공개했다.', companies))
        self.assertEqual(['NASDAQ:GOOGL'], matches('구글은 합성 서비스를 출시했다.', companies))
        self.assertEqual(['KRX:005380', 'KRX:000270'], matches('현대차·기아, 합성 계약 발표', companies))

    def test_source_projection_preserves_the_input_and_existing_ids(self):
        raw = {'companies': [{'company_id': 'NASDAQ:AAPL', 'name': 'Apple', 'aliases': ['Apple Inc.'], 'ticker': 'AAPL'}]}
        before = copy.deepcopy(raw)
        projected = catalogue_companies(raw)
        self.assertEqual(before, raw)
        self.assertEqual(['Apple Inc.', '애플'], projected[0]['aliases'])
        self.assertEqual('NASDAQ:AAPL', projected[0]['companyId'])
        self.assertNotIn('companyId', raw['companies'][0])

    def test_no_company_or_ownership_is_created_by_a_localized_alias(self):
        unrelated = catalogue_companies({'companies': [{'company_id': 'SYNTHETIC', 'name': '사과', 'aliases': [], 'ticker': None}]})
        self.assertEqual([], matches('애플이 합성 제품을 공개했다.', unrelated))
        self.assertEqual(['SYNTHETIC'], [c['companyId'] for c in unrelated])

    def test_two_character_ascii_aliases_are_still_refused_except_the_exact_kt_issuer(self):
        companies = [{'companyId': 'synthetic', 'name': 'Synthetic', 'aliases': ['AI', 'MS', 'LG']}]
        self.assertEqual([], matches('AI MS LG', companies))
        self.assertEqual(['KRX:030200'], matches('KT가 합성 계약을 발표했다.',
            [{'companyId': 'KRX:030200', 'name': 'KT', 'aliases': []}]))
        self.assertEqual([], matches('KT&G 합성 실적 발표',
            [{'companyId': 'KRX:030200', 'name': 'KT', 'aliases': []}]))

    def test_compound_words_and_ambiguous_alias_owners_are_not_matches(self):
        self.assertEqual([], matches('구글링 애플망고 기아차량이라는 합성 단어', self.companies()))
        companies = [{'companyId': 'one', 'name': '합성기업1', 'aliases': ['구글']},
                     {'companyId': 'two', 'name': '합성기업2', 'aliases': ['구글']}]
        self.assertEqual([], matches('구글은 합성 서비스를 발표했다.', companies))

    def test_parent_product_and_subsidiary_guards_survive_localization(self):
        companies = [{'companyId': 'naver', 'name': '네이버', 'aliases': []},
                     {'companyId': 'kakao', 'name': '카카오', 'aliases': []}]
        self.assertEqual([], matches('네이버파이낸셜 합성 계약, 카카오톡 합성 이모티콘', companies))
        self.assertEqual([], matches('현대차 그룹 합성 발표', self.companies()))


if __name__ == '__main__': unittest.main()
