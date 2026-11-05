import unittest
import briefing_company_names as names


class CompanyNameTests(unittest.TestCase):
    companies = [
        {'companyId': 'naver', 'name': '네이버', 'aliases': ['NAVER']},
        {'companyId': 'samsung', 'name': '삼성전자', 'aliases': []},
        {'companyId': 'kakao', 'name': '카카오', 'aliases': ['Kakao']},
    ]

    def test_subsidiary_product_and_whitespace_variants_do_not_become_parent(self):
        for text in ('네이버파이낸셜은 심의 당사자다.', 'NAVER Financial signed a contract.',
                     '네이버 파이낸셜은 별도 법인이다.', '삼성전자서비스가 수상했다.',
                     '카카오톡 채널에서 정부 이모티콘을 배포한다.', '카카오 뱅크는 실적을 발표했다.'):
            with self.subTest(text=text):
                self.assertEqual([], names.matches(text, self.companies))

    def test_case_and_korean_particles_keep_actual_company_mentions(self):
        for text, expected in [('네이버는 계약했다.', 'naver'), ('네이버가 투자했다.', 'naver'),
                               ('삼성전자의 공장', 'samsung'), ('삼성전자는 공급한다.', 'samsung'),
                               ('NAVER signed a contract.', 'naver'), ('Kakao reported revenue.', 'kakao')]:
            self.assertEqual([expected], names.matches(text, self.companies))

    def test_quoted_parent_headline_does_not_override_specific_party(self):
        text = '한국경제TV “두나무-네이버 합병 초읽기” 보도 관련. 네이버파이낸셜-두나무 심의 결과는 미확정이다.'
        self.assertEqual([], names.matches(text, self.companies))
        self.assertEqual(['naver'], names.matches('네이버는 네이버파이낸셜에 대한 별도 계약을 공시했다.', self.companies))

    def test_an_explicit_catalogue_alias_remains_separate_and_ambiguous_alias_is_not_guessed(self):
        expanded = self.companies + [{'companyId': 'financial', 'name': '네이버파이낸셜', 'aliases': []}]
        self.assertEqual(['financial'], names.matches('네이버파이낸셜은 계약했다.', expanded))
        duplicate = self.companies + [{'companyId': 'other', 'name': '다른기업', 'aliases': ['NAVER']}]
        self.assertEqual([], names.matches('NAVER signed a contract.', duplicate))


if __name__ == '__main__':
    unittest.main()
