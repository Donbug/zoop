"""S2's verbatim geography -> S3's country context, never source rewriting or country inference.

Only assigned alpha-2 codes and the explicit, deliberately bounded aliases below resolve. Other names, regions and ambiguous
labels stay unresolved, not contradictory. Alias matching follows the catalogue convention: casefold + whitespace only.
Any code/alias or resolution-rule change MUST bump VERSION; the S3 job binding pins it.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

VERSION = "zoop-country-context-1"

# ISO 3166-1 assigned alpha-2 codes. No reserved/user-assigned codes (UK, EU, XK, ZZ), alpha-3 or inferred territories.
_CODES = frozenset("""
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ
CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR
GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO
JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ
MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA
RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR
TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW
""".split())

# An explicit registry, not fuzzy matching or a claim of exhaustive name coverage. Bare Korea/Congo/Georgia, continents,
# cities, abbreviations and demonyms are intentionally absent. Missing aliases preserve the original value as unknown.
_ALIASES = {
    "AE": ("United Arab Emirates", "아랍에미리트"),
    "AU": ("Australia", "호주", "오스트레일리아"),
    "BR": ("Brazil", "브라질"),
    "CA": ("Canada", "캐나다"),
    "CH": ("Switzerland", "스위스"),
    "CN": ("China", "People's Republic of China", "중국", "중화인민공화국"),
    "DE": ("Germany", "독일"),
    "ES": ("Spain", "스페인"),
    "FR": ("France", "프랑스"),
    "GB": ("United Kingdom", "United Kingdom of Great Britain and Northern Ireland", "영국"),
    "ID": ("Indonesia", "인도네시아"),
    "IN": ("India", "인도"),
    "IT": ("Italy", "이탈리아"),
    "JP": ("Japan", "일본"),
    "KP": ("North Korea", "Democratic People's Republic of Korea", "북한", "조선민주주의인민공화국"),
    "KR": ("South Korea", "Republic of Korea", "Korea, Republic of", "한국", "대한민국", "남한"),
    "MX": ("Mexico", "멕시코"),
    "MY": ("Malaysia", "말레이시아"),
    "NL": ("Netherlands", "네덜란드"),
    "NZ": ("New Zealand", "뉴질랜드"),
    "PH": ("Philippines", "필리핀"),
    "PL": ("Poland", "폴란드"),
    "QA": ("Qatar", "카타르"),
    "RU": ("Russia", "Russian Federation", "러시아"),
    "SA": ("Saudi Arabia", "Kingdom of Saudi Arabia", "사우디아라비아"),
    "SE": ("Sweden", "스웨덴"),
    "SG": ("Singapore", "싱가포르"),
    "TH": ("Thailand", "태국"),
    "TR": ("Türkiye", "Turkey", "튀르키예", "터키"),
    "TW": ("Taiwan", "대만"),
    "US": ("United States", "United States of America", "미국"),
    "VN": ("Vietnam", "Viet Nam", "베트남"),
    "ZA": ("South Africa", "남아프리카공화국"),
}
_LOOKUP = {" ".join(alias.casefold().split()): code for code, aliases in _ALIASES.items() for alias in (code, *aliases)}
_LOOKUP.update({code.casefold(): code for code in _CODES})


@dataclass(frozen=True)
class CountryContext:
    raw: tuple[str, ...]
    known: frozenset[str]
    unresolved: tuple[str, ...]


def resolve(values: Iterable[str]) -> CountryContext:
    """Resolve only whole explicit labels. Do not strip punctuation, split regions or consult publisher/HQ/URL information."""
    raw = tuple(sorted(set(values)))
    known, unresolved = set(), []
    for value in raw:
        code = _LOOKUP.get(" ".join(value.casefold().split()))
        if code is None:
            unresolved.append(value)
        else:
            known.add(code)
    return CountryContext(raw, frozenset(known), tuple(unresolved))
