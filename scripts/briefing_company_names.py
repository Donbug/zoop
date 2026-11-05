"""Conservative input relevance, never ownership inference or a company-ID resolver.

Native S2/S3 still owns grounded identities. Korean particles are accepted, while
longer company/product names are not treated as occurrences of a shorter parent.
"""
import re
import unicodedata

VERSION = 'briefing-company-literal-v1'
PARTICLES = r'(?:에서는|에게는|으로는|에서도|에서|에게|으로|부터|까지|보다|은|는|이|가|을|를|과|와|의|에|로|도|만|측|등)'
WORD = r'A-Za-z0-9_가-힣'
# Distinct literal names, not a corporate-ownership catalogue. No link is added.
DISTINCT_NAMES = (
    ('네이버', ('네이버파이낸셜', '네이버 파이낸셜', '네이버클라우드', '네이버 클라우드')),
    ('NAVER', ('NAVER Financial', 'NAVER Cloud')),
    ('카카오', ('카카오톡', '카카오 톡', '카카오페이', '카카오 페이', '카카오뱅크', '카카오 뱅크', '카카오게임즈')),
    ('Kakao', ('Kakao Pay', 'Kakao Bank', 'Kakao Talk')),
    ('삼성전자', ('삼성전자서비스', '삼성전자 서비스')),
)


def pattern(alias):
    literal = r'\s+'.join(re.escape(s) for s in alias.split())
    return re.compile(r'(?<![' + WORD + r'])' + literal + r'(?=$|[^' + WORD + r']|' + PARTICLES + r'(?![' + WORD + r']))', re.I)


def matches(text, companies):
    text = unicodedata.normalize('NFKC', text)
    owners = {}
    for company in companies:
        for alias in [company['name'], *company['aliases']]:
            key = ' '.join(unicodedata.normalize('NFKC', alias).casefold().split())
            if len(key) >= 3:
                owners.setdefault(key, set()).add(company['companyId'])
    result = []
    for company in companies:
        for alias in [company['name'], *company['aliases']]:
            alias = unicodedata.normalize('NFKC', alias)
            key = ' '.join(alias.casefold().split())
            if len(key) < 3 or owners.get(key) != {company['companyId']}:
                continue
            occurrences = list(pattern(alias).finditer(text))
            if not occurrences:
                continue
            longer = [name for short, names in DISTINCT_NAMES if short.casefold() == key for name in names]
            if any(pattern(name).search(text) for name in longer):
                # A quoted media headline alone cannot resolve parent/subsidiary ambiguity.
                explicit_subject = any(re.match(r'(?:은|는|이|가|와|과|측)(?![' + WORD + r'])|\s*[,，:]|\s+(?:announced|said|signed|reported|launched|has|will)\b', text[m.end():], re.I)
                                       for m in occurrences)
                if not explicit_subject:
                    continue
            result.append(company['companyId'])
            break
    return result
