"""Strict static Korea portal selectors. No script, iframe, attachment or media requests."""
from __future__ import annotations

import copy
import hashlib
import re
from datetime import date
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

from lxml import etree, html

from .ingestion_contracts import IngestionFailure

ROUTES = {
    "policy-news": ("/news/policyNewsList.do", "/news/policyNewsView.do"),
    "press-release": ("/briefing/pressReleaseList.do", "/briefing/pressReleaseView.do"),
    "clarifications": ("/briefing/actuallyList.do", "/briefing/actuallyView.do"),
}
BODY_XPATH = '//*[contains(concat(" ",normalize-space(@class)," ")," article_body ")]/*[contains(concat(" ",normalize-space(@class)," ")," view_cont ")]'
NOTICE = "이 자료는 텍스트에 한하여 공공누리 제1유형(출처표시)의 조건에 따라 이용할 수 있습니다."
BADGE = "공공누리 공공저작물 자유이용허락 1유형 출처표시"
WARNING = "Native canonical text may retain rights/contact boilerplate; not semantic evidence or gold. No media/attachment/iframe coverage."


def fail(code):
    raise IngestionFailure(code)


def text(node):
    return " ".join(node.text_content().split())


def tree(raw):
    try:
        return html.document_fromstring(raw.decode("utf-8", errors="strict"), parser=html.HTMLParser(no_network=True))
    except (UnicodeError, ValueError, etree.LxmlError):
        fail("portal_html_invalid")


def day(value):
    if not re.fullmatch(r"\d{4}[.-]\d{2}[.-]\d{2}", value):
        fail("portal_date_invalid")
    try:
        return date.fromisoformat(value.replace(".", "-")).isoformat()
    except ValueError:
        fail("portal_date_invalid")


def listing_url(config, channel, page):
    return config.listing_origin + ROUTES[channel][0] + "?" + urlencode({"pageIndex": page, "startDate": config.from_day, "endDate": config.through_day})


def article_id(url, config, channel, *, listing=False):
    parts = urlsplit(url)
    origins = {config.listing_origin, config.article_origin}
    if f"{parts.scheme}://{parts.netloc}" not in origins or parts.path != ROUTES[channel][1] or parts.fragment:
        fail("portal_link_invalid")
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if len(dict(pairs)) != len(pairs):
        fail("portal_link_invalid")
    query = dict(pairs)
    allowed = {"newsId"}
    if listing:
        allowed |= {"pageIndex", "repCodeType", "repCode", "startDate", "endDate", "srchWord", "period"}
        for key, value in query.items():
            if key in {"repCodeType", "repCode", "srchWord", "period"} and value:
                fail("portal_link_invalid")
            if key == "startDate" and value != config.from_day or key == "endDate" and value != config.through_day:
                fail("portal_link_invalid")
            if key == "pageIndex" and not re.fullmatch(r"[1-9]\d{0,5}", value):
                fail("portal_link_invalid")
    if set(query) - allowed or not re.fullmatch(r"\d{9}", query.get("newsId", "")):
        fail("portal_link_invalid")
    return query["newsId"]


