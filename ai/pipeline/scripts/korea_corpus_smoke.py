#!/usr/bin/env python3
"""Synthetic loopback CLI -> native collection -> ingestion -> unchanged export, no external/model calls."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PIPELINE)]

from scripts.collection_smoke import LocalSite
from zoop_ai_pipeline import korea_corpus as corpus
from zoop_ai_pipeline.ingestion_contracts import byte_hash, canonical
from zoop_ai_pipeline.korea_portal import BADGE, NOTICE, ROUTES

SUBSTANCE = "정부는 지역 산업의 생산 기반을 강화하기 위한 지원 계획을 발표했습니다. 이번 계획은 관계 기관의 협의를 거쳐 마련되었으며 지역 기업의 투자 여건을 개선하고 필요한 행정 절차를 안내합니다. 신청 방법과 지원 대상은 공식 안내에 따라 확인할 수 있으며 세부 추진 일정도 함께 공개했습니다."


def article(site, identifier, *, channel="policy-news", title=None, publisher="합성기관", publisher_link=True,
            license_type=1, notice=True, body=SUBSTANCE, canonical_id=None, shell=""):
    title = title or "합성 기사 " + identifier
    rights = (f'<div class="law_copy_wrap"><div class="kogl"><div class="guide"><div class="type">'
              f'<a href="https://www.kogl.or.kr/info/license.do"><img src="/images/common/open_type_0{license_type}.png" alt="{BADGE if license_type == 1 else "공공누리 4유형"}"></a>'
              f'<span>{NOTICE.replace("텍스트에 한하여 공공누리 제1유형(출처표시)의 조건", "<strong>텍스트에 한하여 공공누리 제1유형(출처표시)의 조건</strong>") if notice else ""}</span>'
              '</div><div class="info"><p>사진·이미지·동영상은 해당 저작권자의 별도 허락이 필요합니다.</p>'
              '<a href="/etc/copyRight.do">저작권정책</a><span>담당자 안내</span></div></div></div></div>')
    publisher_span = f'<a class="gotosite">{publisher}</a>' if publisher_link else publisher
    return f'<html><head><link rel="canonical" href="{site.url(ROUTES[channel][1])}?newsId={canonical_id or identifier}">{shell}</head><body><div class="article_wrap"><div class="article_head"><h1>{title}</h1><div class="info"><span>2026.10.23</span><span>{publisher_span}</span></div></div><div class="article_body"><div class="view_cont"><p>{body}</p>{rights}</div></div></div></body></html>'.encode()


def listing(ids, *, channel="policy-news", page=1, more=False, total=None, publisher="합성기관"):
    rows = (''.join(f'<li><a href="{ROUTES[channel][1]}?newsId={i}"><strong>합성 기사 {i}</strong><span class="source"><span>2026.10.23</span><span>{publisher}</span></span></a></li>' for i in ids)
            if ids else '<li class="no_data"><span>등록된 정보가 없습니다.</span></li>')
    count = total if total is not None else (page * len(ids) + (1 if more else 0))
    current = f'<span class="num on"><a href="#pageLink" onclick="return false;" class="on" title="현재페이지">{page}</a></span>' if ids else ''
    paging = current + (f'<span class="num"><a href="#pageLink" onclick="pageLink({page + 1}); return false;" title="{page + 1}페이지">{page + 1}</a></span>' if more else '')
    return f'<html><body><form id="mainForm"><input name="pageIndex" value="{page}"><input name="startDate" value="2026-10-01"><input name="endDate" value="2026-10-23"></form><div class="sch_brief"><div class="result">검색결과 총 <strong>{count}</strong>건</div></div><div class="list_type"><ul>{rows}</ul></div><div class="paging">{paging}</div></body></html>'.encode()


def config(root, site, **changes):
    root.mkdir(parents=True, exist_ok=True)
    rights = root / "rights.json"
    rights.write_text(canonical({"synthetic": True, "permission": "synthetic loopback fixture only; no external rights"}))
    excluded = root / "exclusions.json"
    excluded.write_text(canonical({"schemaVersion": "zoop-korea-exclusions-1", "newsIds": ["100000004"]}))
    value = {"schemaVersion": "zoop-korea-corpus-1", "planId": "synthetic-portal", "stateDir": str(root / "corpus"),
        "fromDay": "2026-10-01", "throughDay": "2026-10-23", "listingOrigin": site.url(""), "articleOrigin": site.url(""), "exactHosts": ["127.0.0.1"],
        "channels": [{"name": "policy-news", "maxPages": 3, "maxDocuments": 10}], "maxListingPages": 3, "maxCandidates": 20, "maxDocuments": 10,
        "policy": {"schemaVersion": "zoop-collection-policy-1", "userAgent": "ZoopSyntheticCorpus/1.0", "timeoutSeconds": 5, "maxTotalSeconds": 120,
                   "maxRedirects": 0, "maxRequests": 60, "maxResponseBytes": 100000, "maxTotalBytes": 2000000, "minIntervalSeconds": 0.0,
                   "allowedMediaTypes": ["text/html"], "syntheticLoopback": True},
        "grant": {"grantId": "synthetic-text", "revision": "synthetic-1", "sourceId": "korea-portal", "enabled": True, "rights": "known",
                  "allowedOperations": ["read", "store", "quote-display"], "recipients": [], "purposes": [], "evidence": ["Synthetic fixture authored for this test"], "expiresAt": None},
        "rightsEvidence": {"path": str(rights), "sha256": byte_hash(rights.read_bytes())},
        "exclusionManifest": {"path": str(excluded), "sha256": byte_hash(excluded.read_bytes())}, **changes}
    path = root / "config.json"
    path.write_text(canonical(value))
    return value, path


def cli(path, command="run", expected=0):
    result = subprocess.run([sys.executable, "-m", "zoop_ai_pipeline.korea_corpus_cli", command, "--config", str(path)],
                            cwd=PIPELINE, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, timeout=180)
    assert result.returncode == expected, (result.returncode, result.stdout.decode(), result.stderr.decode())
    return json.loads(result.stdout)


def smoke(root):
    site = LocalSite()
    try:
        site.route("/robots.txt", b"User-agent: *\nAllow: /\n", content_type="text/plain")
        arrival = ["100000005", "100000003", "100000002", "100000001", "100000004", "100000005"]
        site.route(ROUTES["policy-news"][0], listing(arrival))
        # LocalSite routes by path; the hook selects the body from the actual requested newsId.
        def serve():
            from urllib.parse import parse_qs, urlsplit
            identifier = parse_qs(urlsplit(site.log[-1]["path"]).query)["newsId"][0]
            site.routes[ROUTES["policy-news"][1]]["body"] = article(site, identifier, license_type=4 if identifier == "100000002" else 1,
                                                                                    body="문의 담당자 02-1234-5678 담당@example.invalid" if identifier == "100000003" else SUBSTANCE)
        site.route(ROUTES["policy-news"][1], hook=serve)
        value, path = config(root, site)
        result = cli(path)
        assert result["counts"] == {"exported": 2, "refused": 2, "failed": 0, "unknown": 0, "pending": 0}, result
        assert result["duplicates"] == 1 and result["exclusions"] == 1
        state_root = Path(value["stateDir"])
        package_bytes = (state_root / "PACKAGE.json").read_bytes()
        package = json.loads(package_bytes)
        assert [doc["candidate"]["newsId"] for doc in package["documents"]] == ["100000001", "100000005"]
        assert [item["newsId"] for item in package["dispositions"]] == ["100000002", "100000003"]
        files = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        data = json.loads((state_root / "STATE.json").read_bytes())
        data["items"] = {i: data["items"][i] for i in arrival if i in data["items"]}
        item_order, state_before = list(data["items"]), canonical(data)
        assert item_order == ["100000005", "100000003", "100000002", "100000001"]
        validated = corpus.Config.model_validate(value)
        assert canonical(corpus.package(validated, data)).encode() == package_bytes
        assert list(data["items"]) == item_order and canonical(data) == state_before
        before = len(site.log)
        assert cli(path) == result and len(site.log) == before
        replay_bytes = (state_root / "PACKAGE.json").read_bytes()
        assert cli(path, "status") == result and len(site.log) == before
        status_bytes = canonical(corpus.status(validated)).encode()
        assert package_bytes == replay_bytes == status_bytes
        assert files == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        doc = package["documents"][0]
        exported = json.loads((Path(value["stateDir"]) / doc["exportFile"]).read_bytes())
        assert exported["observation"]["collection"]["network"] == "synthetic_loopback"
        assert exported["observation"]["collection"]["published"]["precision"] == "day"
        assert exported["observation"]["publisher"] == "합성기관"
        assert SUBSTANCE in exported["document"]["text"] and NOTICE in exported["document"]["text"]
        assert doc["nativeBodySha256"] == exported["observation"]["collection"]["bodySha256"]
        assert doc["rights"]["qualityWarnings"]
        assert before == 6, site.log  # robots, listing, one native GET per nonexcluded unique article
        return {"status": "passed", "syntheticLoopback": True, "externalRequests": 0, "modelCalls": 0,
                "observedRequests": before, "counts": result["counts"], "checks": ["actual CLI/single-GET native collection/ingestion/export", "KOGL4 and contact-only refusal", "exclusion and duplicate no-fetch", "resume and read-only status zero additional requests", "whole PACKAGE byte identity across initial run, replay and read-only status", "stable documents/dispositions ordering without input, state or body mutation", "native day precision, hashes, attribution and boilerplate warning"]}
    finally:
        site.close()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zoop-korea-synthetic-") as root:
        print(canonical(smoke(Path(root).resolve())))
