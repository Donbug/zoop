#!/usr/bin/env python3
"""Run one approved NAVER API HUB contract probe and write content-free evidence.

The request uses a fixed public query, follows no redirects, ignores process proxies,
and reads at most 1 MiB. Credentials come only from the environment. The evidence
contains no query, result, endpoint, credential, header, or response body.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SCHEMA = "zoop-chat-web-provider-preflight-1"
PROVIDER = "naver-api-hub-webkr"
ENDPOINT = "https://naverapihub.apigw.ntruss.com/search/v1/webkr"
FIXED_QUERY = "주식 용어"
MAX_RESPONSE_BYTES = 1024 * 1024
COMMIT = re.compile(r"[0-9a-f]{40}")
SLUG = re.compile(r"[a-z0-9][a-z0-9._-]{1,63}")
KEYS = {
    "schemaVersion", "candidateCommit", "provider", "credentialRevision",
    "observedAt", "status", "httpStatus", "itemCount", "responseBytes",
    "redirectFollowed", "responseContractObserved",
}


class PreflightError(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _credential(env: dict[str, str], name: str) -> str:
    value = env.get(name, "")
    if not 5 <= len(value) <= 512 or any(ord(char) < 0x21 or ord(char) > 0x7e for char in value):
        raise PreflightError(f"set a valid {name}")
    return value


def _base(candidate: str, credential_revision: str, observed_at: str) -> dict[str, Any]:
    if not COMMIT.fullmatch(candidate):
        raise PreflightError("candidate commit must be a lowercase 40-character Git commit")
    if not SLUG.fullmatch(credential_revision):
        raise PreflightError("credential revision must be a lowercase operational slug")
    return {
        "schemaVersion": SCHEMA,
        "candidateCommit": candidate,
        "provider": PROVIDER,
        "credentialRevision": credential_revision,
        "observedAt": observed_at,
        "status": "failed",
        "httpStatus": None,
        "itemCount": 0,
        "responseBytes": 0,
        "redirectFollowed": False,
        "responseContractObserved": False,
    }


def probe(env: dict[str, str], candidate: str, credential_revision: str,
          open_url: Callable[..., Any] | None = None,
          now: Callable[[], datetime] | None = None) -> dict[str, Any]:
    observed = (now or (lambda: datetime.now(timezone.utc)))().isoformat()
    evidence = _base(candidate, credential_revision, observed)
    client_id = _credential(env, "ZOOP_CHAT_WEB_NAVER_API_HUB_CLIENT_ID")
    client_secret = _credential(env, "ZOOP_CHAT_WEB_NAVER_API_HUB_CLIENT_SECRET")
    query = urllib.parse.urlencode({"query": FIXED_QUERY, "display": 1, "start": 1, "format": "json"})
    request = urllib.request.Request(ENDPOINT + "?" + query, headers={
        "Accept": "application/json",
        "User-Agent": "zoop-chat-preflight/1",
        "X-NCP-APIGW-API-KEY-ID": client_id,
        "X-NCP-APIGW-API-KEY": client_secret,
    }, method="GET")
    opener = open_url or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open
    try:
        with opener(request, timeout=7) as response:
            evidence["httpStatus"] = response.status
            body = response.read(MAX_RESPONSE_BYTES + 1)
            evidence["responseBytes"] = min(len(body), MAX_RESPONSE_BYTES + 1)
            if response.status != 200 or len(body) > MAX_RESPONSE_BYTES:
                return evidence
            value = json.loads(body)
            items = value.get("items") if isinstance(value, dict) else None
            if not isinstance(items, list) or len(items) > 1:
                return evidence
            if any(not isinstance(item, dict) or not isinstance(item.get("title"), str)
                   or not isinstance(item.get("link"), str) for item in items):
                return evidence
            evidence["itemCount"] = len(items)
            evidence["responseContractObserved"] = True
            evidence["status"] = "passed"
            return evidence
    except urllib.error.HTTPError as error:
        evidence["httpStatus"] = error.code
        return evidence
    except (OSError, UnicodeError, json.JSONDecodeError):
        return evidence


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PreflightError(f"cannot read web preflight evidence: {error}") from None
    if not isinstance(value, dict) or set(value) != KEYS:
        raise PreflightError("web preflight evidence keys differ")
    if (value["schemaVersion"] != SCHEMA or not isinstance(value["candidateCommit"], str)
            or not COMMIT.fullmatch(value["candidateCommit"])):
        raise PreflightError("web preflight evidence identity is invalid")
    if (value["provider"] != PROVIDER or not isinstance(value["credentialRevision"], str)
            or not SLUG.fullmatch(value["credentialRevision"])):
        raise PreflightError("web preflight provider binding is invalid")
    if not isinstance(value["observedAt"], str):
        raise PreflightError("web preflight observedAt is invalid")
    try:
        observed = datetime.fromisoformat(value["observedAt"].replace("Z", "+00:00"))
    except ValueError:
        raise PreflightError("web preflight observedAt is invalid") from None
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise PreflightError("web preflight observedAt must include an offset")
    if (value["status"] != "passed" or value["responseContractObserved"] is not True
            or value["redirectFollowed"] is not False or value["httpStatus"] != 200):
        raise PreflightError("web preflight did not pass")
    if type(value["itemCount"]) is not int or not 0 <= value["itemCount"] <= 1:
        raise PreflightError("web preflight itemCount is invalid")
    if type(value["responseBytes"]) is not int or not 0 <= value["responseBytes"] <= MAX_RESPONSE_BYTES:
        raise PreflightError("web preflight responseBytes is invalid")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as out:
        json.dump(value, out, ensure_ascii=False, indent=2, sort_keys=True)
        out.write("\n")
    Path(out.name).replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--credential-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--i-approved-provider-call", action="store_true")
    args = parser.parse_args(argv)
    if not args.i_approved_provider_call:
        print("stopped: pass --i-approved-provider-call after the single external call is approved")
        return 2
    try:
        evidence = probe(dict(os.environ), args.candidate_commit, args.credential_revision)
        _write(args.output, evidence)
    except PreflightError as error:
        print("stopped:", error)
        return 2
    print("web preflight:", evidence["status"])
    return 0 if evidence["status"] == "passed" else 2


if __name__ == "__main__":
    sys.exit(main())