def parse_listing(raw, config, channel, page, page_size=None):
    dom = tree(raw)
    current = dom.xpath('//input[@name="pageIndex"]/@value')
    if current != [str(page)]:
        fail("portal_page_nonadvancing")
    for name, expected in (("startDate", config.from_day), ("endDate", config.through_day)):
        if dom.xpath(f'//form[@id="mainForm"]//input[@name="{name}"]/@value') != [expected]:
            fail("portal_period_unbound")
    lists = dom.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," list_type ")]/ul')
    results = dom.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," sch_brief ")]/*[contains(concat(" ",normalize-space(@class)," ")," result ")]/strong')
    if len(lists) != 1 or len(results) != 1 or not re.fullmatch(r"\d+", text(results[0])):
        fail("portal_pagination_ambiguous")
    total = int(text(results[0]))
    entries = lists[0].xpath('./li')
    rows = lists[0].xpath('./li/a')
    empty = (len(entries) == 1 and entries[0].get("class") == "no_data"
             and text(entries[0]) == "등록된 정보가 없습니다."
             and (len(entries[0]) == 0 or
                  (len(entries[0]) == 1 and entries[0][0].tag == "span" and not entries[0][0].attrib
                   and len(entries[0][0]) == 0 and not (entries[0].text or "").strip()
                   and not (entries[0][0].tail or "").strip())))
    if total == 0:
        if not empty or rows:
            fail("portal_pagination_ambiguous")
    elif len(entries) != len(rows) or not rows:
        fail("portal_pagination_ambiguous")
    if page > 1 and (not page_size or len(rows) > page_size):
        fail("portal_pagination_ambiguous")
    candidates = []
    for row in rows:
        identifier = article_id(urljoin(config.listing_origin, row.get("href", "")), config, channel, listing=True)
        titles = row.xpath('.//strong')
        source = row.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," source ")]/span')
        if len(titles) != 1 or len(source) != 2 or not text(titles[0]) or not text(source[1]):
            fail("portal_listing_metadata_missing")
        published = day(text(source[0]))
        if not config.from_day <= published <= config.through_day:
            fail("portal_listing_date_outside_period")
        candidates.append({"newsId": identifier, "channel": channel, "title": text(titles[0]), "publisher": text(source[1]),
                           "publicationDay": published, "url": config.article_origin + ROUTES[channel][1] + "?newsId=" + identifier})
    dates = [c["publicationDay"] for c in candidates]
    if dates != sorted(dates, reverse=True):
        fail("portal_listing_not_chronological")
    pagers = dom.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," paging ")]')
    if len(pagers) > 1:
        fail("portal_pagination_ambiguous")
    if total == 0:
        if page != 1 or pagers and pagers[0].xpath('.//a'):
            fail("portal_pagination_ambiguous")
        return candidates, False
    if not pagers:
        fail("portal_pagination_ambiguous")
    active = pagers[0].xpath('./span[contains(concat(" ",normalize-space(@class)," ")," num ") and contains(concat(" ",normalize-space(@class)," ")," on ")]/a')
    if (len(active) != 1 or text(active[0]) != str(page) or active[0].get("title") != "현재페이지"
            or active[0].get("onclick", "").strip() != "return false;"):
        fail("portal_pagination_ambiguous")
    rendered = set()
    for link in pagers[0].xpath('.//a'):
        if link is active[0]:
            continue
        action = link.get("onclick", "")
        match = re.fullmatch(r"\s*pageLink\(([1-9]\d*)\)\s*;?\s*(?:return false;?)?\s*", action)
        if link.get("href") != "#pageLink" or match is None:
            fail("portal_pagination_ambiguous")
        target = int(match.group(1))
        classes = set(link.get("class", "").split())
        if link.getparent().tag == "span" and "num" in link.getparent().get("class", "").split():
            if text(link) != str(target) or target == page:
                fail("portal_pagination_ambiguous")
        elif not classes.intersection({"first", "prev", "next", "last"}):
            fail("portal_pagination_ambiguous")
        rendered.add(target)
    if rendered and max(rendered) > page and page + 1 not in rendered:
        fail("portal_pagination_ambiguous")
    size = page_size if page > 1 else len(rows)
    offset = (page - 1) * size
    if total < offset + len(rows) or len(rows) != min(size, total - offset):
        fail("portal_pagination_ambiguous")
    more = total > page * size
    if more != (page + 1 in rendered):
        fail("portal_pagination_ambiguous")
    return candidates, more


def validate_article(fetched, candidate, config):
    channel, identifier = candidate["channel"], candidate["newsId"]
    if fetched.media_type != "text/html" or article_id(fetched.final_url, config, channel) != identifier:
        fail("portal_article_identity_mismatch")
    dom = tree(fetched.body)
    canonicals = dom.xpath('//link[@rel="canonical"]/@href')
    if len(canonicals) != 1 or article_id(canonicals[0], config, channel) != identifier:
        fail("portal_canonical_mismatch")
    heads = dom.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," article_head ")]')
    bodies = dom.xpath(BODY_XPATH)
    if len(heads) != 1 or len(bodies) != 1:
        fail("portal_inline_body_missing")
    titles = heads[0].xpath('./h1')
    details = heads[0].xpath('./div[contains(concat(" ",normalize-space(@class)," ")," info ")]')
    spans = details[0].xpath('./span') if len(details) == 1 else []
    if len(titles) != 1 or len(spans) != 2 or not text(spans[1]):
        fail("portal_article_metadata_missing")
    if text(titles[0]) != candidate["title"] or text(spans[1]) != candidate["publisher"] or day(text(spans[0])) != candidate["publicationDay"]:
        fail("portal_article_metadata_changed")
    rights = bodies[0].xpath('.//div[contains(concat(" ",normalize-space(@class)," ")," law_copy_wrap ")]//div[@class="kogl"]/div[@class="guide"]')
    if len(rights) != 1:
        fail("portal_item_license_missing")
    types = rights[0].xpath('./div[contains(concat(" ",normalize-space(@class)," ")," type ")]')
    if len(types) != 1:
        fail("portal_item_not_kogl1_text")
    images = types[0].xpath('./a[@href="https://www.kogl.or.kr/info/license.do"]/img')
    notices = types[0].xpath('./span')
    if (len(images) != 1 or len(notices) != 1 or images[0].get("alt") != BADGE
            or urlsplit(images[0].get("src", "")).path != "/images/common/open_type_01.png"
            or text(notices[0]) != NOTICE):
        fail("portal_item_not_kogl1_text")
    body = copy.deepcopy(bodies[0])
    for node in body.xpath('.//script|.//style|.//iframe|.//figure|.//img|.//video|.//audio|.//*[contains(concat(" ",normalize-space(@class)," ")," law_copy_wrap ") or contains(concat(" ",normalize-space(@class)," ")," remark_briefing ")]'):
        if node.getparent() is not None:
            node.getparent().remove(node)
    substance = text(body)
    # Explicitly conservative, not a semantic classifier: attachment notices and identifiable contacts alone do not qualify.
    without_contacts = re.sub(r"[^\s@]+@[^\s@]+|\(?0\d{1,2}\)?[- )]\d{3,4}-\d{4}|문의[^.\n]{0,120}|담당[^.\n]{0,120}", "", substance)
    if len(without_contacts.strip()) < 120 or len(re.findall(r"[가-힣]", without_contacts)) < 60:
        fail("portal_no_substantive_inline_body_or_contact_only")
    return {"license": "KOGL-type-1-text-only", "notice": NOTICE, "canonicalUrl": canonicals[0],
            "bodySha256": hashlib.sha256(fetched.body).hexdigest(), "qualityWarnings": [WARNING],
            "contactPresent": bool(re.search(r"문의|담당|@|\d{2,3}-\d{3,4}-\d{4}", substance))}
