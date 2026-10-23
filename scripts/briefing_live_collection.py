#!/usr/bin/env python3
"""Bounded local company-news discovery and same-response body/clock capture.

No scheduler, publication or model call. Search dates are discovery hints only.
The fetched publisher HTML supplies both body and the verified publication clock.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import urllib.request
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import briefing_replay as base
import briefing_publication_clock as clock

VERSION = "zoop-local-collection-v1"

def key_values(path):
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise base.ReplayError("private_0600_key_file_required")
    values = {}
    for line in path.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            k, sep, v = line.strip().removeprefix("export ").partition("=")
            if sep:
                if k in values: raise base.ReplayError("duplicate_key")
                values[k] = v.strip().strip("\"'")
    return values

def search(output, key, company, start, end, limit, timeout=30):
    payload = {"query": company["name"]+" company business earnings investment contract announcement",
        "type":"fast", "category":"news", "numResults":limit,
        "startPublishedDate":start, "endPublishedDate":end,
        "contents":{"text":False,"highlights":False,"summary":None}}
    rid = base.digest(base.canonical(payload))
    receipt = output/"search"/(rid+".receipt.json")
    response = output/"search"/(rid+".response.json")
    pending = output/"search"/(rid+".pending.json")
    if receipt.exists():
        saved = base.strict_load(base.regular(receipt))
        if saved["status"] != "complete": return {"company":company,"status":saved["status"],"results":[]}
        raw = base.regular(response)
        if base.digest(raw) != saved["responseSha256"]: raise base.ReplayError("search_response_changed")
        return {"company":company,"status":"complete","results":base.strict_load(raw).get("results",[])}
    if pending.exists(): raise base.ReplayError("unresolved_search_request_not_retransmitted")
    base.save_json(pending, {"provider":"exa","requestDigest":rid,"payload":payload,"startedAt":base.now()})
    state = {"requestDigest":rid,"status":"unknown","completedAt":None}
    try:
        req=urllib.request.Request("https://api.exa.ai/search",data=base.canonical(payload),
            headers={"Content-Type":"application/json","x-api-key":key},method="POST")
        opener=urllib.request.build_opener(base.NoRedirect())
        with opener.open(req,timeout=timeout) as res:
            raw=res.read(3_000_001)
            if len(raw)>3_000_000: raise base.ReplayError("search_response_too_large")
            if key.encode() in raw: raise base.ReplayError("credential_echo")
        parsed=base.strict_load(raw)
        base.write_once(response,raw)
        state.update(status="complete",responseSha256=base.digest(raw),results=len(parsed.get("results",[])))
        return {"company":company,"status":"complete","results":parsed.get("results",[])}
    except Exception as exc:
        state.update(status="failed_or_unknown",errorType=type(exc).__name__)
        return {"company":company,"status":state["status"],"results":[]}
    finally:
        state["completedAt"]=base.now();base.save_json(receipt,state)

def fetch_host(args, output, candidates):
    # Reuse the existing team's public/robots/size-limited transport; do not alter its source.
    from investmate.crawl_types import FetchPolicy
    from investmate.fetching import WebFetcher
    from zoop_ai_pipeline.ingestion_parsers import prepare
    host=urlsplit(candidates[0]["url"]).hostname
    policy=FetchPolicy(allowed_domains=[host],timeout_seconds=12.0,max_requests=len(candidates)*3+4,
        max_response_bytes=3_000_000,max_total_bytes=30_000_000,min_interval_seconds=0.5)
    fetcher=WebFetcher(policy);results=[]
    try:
        for candidate in candidates:
            rid=base.digest(candidate["url"].encode())
            receipt=output/"pages"/(rid+".json")
            if receipt.exists():
                results.append(base.strict_load(base.regular(receipt)));continue
            record={"url":candidate["url"],"status":"not_acquired","observedAt":base.now(),
                "companyAssociations":candidate["companies"]}
            try:
                res=fetcher.fetch(candidate["url"],kind="page")
                if not clock.same_page(res.url,candidate["url"]):
                    raise base.ReplayError("redirect_not_original_article")
                raw=res.data
                stamp=base.now()
                html_sha=base.digest(raw)
                base.write_once(output/"html"/(html_sha+".html"),raw)
                state,published,declarations=clock.declaration_status(raw,res.url)
                if state!="verified_timestamp": raise base.ReplayError("publisher_time_"+state)
                if not (clock.aware(args.window_from)<clock.aware(published)<=clock.aware(args.discovery_to)):
                    raise base.ReplayError("publisher_time_outside_window")
                prepared=prepare(raw,"text/html",None)
                body=prepared["text"]
                if len(body.strip())<80: raise base.ReplayError("body_insufficient")
                document={"documentId":"news-"+rid,"sourceKind":"news","sourceId":host,
                    "url":candidate["url"],"title":candidate["title"],"body":body,
                    "bodySha256":base.digest(body.encode()),"bodyScope":"same_response_native_article",
                    "bodyAcquiredAt":stamp,"collectedAt":stamp,"originalPublicationVerified":True,
                    "allowModelSend":False,"rightsStatus":"unconfirmed","requiresReviewBeforeAnalysis":True,
                    "companyAssociations":candidate["companies"],
                    "capture":{"htmlSha256":html_sha,"publishedAt":published,"checkedAt":stamp,
                        "declarations":declarations,"finalUrl":res.url,"httpStatus":200,
                        "bodyParser":"zoop-native-parsers-1","sameResponseBodyAndClock":True}}
                base.save_json(output/"documents"/(rid+".json"),document)
                record.update(status="acquired",documentId=document["documentId"],htmlSha256=html_sha)
            except Exception as exc:
                record.update(status="excluded",reason=str(exc) if isinstance(exc,base.ReplayError)
                    else getattr(exc,"code",type(exc).__name__))
            base.save_json(receipt,record);results.append(record)
    finally: fetcher.close()
    return results

def run(args):
    output=Path(args.output).resolve();base.private_dir(output)
    for name in ["search","pages","html","documents"]:base.private_dir(output/name)
    companies=base.strict_load(base.regular(Path(args.companies)))["companies"]
    companies=[{"companyId":c.get("company_id",c.get("companyId")),"name":c["name"]}
        for c in companies]
    plan={"schemaVersion":VERSION,"windowFrom":args.window_from,"discoveryTo":args.discovery_to,
        "companies":companies,"perCompanyLimit":args.per_company_limit,
        "authorizationRef":args.authorization_ref,"maximumUrls":len(companies)*args.per_company_limit,
        "marketWideCoverageProven":False}
    base.save_json(output/"collection-plan.json",plan)
    keys=key_values(Path(args.search_key_file))
    with ThreadPoolExecutor(max_workers=3) as pool:
        searches=list(pool.map(lambda c:search(output,keys["EXA_API_KEY"],c,args.window_from,
            args.discovery_to,args.per_company_limit),companies))
    candidates={}
    for result in searches:
        for entry in result["results"]:
            url=entry.get("url")
            try: clock.public_url(url)
            except Exception: continue
            if urlsplit(url).scheme!="https": continue
            row=candidates.setdefault(url,{"url":url,"title":entry.get("title") or url,"companies":[]})
            if result["company"] not in row["companies"]: row["companies"].append(result["company"])
    base.save_json(output/"discovery.json",{"searches":searches,"candidates":list(candidates.values())})
    hosts={}
    for c in candidates.values():hosts.setdefault(urlsplit(c["url"]).hostname,[]).append(c)
    outcomes=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(lambda x:fetch_host(args,output,x),hosts.values()):outcomes.extend(result)
    docs=[base.strict_load(base.regular(f)) for f in sorted((output/"documents").glob("*.json"))]
    raw=b"".join(base.canonical(d)+b"\n" for d in docs)
    base.write_once(output/"sources.jsonl",raw);source_sha=base.digest(raw)
    records=[]
    for d in docs:
        c=d["capture"];records.append({"schemaVersion":"zoop-publication-clock-v1",
            "documentId":d["documentId"],"sourceFileSha256":source_sha,"bodySha256":d["bodySha256"],
            "url":d["url"],"status":"verified_timestamp","publishedAt":c["publishedAt"],
            "checkedAt":c["checkedAt"],"htmlSha256":c["htmlSha256"],"declarations":c["declarations"],
            "finalUrl":c["finalUrl"],"httpStatus":200,"meaning":"Same response captured with body before local cutoff"})
    base.save_json(output/"clocks.json",{"schemaVersion":"zoop-publication-clock-registry-v1",
        "sourceFileSha256":source_sha,"records":records})
    cutoff=base.now()
    round_={"date":datetime.fromisoformat(cutoff).astimezone(ZoneInfo("Asia/Seoul")).date().isoformat(),"edition":args.edition,
        "window":{"from":args.window_from,"to":cutoff,"openStart":False},
        "localCollection":{"schemaVersion":VERSION,"manualValidation":True,"discoveryTo":args.discovery_to,
            "sourceFileSha256":source_sha,"collectionPlanSha256":base.digest(base.canonical(plan)),
            "collectedBeforeCutoff":True,"productionAuthorized":False}}
    base.save_json(output/"round-spec.json",round_)
    summary={"status":"COMPLETE" if docs else "NO_ELIGIBLE_SOURCE","documents":len(docs),"urls":len(candidates),
        "searchRequests":len(searches),"searchFailures":sum(r["status"]!="complete" for r in searches),
        "outcomes":outcomes,"round":round_,"newModelCalls":0}
    base.save_json(output/"collection-summary.json",summary)
    return summary

def parser():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ["output","companies","search-key-file","window-from","discovery-to","authorization-ref"]:
        p.add_argument("--"+name,required=True)
    p.add_argument("--edition",choices=["morning","evening"],default="evening")
    p.add_argument("--per-company-limit",type=int,choices=range(1,4),default=2)
    return p

if __name__=="__main__":
    try:
        value=run(parser().parse_args())
        print(json.dumps({k:v for k,v in value.items() if k!="outcomes"},ensure_ascii=False),flush=True)
    except Exception as exc:
        print(json.dumps({"status":"FAILED","code":str(exc) if isinstance(exc,base.ReplayError) else type(exc).__name__}),flush=True)
        raise SystemExit(1)
