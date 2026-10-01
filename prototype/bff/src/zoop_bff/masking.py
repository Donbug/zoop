"""Personal-data masking for what administrators read (requirement 75: AI transcripts and dislike reasons).

Masking is applied when a record is *read*; the stored text is never rewritten. Patterns cover e-mail
addresses, Korean mobile/landline numbers, resident registration numbers, card numbers and bank account
numbers. The owner's own e-mail address and display name are replaced as well (when known).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
# 6 birth digits + 7 digits starting with 1-8 (the 7th digit encodes century and sex).
RRN = re.compile(r"(?<!\d)\d{6}[-\s]?[1-8]\d{6}(?!\d)")
CARD = re.compile(r"(?<!\d)(?:\d{4}[-\s]?){3}\d{4}(?!\d)|(?<!\d)3[47]\d{2}[-\s]?\d{6}[-\s]?\d{5}(?!\d)")
MOBILE = re.compile(r"(?<!\d)(?:\+82[-\s]?)?0?1[016-9][-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)")
LANDLINE = re.compile(r"(?<!\d)(?:\+82[-\s]?)?0?(?:2|[3-6]\d)[-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)")
# Bank accounts: dash-grouped digits or one long digit run (10-14 digits). Dates are skipped in ``_account``.
ACCOUNT = re.compile(r"(?<!\d)\d{2,6}(?:-\d{2,8}){1,3}(?!\d)|(?<!\d)\d{10,14}(?!\d)")
_DATE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")

TOKENS = {
    "email": "[이메일]",
    "phone": "[전화번호]",
    "rrn": "[주민등록번호]",
    "card": "[카드번호]",
    "account": "[계좌번호]",
    "name": "[이름]",
}
RULES = [
    "이메일 주소",
    "휴대전화·일반전화 번호",
    "주민등록번호",
    "카드번호",
    "계좌번호",
    "회원의 표시 이름·이메일",
]


def _account(match: re.Match[str]) -> str | None:
    text = match.group(0)
    digits = sum(c.isdigit() for c in text)
    if _DATE.match(text) or not 9 <= digits <= 16:
        return None
    return text


class Masker:
    """``mask(text)`` -> ``(masked text, replacements per kind)``. ``owner_*`` are the writer's own details."""

    def __init__(self, owner_email: str | None = None, owner_name: str | None = None):
        self._literals: list[tuple[str, re.Pattern[str]]] = []
        if owner_email:
            self._literals.append(("email", re.compile(re.escape(owner_email), re.IGNORECASE)))
        if owner_name and len(owner_name.strip()) >= 2:
            self._literals.append(("name", re.compile(re.escape(owner_name.strip()), re.IGNORECASE)))

    @staticmethod
    def _sub(kind: str, pattern: re.Pattern[str], text: str, counts: Counter[str], accept: Callable[[re.Match[str]], str | None] | None = None) -> str:
        def replace(match: re.Match[str]) -> str:
            if accept is not None and accept(match) is None:
                return match.group(0)
            counts[kind] += 1
            return TOKENS[kind]

        return pattern.sub(replace, text)

    def mask(self, text: str) -> tuple[str, Counter[str]]:
        counts: Counter[str] = Counter()
        for kind, pattern in self._literals:
            text = self._sub(kind, pattern, text, counts)
        text = self._sub("email", EMAIL, text, counts)
        text = self._sub("rrn", RRN, text, counts)
        text = self._sub("card", CARD, text, counts)
        text = self._sub("phone", MOBILE, text, counts)
        text = self._sub("phone", LANDLINE, text, counts)
        text = self._sub("account", ACCOUNT, text, counts, _account)
        return text, counts


def merge(counters: Iterable[Counter[str]]) -> dict[str, int]:
    total: Counter[str] = Counter()
    for counter in counters:
        total.update(counter)
    return dict(total)
