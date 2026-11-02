#!/usr/bin/env python3
"""Read one approved non-fixture company, document set and evidence span through the public chatbot data path."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

SCHEMA = "zoop-chat-nonfixture-probe-1"
REPORT_SCHEMA = "zoop-chat-nonfixture-smoke-1"
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}")
KEYS = {"schemaVersion", "graphVersionId", "companyId", "evidenceId", "minimumDocuments"}


class SmokeError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_probe(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SmokeError("probe is not readable JSON") from error
    if not isinstance(value, dict) or set(value) != KEYS or value.get("schemaVersion") != SCHEMA:
        raise SmokeError("probe does not match the closed schema")
    for key in ("graphVersionId", "companyId", "evidenceId"):
        if not isinstance(value[key], str) or not ID.fullmatch(value[key]):
            raise SmokeError(f"{key} is invalid")
    if type(value["minimumDocuments"]) is not int or not 1 <= value["minimumDocuments"] <= 20:
        raise SmokeError("minimumDocuments must be between 1 and 20")
    return value


def base_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme not in ({"http", "https"} if loopback else {"https"}) or not parsed.netloc:
        raise SmokeError("base URL must be HTTPS (HTTP is allowed only on loopback)")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise SmokeError("base URL must contain only scheme and authority")
    return value.rstrip("/")


def get_json(opener, base: str, path: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(base + path, headers={"Accept": "application/json"}, method="GET")
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
            if response.status != 200 or len(raw) > 8 * 1024 * 1024:
                raise SmokeError(f"GET {path.split('?')[0]} returned an unusable response")
    except urllib.error.HTTPError as error:
        raise SmokeError(f"GET {path.split('?')[0]} returned HTTP {error.code}") from error
    except urllib.error.URLError as error:
        raise SmokeError(f"GET {path.split('?')[0]} failed") from error
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SmokeError(f"GET {path.split('?')[0]} returned invalid JSON") from error
    if not isinstance(value, dict):
        raise SmokeError(f"GET {path.split('?')[0]} returned a non-object")
    return value


def evaluate(probe: dict[str, Any], graph: dict[str, Any], documents: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    version = probe["graphVersionId"]
    company = probe["companyId"]
    evidence_id = probe["evidenceId"]
    failures: list[str] = []

    graph_metadata = graph.get("metadata") if isinstance(graph.get("metadata"), dict) else {}
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    if graph_metadata.get("graphVersion") != version:
        failures.append("graph_version_mismatch")
    if not any(isinstance(node, dict) and node.get("id") == company and node.get("kind") == "company" for node in nodes):
        failures.append("company_not_in_graph")
    if not any(isinstance(node, dict) and node.get("kind") == "issue" for node in nodes):
        failures.append("issue_not_in_graph")

    doc_metadata = documents.get("metadata") if isinstance(documents.get("metadata"), dict) else {}
    items = documents.get("items") if isinstance(documents.get("items"), list) else []
    if doc_metadata.get("graphVersion") != version:
        failures.append("document_version_mismatch")
    if len(items) < probe["minimumDocuments"]:
        failures.append("documents_below_minimum")
    quotes = [quote for item in items if isinstance(item, dict)
              for quote in (item.get("quotes") if isinstance(item.get("quotes"), list) else [])
              if isinstance(quote, dict)]
    if not any(quote.get("evidenceId") == evidence_id for quote in quotes):
        failures.append("evidence_not_in_company_documents")

    evidence_metadata = evidence.get("metadata") if isinstance(evidence.get("metadata"), dict) else {}
    if evidence.get("id") != evidence_id:
        failures.append("evidence_id_mismatch")
    if evidence_metadata.get("graphVersion") != version:
        failures.append("evidence_version_mismatch")
    if evidence.get("quoteVerified") is not True:
        failures.append("evidence_not_verified")
    if not isinstance(evidence.get("articleId"), str) or not isinstance(evidence.get("articleVersion"), str):
        failures.append("evidence_document_binding_missing")
    if not isinstance(evidence.get("eventIds"), list) or not evidence["eventIds"]:
        failures.append("evidence_event_binding_missing")

    return {
        "schemaVersion": REPORT_SCHEMA,
        "status": "passed" if not failures else "failed",
        "graphVersionId": version,
        "companyId": company,
        "evidenceId": evidence_id,
        "observed": {"nodes": len(nodes), "edges": len(edges), "documents": len(items), "quotes": len(quotes)},
        "failures": failures,
    }


def write_new(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, sort_keys=True, indent=2)
        output.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probe", type=Path)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if not 0.1 <= args.timeout <= 60:
            raise SmokeError("timeout must be between 0.1 and 60 seconds")
        probe = load_probe(args.probe)
        base = base_url(args.base_url)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        query = urllib.parse.urlencode({"mode": "all", "companyId": probe["companyId"], "depth": 3,
                                        "graphVersion": probe["graphVersionId"]})
        graph = get_json(opener, base, "/api/v1/graph?" + query, args.timeout)
        query = urllib.parse.urlencode({"graphVersion": probe["graphVersionId"], "limit": 20})
        documents = get_json(opener, base, "/api/v1/companies/" + urllib.parse.quote(probe["companyId"], safe="")
                             + "/documents?" + query, args.timeout)
        query = urllib.parse.urlencode({"graphVersion": probe["graphVersionId"], "companyId": probe["companyId"]})
        evidence = get_json(opener, base, "/api/v1/evidence/" + urllib.parse.quote(probe["evidenceId"], safe="")
                            + "?" + query, args.timeout)
        report = evaluate(probe, graph, documents, evidence)
        write_new(args.output, report)
    except (SmokeError, FileExistsError, OSError) as error:
        print(f"invalid: {error}", file=sys.stderr)
        return 64
    print(json.dumps({"status": report["status"], "graphVersionId": report["graphVersionId"],
                      "observed": report["observed"]}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
