#!/usr/bin/env python3
"""레지스트리와 목표 OpenAPI에서 팀용 xlsx·마크다운과 실패 목록을 만든다."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "docs/system"
OUT = SYSTEM / "out"
API_OUT = ROOT / "docs/api/out"
METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(x) for x in value)
    return str(value)


def md(value) -> str:
    return cell(value).replace("|", "\\|").replace("\n", "<br>")


def table(headers: list[str], rows) -> str:
    return "| " + " | ".join(headers) + " |\n| " + " | ".join("---" for _ in headers) + " |\n" + "".join(
        "| " + " | ".join(md(x) for x in row) + " |\n" for row in rows)


def slug(value: str) -> str:
    # 원본의 잘못된 ID도 안전한 파일명으로 보존하되 정상 ID와 충돌하지 않는다.
    return "".join(c if c.isalnum() or c in "-_" else f"~{ord(c):02x}" for c in value)


def source_label(source: dict | None) -> str:
    if not source:
        return ""
    return f"{source['path']}:{source['row']} ({source['rowUnit']})"


def source_link(source: dict, depth: int = 4) -> str:
    return f"[{source_label(source)}]({'../' * depth}{source['path']})"


def operations(document: dict):
    for path, item in document.get("paths", {}).items():
        for method, op in item.items():
            if method in METHODS:
                yield path, method, op


def deref(document: dict, value: dict) -> dict:
    target = value.get("$ref", "")
    if not target.startswith("#/"):
        return value
    current = document
    for part in target[2:].split("/"):
        current = current[part.replace("~1", "/").replace("~0", "~")]
    return current


def schema_label(value: dict) -> str:
    if "$ref" in value:
        return value["$ref"].rsplit("/", 1)[-1]
    union = value.get("oneOf", value.get("anyOf", []))
    if union:
        return " / ".join(schema_label(v) for v in union)
    kind = value.get("type", "object")
    if kind == "array":
        return f"{schema_label(value.get('items', {}))}[]"
    text = cell(kind)
    if "enum" in value:
        text += " {" + cell(value["enum"]) + "}"
    if "format" in value:
        text += f" ({value['format']})"
    return text


def schema_md(value: dict) -> str:
    if "$ref" in value:
        name = value["$ref"].rsplit("/", 1)[-1]
        return f"[{name}](#schema-{slug(name).lower()})"
    union = value.get("oneOf", value.get("anyOf", value.get("allOf", [])))
    if union:
        return " / ".join(schema_md(v) for v in union)
    if value.get("type") == "array":
        return schema_md(value.get("items", {})) + "[]"
    return schema_label(value)


def inline_schema_rows(schema: dict, prefix: str = "") -> list[list[str]]:
    result = []
    for key, value in schema.get("properties", {}).items():
        path = f"{prefix}.{key}" if prefix else key
        result.append([path, "필수" if key in schema.get("required", []) else "선택", schema_md(value), value.get("description", "")])
        result.extend(inline_schema_rows(value, path))
        if "items" in value:
            result.extend(inline_schema_rows(value["items"], path + "[]"))
        for union in ("oneOf", "anyOf", "allOf"):
            for branch in value.get(union, []):
                result.extend(inline_schema_rows(branch, path))
    return result


def schema_fields(document: dict, schema: dict, prefix: str = "", seen: frozenset = frozenset()) -> dict:
    """참조·배열·union을 따라 필드별 형식/필수 여부를 비교한다. 순환 참조는 한 번만 펼친다."""
    result = {}
    if "$ref" in schema:
        target = schema["$ref"]
        if target in seen:
            return {prefix or "$": {"recursive": target.rsplit("/", 1)[-1]}}
        return schema_fields(document, deref(document, schema), prefix, seen | {target})
    signature = {k: schema[k] for k in ("type", "enum", "const", "format", "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems") if k in schema}
    if signature:
        result[prefix or "$"] = signature
    required = set(schema.get("required", []))
    for name, child in schema.get("properties", {}).items():
        key = f"{prefix}.{name}" if prefix else name
        result[key + ":required"] = name in required
        result.update(schema_fields(document, child, key, seen))
    if "items" in schema:
        result.update(schema_fields(document, schema["items"], prefix + "[]", seen))
    for union in ("oneOf", "anyOf", "allOf"):
        for i, branch in enumerate(schema.get(union, [])):
            result.update(schema_fields(document, branch, f"{prefix}<{union}:{i}>", seen))
    return result


def operation_fields(document: dict, path: str, method: str, op: dict) -> dict:
    fields = {}
    params = document["paths"][path].get("parameters", []) + op.get("parameters", [])
    for parameter in params:
        p = deref(document, parameter)
        key = f"{p['in']}.{p['name']}"
        fields[key + ":required"] = p.get("required", False)
        fields.update(schema_fields(document, p.get("schema", {}), key))
    body = deref(document, op.get("requestBody", {}))
    if body:
        fields["requestBody:required"] = body.get("required", False)
    for content_type, value in body.get("content", {}).items():
        fields.update(schema_fields(document, value.get("schema", {}), "request:" + content_type))
    for status, response in op.get("responses", {}).items():
        response = deref(document, response)
        fields["response:" + status] = True
        for content_type, value in response.get("content", {}).items():
            fields.update(schema_fields(document, value.get("schema", {}), f"response:{status}:{content_type}"))
        for header, value in response.get("headers", {}).items():
            fields.update(schema_fields(document, deref(document, value).get("schema", {}), f"response:{status}:header:{header}"))
    fields["security"] = op.get("security", document.get("security", []))
    return fields


def workbook(path: Path, sheets: dict[str, tuple[list[str], list[list]]]) -> dict:
    book = Workbook()
    book.remove(book.active)
    for name, (headers, rows) in sheets.items():
        ws = book.create_sheet(name)
        ws.append(headers)
        for row in rows:
            # 원본 셀을 수식으로 실행하지 않는다(구글 시트 가져오기에서도 문자열이다).
            ws.append([cell(v) for v in row])
            for entry in ws[ws.max_row]:
                if entry.data_type == "f":
                    entry.data_type = "s"
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for entry in ws[1]:
            entry.font = Font(bold=True, color="FFFFFF")
            entry.fill = PatternFill("solid", fgColor="17463E")
        for row in ws.iter_rows(min_row=2):
            for entry in row:
                entry.alignment = Alignment(vertical="top", wrap_text=True)
        for index, header in enumerate(headers, 1):
            ws.column_dimensions[get_column_letter(index)].width = 48 if any(k in header for k in ("사유", "내용", "경고", "차이", "출처", "필요", "요청", "응답")) else 26
    book.save(path)
    # 저장 후 독립 reader로 전체 행/셀을 되읽어 배포본과 생성 입력을 대조한다.
    readback = load_workbook(path, read_only=True, data_only=False)
    try:
        if readback.sheetnames != list(sheets):
            raise ValueError("xlsx 되읽기: 시트 목록/순서 불일치")
        counts = {}
        for name, (headers, rows) in sheets.items():
            expected = [headers] + rows
            actual = list(readback[name].iter_rows(values_only=True))
            if len(actual) != len(expected):
                raise ValueError(f"xlsx 되읽기: {name} 행 수 불일치")
            for n, (saved, original) in enumerate(zip(actual, expected), 1):
                if tuple(cell(v) for v in saved) != tuple(cell(v) for v in original):
                    raise ValueError(f"xlsx 되읽기: {name} {n}행 셀 불일치")
            counts[name] = len(rows)
        return {"status": "passed", "sheetDataRows": counts,
                "cells": sum((len(rows) + 1) * len(headers) for headers, rows in sheets.values())}
    finally:
        readback.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="생성 후 실패 목록을 출력한다. 목록이 하나라도 있으면 종료 코드 1")
    parser.add_argument("--bff-url", help="현재 BFF의 /openapi.json URL. 지정 시 해당 문서만 GET하고 out에 관측본을 저장한다")
    args = parser.parse_args()
    catalog = load(SYSTEM / "catalog.yaml")
    links = load(SYSTEM / "links.yaml")
    api = load(ROOT / links["apiContract"])
    OUT.mkdir(parents=True, exist_ok=True)
    API_OUT.mkdir(parents=True, exist_ok=True)
    for pattern in ("screen-*.md", "feature-*.md", "api-differences/*.json"):
        # 이 생성기가 관리하는 산출물만 제거하여 사라진 ID/작업의 문서가 남지 않게 한다.
        for stale in OUT.glob(pattern):
            stale.unlink()
    findings: list[dict] = []

    def finding(code, target, message, severity="warning", source=""):
        findings.append({"code": code, "target": target, "severity": severity, "message": message, "source": source})

    for w in catalog["warnings"]:
        finding(w["code"], w["id"], w["message"], source=source_label(w.get("source")))
    for path, digest in catalog["fingerprints"].items():
        actual = ROOT / path
        if not actual.exists() or hashlib.sha256(actual.read_bytes()).hexdigest() != digest:
            finding("SOURCE_CHANGED", path, "가져오기 이후 원본이 바뀌었다. 동일 명령으로 다시 가져와야 한다.", "error")
    specs = {r["id"]: r for r in catalog["specs"]}
    screens = {r["id"]: r for r in catalog["screens"]}
    tasks = {r["id"]: r for r in catalog["wbs"]}
    requirements = defaultdict(list)
    for rec in catalog["requirements"]:
        requirements[rec["id"]].append(rec)
    implementations = {r["specId"]: r for r in catalog["implementation"]}
    decisions = links.get("featureDecisions", {})
    authority = links.get("authority", {})
    scope = authority.get("implementationScope", {})
    raw_proposal_ids = {rid for rid, rec in specs.items() if rec.get("scopeClass") == "proposal"}
    included_proposals = scope.get("includeRawProposalIds", [])
    authority_source = ROOT / authority.get("source", "")
    authority_valid = (
        bool(authority.get("decisionId")) and bool(authority.get("authority"))
        and authority_source.is_file()
        and scope.get("appliesTo") == "all-specs-and-wbs"
        and scope.get("status") == "팀합의요구/설계대상"
        and scope.get("implementationComplete") is False
        and scope.get("paidExecutionApproved") is False
        and len(included_proposals) == len(set(included_proposals))
        and set(included_proposals) == raw_proposal_ids
    )
    if not authority_valid:
        finding("INVALID_EFFECTIVE_AUTHORITY", "authority", "유효 사용자 결정의 출처·전 범위·원문 제안 ID·완료/실행 경계를 확인해야 한다.", "error")
    api_authority = api.get("x-zoop-approvals", {}).get("implementationScope", {})
    if api_authority != {"authorityRef": "docs/system/links.yaml#authority",
                         "decisionId": authority.get("decisionId"), "source": authority.get("source")}:
        finding("API_AUTHORITY_MISMATCH", "OpenAPI", "목표 API의 유효 기준 참조가 links.yaml.authority와 다르다.", "error")
    effective_scope = scope["status"] if authority_valid else "유효 기준 오류"
    effective_specs = {
        rid: {"raw": {"status": rec["status"], "priority": rec["priority"],
                      "scopeClass": rec.get("scopeClass", "existing"), "source": rec["source"]},
              "implementationScope": effective_scope, "authorityDecisionId": authority.get("decisionId"),
              "implementationEvidence": implementations.get(rid, {}).get("evidenceKind", "문서 판정 없음")}
        for rid, rec in specs.items()
    }
    wbs_bindings = {r["wbsId"]: r for r in links.get("wbsConnections", [])}
    common_wbs = links.get("commonWbs", {})
    for wid, title in common_wbs.items():
        if wid not in tasks or tasks[wid]["title"] != title:
            finding("WBS_MEANING_CHANGED", wid, f"공통 계약 작업 '{title}'과 현재 WBS 의미가 다르다.", "error")
    by_spec, by_screen, by_wbs = defaultdict(list), defaultdict(list), defaultdict(list)
    all_ops = list(operations(api))
    seen_ops = set()
    for path, method, op in all_ops:
        oid = op["operationId"]
        if oid in seen_ops:
            finding("DUPLICATE_OPERATION_ID", oid, "목표 API operationId 중복", "error")
        seen_ops.add(oid)
        x = op.get("x-zoop", {})
        for key, valid, index in (("fsIds", specs, by_spec), ("nfsIds", specs, by_spec), ("screenIds", screens, by_screen), ("wbsIds", tasks, by_wbs)):
            for rid in x.get(key, []):
                if rid not in valid:
                    finding("BROKEN_ID", oid, f"{key}: {rid} 참조 대상이 없다.", "error")
                index[rid].append((path, method, op))
        if not x.get("screenIds"):
            finding("API_WITHOUT_SCREEN", oid, "목표 API에 연결 화면이 없다.", "error")
        if x.get("priority") not in ("P1", "P2"):
            finding("INVALID_PRIORITY", oid, "API 우선순위는 P1 또는 P2여야 한다.", "error")
        if x.get("teamQuestions"):
            finding("TEAM_DECISION_REQUIRED", oid, " / ".join(x["teamQuestions"]))
        for code in x.get("errorCodes", []):
            if code not in {e["code"] for e in api["x-zoop-error-codes"]}:
                finding("BROKEN_ERROR_CODE", oid, f"정의되지 않은 오류 코드 {code}", "error")
        for wid in x.get("wbsIds", []):
            if wid not in tasks or wid in common_wbs:
                continue
            binding = wbs_bindings.get(wid)
            if not binding or not set(binding["specIds"]).intersection(x.get("fsIds", []) + x.get("nfsIds", [])):
                finding("API_WBS_MEANING_MISMATCH", oid, f"{wid}: 현재 제목/역할 기반 편집 연결과 API 기능 의미가 대응하지 않는다.", "error")
        for rid in x.get("fsIds", []) + x.get("nfsIds", []):
            if not authority_valid:
                finding("API_SCOPE_WITHOUT_AUTHORITY", oid, f"{rid}: 유효 기준이 검증되지 않았다.", "error")
            if decisions.get(rid, {}).get("apiDisposition") == "API 불필요":
                finding("OFFLINE_FEATURE_HAS_API", oid, f"{rid}: API 불필요 판정과 HTTP 작업 연결이 충돌한다.", "error")
        if "FS042" in x.get("fsIds", []) and not x.get("meaningQualifications", {}).get("FS042"):
            finding("SPEC_MEANING_UNQUALIFIED", oid, "FS042의 시점 그래프/기존 재무 중 연결 의미를 명시해야 한다.", "error")
    for rid, rec in specs.items():
        for qid in rec["requirementIds"]:
            if qid not in requirements:
                finding("BROKEN_REQUIREMENT_ID", rid, f"요구사항 {qid} 원본 행이 없다.", "error", source_label(rec["source"]))
            elif len(requirements[qid]) == 1 and requirements[qid][0]["title"] != rec["title"]:
                finding("REQUIREMENT_TITLE_REVIEW", rid, f"명세 '{rec['title']}' ↔ 요구사항 {qid} '{requirements[qid][0]['title']}'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).", source=source_label(requirements[qid][0]["source"]))
        disposition = decisions.get(rid, {})
        if rec.get("scopeClass") == "proposal":
            finding("RAW_SCOPE_STATUS_CORRECTION", rid, f"원문 '{rec['status']}'/우선순위 '{rec['priority']}'를 보존한다. 현재 {authority.get('decisionId')}의 유효 범위는 '{effective_scope}'이며 WBS 표기 충돌은 정정 요청이다. 구현 완료·유료 실행 승인은 별개다.", source=source_label(rec["source"]))
            if disposition.get("rawScopeStatus") != rec["status"]:
                finding("RAW_SCOPE_STATUS_MISMATCH", rid, "사람 편집 rawScopeStatus가 원문 상태와 다르다.", "error")
        if ("P1" in rec["priority"] or rid in raw_proposal_ids) and not by_spec[rid] and disposition.get("apiDisposition") not in ("계약 미정", "API 불필요"):
            finding("P1_WITHOUT_API", rid, "API 대응이 필요한 P1/유효 포함 요구에 작업 연결 또는 계약 미정 사유가 없다.", "error")
        if disposition.get("apiDisposition") in ("계약 미정", "API 불필요") and not disposition.get("reason"):
            finding("API_DISPOSITION_WITHOUT_REASON", rid, "API 불필요/계약 미정에는 사유가 필요하다.", "error")
        if disposition.get("apiDisposition") == "계약 미정":
            finding("CONTRACT_UNDECIDED", rid, disposition.get("reason", "계약 미정 사유가 없다."))
    for rid, decision in decisions.items():
        if rid not in specs:
            finding("BROKEN_ID", rid, "사람 편집 featureDecisions에 존재하지 않는 명세 ID가 있다.", "error")
        for key, valid in (("screenIds", screens), ("wbsIds", tasks)):
            for target in decision.get(key, []):
                if target not in valid:
                    finding("BROKEN_ID", rid, f"{key}: {target}", "error")
        for target in decision.get("reusesSpecIds", []):
            if target not in specs:
                finding("BROKEN_ID", rid, f"재사용 근거 명세 {target}가 없다.", "error")
    human_tasks = defaultdict(list)
    for connection in links.get("wbsConnections", []):
        wid = connection["wbsId"]
        if wid not in tasks:
            finding("BROKEN_ID", wid, "사람 편집 WBS 연결의 작업 번호가 없다.", "error")
        elif connection.get("title") != tasks[wid]["title"] or connection.get("role") != tasks[wid].get("role"):
            finding("WBS_MEANING_CHANGED", wid, "번호는 존재하지만 사람이 확인한 제목/역할과 새 원문이 다르다. 내용 기반으로 다시 연결해야 한다.", "error")
        for rid in connection["specIds"]:
            if rid not in specs:
                finding("BROKEN_ID", wid, f"사람 편집 WBS 연결 명세 {rid}가 없다.", "error")
            human_tasks[rid].append(wid)
    for wid, task in tasks.items():
        for raw in task["rawSpecIds"]:
            if raw not in specs:
                finding("WBS_RAW_ID_REVIEW", wid, f"원본 WBS의 {raw}는 현재 명세 ID가 아니다. 사람이 정한 연결과 구분하여 원문을 보존한다.", source=source_label(task["source"]))
            elif raw not in wbs_bindings.get(wid, {}).get("specIds", []):
                finding("WBS_EDITORIAL_ID_DIFFERENCE", wid, f"원문 {raw}는 의존/재사용 참조 또는 업무명과 다른 산출물 ID다. 제목·역할 기반 편집 연결과 rawSpecIds를 분리하며 원문을 자동 치환하지 않는다.", source=source_label(task["source"]))
    code_by_spec = defaultdict(list)
    for row in links.get("implementationLocations", []):
        if row["specId"] not in specs:
            finding("BROKEN_ID", row["specId"], "구현 위치에 존재하지 않는 명세 ID가 있다.", "error")
        code_by_spec[row["specId"]].extend(row["codeLocations"])
        for location in row["codeLocations"]:
            if not (ROOT / location.split(":", 1)[0]).exists():
                finding("CODE_LOCATION_MISSING", row["specId"], location, "error")

    observed_path = OUT / "bff-openapi.json"
    observation_meta = OUT / "bff-observation.json"
    bff = None
    if args.bff_url:
        try:
            with urllib.request.urlopen(args.bff_url, timeout=15) as response:
                bff = json.load(response)
            if not isinstance(bff, dict) or "paths" not in bff:
                raise ValueError("OpenAPI paths가 없다")
            observed_path.write_text(json.dumps(bff, ensure_ascii=False, indent=2) + "\n")
            observation_meta.write_text(json.dumps({"url": args.bff_url, "observedAt": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False, indent=2) + "\n")
        except (OSError, ValueError, urllib.error.URLError) as error:
            finding("BFF_UNOBSERVED", args.bff_url, f"현재 BFF 관측 실패: {type(error).__name__}. 이전 관측본으로 성공 판정하지 않는다.", "error")
    elif observed_path.exists():
        bff = json.loads(observed_path.read_text())
        finding("BFF_CACHED_OBSERVATION", "BFF", "현재 서버를 조회하지 않고 out/bff-openapi.json의 마지막 관측본과 비교했다. 최종 통합은 --bff-url로 다시 실행한다.")
    else:
        finding("BFF_UNOBSERVED", "BFF", "--bff-url을 지정하지 않았고 저장된 관측본도 없다.", "error")
    differences = []
    if bff is not None:
        used = set()
        for path, method, op in all_ops:
            oid, proto = op["operationId"], op["x-zoop"]["prototype"]
            bpath = proto.get("path")
            bmethod = (proto.get("method") or method).lower()
            if not bpath:
                differences.append([oid, path, "없음", "직접 대응 BFF 작업 없음", "목표 API만 있음"])
                finding("TARGET_ONLY_API", oid, f"{method.upper()} {path}: 직접 대응 BFF 없음", "difference")
                continue
            used.add((bpath, bmethod))
            if bpath not in bff["paths"] or bmethod not in bff["paths"][bpath]:
                finding("BFF_OPERATION_MISSING", oid, f"{bmethod.upper()} {bpath}", "error")
                continue
            boperation = bff["paths"][bpath][bmethod]
            if proto.get("operationId") != boperation.get("operationId"):
                finding("BFF_OPERATION_ID_CHANGED", oid, f"기록 {proto.get('operationId')} ↔ 현재 {boperation.get('operationId')}", "difference")
            goal_fields = operation_fields(api, path, method, op)
            actual_fields = operation_fields(bff, bpath, bmethod, boperation)
            added = sorted(goal_fields.keys() - actual_fields.keys())
            removed = sorted(actual_fields.keys() - goal_fields.keys())
            changed = sorted(k for k in goal_fields.keys() & actual_fields.keys() if goal_fields[k] != actual_fields[k])
            description = f"목표만 {len(added)} · BFF만 {len(removed)} · 형식/필수/권한 변경 {len(changed)}"
            differences.append([oid, path, bpath, description, " / ".join(proto.get("differences", []))])
            if path != bpath:
                finding("BFF_PATH_DIFFERENCE", oid, f"목표 {path} ↔ BFF {bpath}", "difference")
            if added or removed or changed:
                finding("BFF_FIELD_DIFFERENCE", oid, description, "difference")
            # 개별 필드 이름과 양쪽의 실제 스키마 서명을 생략 없이 보존한다.
            (OUT / "api-differences").mkdir(exist_ok=True)
            (OUT / "api-differences" / (slug(oid) + ".json")).write_text(json.dumps({"operationId": oid, "targetPath": path, "bffPath": bpath,
                "targetOnly": {k: goal_fields[k] for k in added}, "bffOnly": {k: actual_fields[k] for k in removed},
                "changed": {k: {"target": goal_fields[k], "bff": actual_fields[k]} for k in changed}}, ensure_ascii=False, indent=2) + "\n")
        excluded = {(r["path"], r["method"].lower()): r["reason"] for r in links.get("prototypeOnly", [])}
        for path, method, op in operations(bff):
            if (path, method) not in used:
                reason = excluded.get((path, method))
                finding("PROTOTYPE_ONLY_API" if reason else "BFF_UNMAPPED_API", op["operationId"], f"{method.upper()} {path}: {reason or '대응 목표 계약이 없다. 팀 확인 필요.'}", "difference")
        for path, method in excluded:
            if path not in bff["paths"] or method not in bff["paths"][path]:
                finding("STALE_PROTOTYPE_EXCLUSION", path, "프로토타입 전용 목록에서 대응 경로가 사라졌다.")

    acceptance_rows, acceptance_records = [], []
    for rid, rec in specs.items():
        impl = implementations.get(rid, {})
        definitions = rec["definitions"]
        # 목차에만 있는 ID도 한 행으로 남겨 상세 누락을 coverage에서 숨기지 않는다.
        for index, definition in enumerate(definitions or [{"source": rec["source"], "fields": {}}], 1):
            fields = definition["fields"]
            raw_acceptance = fields.get("수용 기준", "")
            record = {
                "specId": rid, "definitionIndex": index if definitions else None,
                "indexTitle": rec["title"],
                "definitionTitle": fields.get("기능명", fields.get("요구사항명", "")),
                "definitionSource": definition["source"], "indexSource": rec["source"],
                "rawAcceptance": raw_acceptance,
                "acceptancePresence": "있음" if raw_acceptance else "없음" if definitions else "상세 정의 없음",
                "rawStatus": rec["status"], "rawPriority": rec["priority"],
                "implementationScope": effective_scope, "authorityDecisionId": authority.get("decisionId"),
                "legacyImplementation": impl,
                "legacyQualification": "ID 단위 기존 문서 판정이며 이 상세 정의의 수용 기준 통과 판정이 아님",
                "codeLocations": list(dict.fromkeys(impl.get("codeLocations", []) + code_by_spec[rid])),
                "currentRuntimeVerification": "미실행",
            }
            acceptance_records.append(record)
            acceptance_rows.append([
                rid, record["definitionIndex"], rec["title"], record["definitionTitle"],
                source_label(definition["source"]), record["acceptancePresence"],
                raw_acceptance or record["acceptancePresence"], rec["priority"], rec["status"],
                effective_scope, authority.get("decisionId"), impl.get("status", "문서 판정 없음"),
                source_label(impl.get("source")), record["legacyQualification"],
                impl.get("evidenceKind", "문서 판정 없음"), record["codeLocations"], "미실행",
            ])
    expected_definitions = sum(len(rec["definitions"]) for rec in specs.values())
    actual_definitions = sum(row["definitionIndex"] is not None for row in acceptance_records)
    expected_sources = Counter((rid, d["source"]["path"], d["source"]["row"])
                               for rid, rec in specs.items() for d in rec["definitions"])
    actual_sources = Counter((r["specId"], r["definitionSource"]["path"], r["definitionSource"]["row"])
                             for r in acceptance_records if r["definitionIndex"] is not None)
    acceptance_coverage = {
        "status": "passed" if set(r["specId"] for r in acceptance_records) == set(specs)
                  and expected_sources == actual_sources and actual_definitions == expected_definitions else "failed",
        "specIds": len(specs), "coveredSpecIds": len({r["specId"] for r in acceptance_records}),
        "expectedDefinitions": expected_definitions, "coveredDefinitions": actual_definitions,
        "rows": len(acceptance_records),
        "missingAcceptanceDefinitions": sum(r["definitionIndex"] is not None and not r["rawAcceptance"] for r in acceptance_records),
        "missingDetailIds": [rid for rid, rec in specs.items() if not rec["definitions"]],
        "currentRuntimeVerification": "미실행",
    }
    if acceptance_coverage["status"] != "passed":
        finding("ACCEPTANCE_COVERAGE_INCOMPLETE", "수용 기준", "전체 ID/상세 정의 출처별 수용 기준 행이 빠졌다.", "error")

    corrections = []

    def correction(code, target, left, right, decision, request):
        corrections.append({"code": code, "target": target, "originalA": left, "originalB": right,
                            "workerDecision": decision, "ownerCorrectionRequest": request,
                            "status": "원문 담당자 정정 요청(원문 변경 없음)"})

    def spec_original(rid):
        rec = specs[rid]
        return {"source": rec["source"], "text": f"{rid}: {rec['title']} / {rec['priority']} / {rec['status']}"}

    def definition_original(definition):
        fields = definition["fields"]
        return {"source": definition["source"], "text": fields.get("기능명", fields.get("요구사항명", "")),
                "rawAcceptance": fields.get("수용 기준", "")}

    def task_original(wid):
        task = tasks[wid]
        return {"source": task["source"], "text": f"{wid}: {task['title']} / {task['type']} / {task['start']}~{task['end']} / 가중치 {task['weight']} / raw {cell(task['rawSpecIds'])}"}

    for rid, rec in specs.items():
        for qid in rec["requirementIds"]:
            if len(requirements[qid]) == 1 and requirements[qid][0]["title"] != rec["title"]:
                requirement = requirements[qid][0]
                correction("REQUIREMENT_TITLE_REVIEW", rid, spec_original(rid),
                           {"source": requirement["source"], "text": f"요구사항 {qid}: {requirement['title']}"},
                           "원문 요구 번호와 의미 연결을 보존하며 제목 차이만으로 자동 재연결하지 않는다.",
                           "명세/요구사항 담당자가 분리·통합·번호 이동인지 확인하고 현재 ID와 의미별 연결을 정정해 주세요.")
        if len(rec["definitions"]) > 1:
            for definition in rec["definitions"][1:]:
                correction("MULTIPLE_SPEC_DEFINITIONS", rid, definition_original(rec["definitions"][0]),
                           definition_original(definition), "두 상세를 독립 행으로 유지하고 자동으로 우선 정의를 선택하지 않는다.",
                           "명세 담당자가 두 정의의 유지/이전/통합 관계와 의미별 수용 기준을 명시해 주세요.")
        if rec.get("scopeClass") == "proposal":
            wid = decisions.get(rid, {}).get("wbsIds", [None])[0]
            if wid in tasks:
                correction("RAW_SCOPE_STATUS_CORRECTION", rid, spec_original(rid), task_original(wid),
                           f"유효 범위는 {effective_scope}이며 재사용 공수는 중복 산정하지 않는다.",
                           "명세/WBS 담당자가 미갱신 상태·우선순위 표기를 정정하고 기존 기능 재사용과 상세 단계의 일정·역할을 일치시켜 주세요.")
    if "FS042" in specs and specs["FS042"]["definitions"]:
        correction("SPEC_ID_MEANING_CONFLICT", "FS042", spec_original("FS042"),
                   definition_original(specs["FS042"]["definitions"][0]),
                   "시점 그래프 연결과 재무·실적 요구를 별도 의미로 보존한다. 재무 폐기를 추정하지 않는다.",
                   "명세 담당자가 재무/시점 그래프의 고유 ID·목차·요구 연결을 정정하고 WBS 담당자가 의미별 책임을 연결해 주세요.")
    if "FS050" in specs and "FS051" in specs:
        correction("SPEC_V2_MEANING_REVIEW", "FS050", spec_original("FS050"), spec_original("FS051"),
                   "새 대화/후속 질문 v2와 기존 새 대화·근거 탐색 정의를 자동 통합하거나 제외하지 않는다.",
                   "AI 명세 담당자가 FS050과 FS050-01/-02·FS051·FS052의 채택/이전/동시 유지 관계를 명시해 주세요.")
    if "FS050" in specs and "FS050-01" in specs:
        correction("SPEC_V2_MEANING_REVIEW", "FS050 / FS050-01", spec_original("FS050"), spec_original("FS050-01"),
                   "v2의 새 대화/후속 질문과 기존 FS050 근거 탐색 분리 의미를 독립적으로 유지한다.",
                   "AI 명세 담당자가 기존 FS050 분리 이력과 v2의 FS050 재사용 관계를 정정해 주세요.")
    if "FS???" in specs and "FS066-01" in specs:
        correction("MALFORMED_SPEC_ID", "FS???", spec_original("FS???"), spec_original("FS066-01"),
                   "브리핑 리뷰의 원문 ID를 보존하고 공통 평가 의미와의 연결을 임의 번호로 확정하지 않는다.",
                   "명세 담당자가 브리핑 리뷰와 공통 평가의 고유 ID/통합 관계 및 목차 연결을 정정해 주세요.")
    if "6.5.3" in tasks and "FS035" in specs:
        correction("WBS_RAW_ID_REVIEW", "FS057 / 6.5.3", task_original("6.5.3"), spec_original("FS035"),
                   "기존 FS057→FS035 통합 선언에 따라 저장 업무를 FS035로 편집 연결하고 raw FS057은 보존한다.",
                   "WBS 담당자가 산출물 FS057을 현재 통합 ID와 일치시키고 기존 저장 업무와 중복 산정하지 않도록 정정해 주세요.")
    if "6.8.7" in tasks and "FS034" in specs:
        correction("WBS_TITLE_MISSING", "6.8.7", task_original("6.8.7"), spec_original("FS034"),
                   "공란 번호에 이전 중복 발행 방지 의미를 부여하지 않는다. 기존 저장/상태 계약 연결을 유지한다.",
                   "WBS 담당자가 공란 업무의 유지/삭제와 실제 업무·산출물·담당·기간을 명시하고 FS034 책임을 확인해 주세요.")
    for records in catalog.get("wbsSources", {}).get("ancillaryRows", {}).values():
        for record in records:
            if any("6.5.13" in text and "6.5.20" in text for text in record["cells"]) and "6.6.13" in tasks:
                correction("WBS_COVER_BODY_CONFLICT", "FS074~FS081 / 6.6.13~20",
                           {"source": record["source"], "text": cell(record["cells"])}, task_original("6.6.13"),
                           "본문 6.6.13~20을 현재 역할 연결에 사용한다. 일정 기준은 WBS이며 내부 충돌은 정정 요청으로 남긴다.",
                           "WBS 담당자가 표지/요약/본문의 번호·역할·기간·가중치를 일치시켜 주세요. 원문 제안 8개를 제외하지 마세요.")
    correction_rows = [[r["code"], r["target"], source_label(r["originalA"]["source"]), r["originalA"]["text"],
                        source_label(r["originalB"]["source"]), r["originalB"]["text"],
                        r["workerDecision"], r["ownerCorrectionRequest"], r["status"]] for r in corrections]

    trace_rows, screen_rows, feature_rows, api_rows = [], [], [], []
    for rid, rec in specs.items():
        impl = implementations.get(rid, {})
        status = impl.get("status", "문서 판정 없음")
        disposition = decisions.get(rid, {}).get("apiDisposition", "연결됨" if by_spec[rid] else "미연결")
        codes = list(dict.fromkeys(impl.get("codeLocations", []) + code_by_spec[rid]))
        matched = by_spec[rid] or [("", "", {})]
        for path, method, op in matched:
            x = op.get("x-zoop", {})
            trace_rows.append([rid, rec["title"], rec["priority"], rec["status"], rec["requirementIds"], x.get("screenIds", decisions.get(rid, {}).get("screenIds", [])),
                               op.get("operationId", ""), method.upper(), path, x.get("wbsIds", decisions.get(rid, {}).get("wbsIds", [])), status, disposition,
                               decisions.get(rid, {}).get("reason", ""), source_label(rec["source"]), source_label(impl.get("source")), codes, rec.get("scopeClass", "existing"),
                               effective_scope, authority.get("decisionId"), authority.get("source")])
        wids = list(dict.fromkeys(human_tasks[rid] + decisions.get(rid, {}).get("wbsIds", []) + (list(common_wbs) if by_spec[rid] else [])))
        for wid in wids or [""]:
            task = tasks.get(wid, {})
            feature_rows.append([rid, rec["title"], rec["priority"], wid, task.get("title", ""), task.get("start", ""), task.get("end", ""),
                                 task.get("owners", ""), status, disposition, impl.get("detail", ""), codes, source_label(task.get("source")), source_label(impl.get("source")),
                                 rec.get("scopeClass", "existing"), task.get("role", ""), task.get("rawSpecIds", []), wbs_bindings.get(wid, {}).get("reason", ""),
                                 effective_scope, authority.get("decisionId")])
    for sid, screen in screens.items():
        for path, method, op in by_screen[sid] or [("", "", {})]:
            x = op.get("x-zoop", {})
            for rid in x.get("fsIds", []) + x.get("nfsIds", []) or [""]:
                screen_rows.append([sid, screen["title"], screen["route"], screen["page"], rid, specs.get(rid, {}).get("title", ""),
                                    op.get("operationId", ""), method.upper(), path, x.get("priority", ""), x.get("wbsIds", [])])
        for rid, decision in decisions.items():
            if sid in decision.get("screenIds", []):
                screen_rows.append([sid, screen["title"], screen["route"], screen["page"], rid, specs.get(rid, {}).get("title", ""),
                                    decision.get("apiDisposition", ""), "", "", specs.get(rid, {}).get("priority", ""), decision.get("wbsIds", [])])
    for path, method, op in all_ops:
        x = op["x-zoop"]
        api_rows.append([op["operationId"], op["summary"], method.upper(), path, x["authority"], x["priority"], x["fsIds"], x["nfsIds"],
                         x["screenIds"], x["wbsIds"], x["prototype"].get("path"), x["prototype"]["differences"], x["teamQuestions"]])
    proposals = [r for r in specs.values() if r.get("scopeClass") == "proposal"]
    proposal_rows = [[r["id"], r["title"], r["priority"], r["status"], decisions.get(r["id"], {}).get("reusesSpecIds", []),
                      decisions.get(r["id"], {}).get("wbsIds", []), decisions.get(r["id"], {}).get("apiDisposition", ""),
                      decisions.get(r["id"], {}).get("operationalIntegration", ""), effective_scope,
                      authority.get("decisionId"), authority.get("source"),
                      decisions.get(r["id"], {}).get("reason", ""), source_label(r["source"])] for r in proposals]
    wbs_rows = [[wid, t["title"], t.get("role", ""), t["type"], t["deliverable"], t["rawSpecIds"],
                 wbs_bindings.get(wid, {}).get("specIds", []), t["owners"], t["start"], t["end"], t["weight"], t["progress"],
                 effective_scope,
                 source_label(t["source"])] for wid, t in tasks.items()]
    warning_rows = [[w["code"], w["severity"], w["target"], w["message"], w["source"]] for w in findings]
    error_rows = [[r["code"], r["httpStatus"], r["meaning"], r["recovery"]] for r in api["x-zoop-error-codes"]]
    sheets = {
        "추적표": (["명세 ID", "명세명", "원본 우선순위", "원본 상태", "요구사항 번호", "화면 ID", "operationId", "메서드", "목표 경로", "WBS", "문서 구현 판정", "API 대응", "사유", "명세 출처", "판정 출처", "코드 위치", "원문 범위 분류", "유효 구현 범위", "유효 기준 결정", "유효 기준 출처"], trace_rows),
        "화면→기능→API": (["화면 ID", "화면명", "라우트", "캡처 쪽수", "명세 ID", "명세명", "operationId", "메서드", "목표 경로", "API 우선순위", "WBS"], screen_rows),
        "기능→WBS→구현 상태": (["명세 ID", "명세명", "원본 우선순위", "WBS", "업무", "시작일", "종료일", "담당", "문서 구현 판정", "API 대응", "판정 내용", "코드 위치", "WBS 출처", "판정 출처", "원문 범위 분류", "역할", "원문 FS/의존 참조", "편집 연결 근거", "유효 구현 범위", "유효 기준 결정"], feature_rows),
        "API 목록": (["operationId", "작업명", "메서드", "목표 경로", "권한", "API 우선순위", "FS", "NFS", "화면 ID", "WBS", "BFF 경로", "목표 차이", "팀 확인 필요"], api_rows),
        "오류 코드": (["코드", "HTTP", "의미", "복구 규칙"], error_rows),
        "경고": (["분류", "수준", "대상 ID", "경고 내용", "출처"], warning_rows),
        "원문 WBS": (["WBS", "업무", "역할", "원문 유형", "원문 산출물", "rawSpecIds", "편집 명세 연결", "담당", "시작일", "종료일", "가중치", "진행률", "유효 구현 범위(원문과 별도)", "출처"], wbs_rows),
        "원문 제안·유효 기준": (["명세 ID", "명세명", "원본 우선순위", "원본 상태", "재사용 기존 FS", "현재 WBS", "API 대응", "운영 연동", "유효 구현 범위", "유효 기준 결정", "유효 기준 출처", "사유", "원문 출처"], proposal_rows),
        "수용 기준": (["명세 ID", "상세 정의 번호", "목차명", "상세 기능명", "상세 정의 출처", "수용 기준 존재", "원문 수용 기준", "원본 우선순위", "원본 상태", "유효 구현 범위", "유효 기준 결정", "기존 문서 구현 판정", "판정 출처", "판정 적용 경계", "기존 증거 종류", "코드 위치(실행 증거 아님)", "현행 실행 검증"], acceptance_rows),
    }
    readback = workbook(OUT / "zoop-trace.xlsx", sheets)
    print(f"xlsx 되읽기: {readback['status']} · {len(readback['sheetDataRows'])}시트 · {readback['cells']}셀")
    (OUT / "acceptance-matrix.json").write_text(json.dumps({"coverage": acceptance_coverage,
        "authorityDecisionId": authority.get("decisionId"), "records": acceptance_records}, ensure_ascii=False, indent=2) + "\n")
    (OUT / "acceptance-matrix.md").write_text("# 전체 명세의 상세 정의별 수용 기준\n\n원문 상세 정의를 각각 한 행으로 유지한다. 기존 ID 단위 구현 판정은 인용이며 해당 상세의 수용 기준 통과 증거가 아니다. **현행 실행 검증은 전부 미실행**이다. 상세/수용 기준이 없는 항목도 표시한다.\n\n"
        + f"- 범위: {len(specs)} ID · {actual_definitions}/{expected_definitions} 상세 정의 · {len(acceptance_records)}행\n"
        + f"- coverage: {acceptance_coverage['status']} · 수용 기준 없는 상세 {acceptance_coverage['missingAcceptanceDefinitions']}개\n\n"
        + table(sheets["수용 기준"][0], acceptance_rows))
    (OUT / "source-corrections.json").write_text(json.dumps({"status": "원문 변경 없음",
        "authorityDecisionId": authority.get("decisionId"), "records": corrections}, ensure_ascii=False, indent=2) + "\n")
    (OUT / "source-corrections.md").write_text("# 원문 정정 요청\n\n두 원문·출처와 작업자 가결정을 분리한다. 이 요청으로 원문 ID/상태/일정을 수정하거나 기능 완료로 승격하지 않는다. WBS 내부 마일스톤/상위 종료일 충돌은 [현재 작업 기준](../../share/day-work-2026-10-08.md)의 일정 정정 요청도 함께 읽는다.\n\n"
        + table(["분류", "대상", "원문 A 출처", "원문 A", "원문 B 출처", "원문 B", "작업자 가결정", "담당자 수정 요청", "상태"], correction_rows))
    (OUT / "effective-authority.json").write_text(json.dumps({
        "authority": authority, "valid": authority_valid,
        "sourceSha256": hashlib.sha256(authority_source.read_bytes()).hexdigest() if authority_source.is_file() else None,
        "specs": effective_specs,
        "wbsImplementationScope": {"status": effective_scope, "count": len(tasks)},
    }, ensure_ascii=False, indent=2) + "\n")
    (OUT / "warnings.md").write_text("# 추적 검사 결과\n\n원본 오류·미결정·목표/BFF 차이는 숨기지 않는다. 차이는 오류 수정 완료 또는 정식 구현 완료를 뜻하지 않는다.\n\n" + table(sheets["경고"][0], warning_rows))
    (OUT / "api-differences.md").write_text("# 목표 계약 ↔ BFF 관측본\n\n경로·요청/응답 필드·필수 여부·형식·권한을 비교한다. 각 작업의 전체 필드 차이는 `api-differences/<operationId>.json`에 있다. 실제 동작 시험이 아니며 현재 서버 조회 시각은 `bff-observation.json`에 있다.\n\n" + table(["operationId", "목표 경로", "BFF 경로", "필드 차이", "설계 차이"], differences))
    (OUT / "checks.json").write_text(json.dumps({"findings": findings, "counts": dict(Counter(w["code"] for w in findings)),
        "severityCounts": dict(Counter(w["severity"] for w in findings)),
        "xlsxReadback": readback,
        "acceptanceCoverage": acceptance_coverage,
        "sourceCorrectionCount": len(corrections),
        "authority": {"decisionId": authority.get("decisionId"), "source": authority.get("source"), "valid": authority_valid},
        "scopeCounts": {"rawExistingSpecs": len(specs) - len(proposals), "rawProposals": len(proposals),
                        "effectiveIncludedSpecs": len(specs) if authority_valid else 0,
                        "effectiveIncludedRawProposals": len(proposals) if authority_valid else 0,
                        "effectiveIncludedWbs": len(tasks) if authority_valid else 0,
                        "wbs": len(tasks), "wbsRoles": dict(Counter(t.get("role", "") for t in tasks.values())),
                        "targetOperations": len(all_ops)},
        "sheetDataRows": {k: len(v[1]) for k, v in sheets.items()}}, ensure_ascii=False, indent=2) + "\n")
    migration = links.get("wbsMigration", {})
    (OUT / "wbs-migration.md").write_text("# WBS 내용 기반 연결 이행\n\n기계 추출 raw와 아래 편집 관계는 별개다. 번호 존재만으로 옛 의미를 승계하지 않는다. 승인·구현 상태를 자동 변경하지 않는다.\n\n"
        + f"- 이전: `{migration.get('previousWbsSource', '')}` · {migration.get('previousTaskCount', '')}개\n"
        + f"- 현재: `{migration.get('currentWbsSource', '')}` · {len(tasks)}개 · 역할 {dict(Counter(t.get('role', '') for t in tasks.values()))}\n"
        + f"- 헤더 대조: {migration.get('headerComparison', '')}\n"
        + f"- 목표 API {len(all_ops)}개를 현재 업무명·역할·FS 편집 연결로 검사했다. 작업별 연결 정본은 openapi.yaml의 x-zoop.wbsIds다.\n"
        + f"- 원문 제안 {len(proposals)}개도 현재 유효 기준 '{effective_scope}'에 포함한다. 결정 출처는 `{authority.get('source', '')}`다. 표지/요약 vs 본문 및 원문 ID 차이는 정정 요청으로 warnings.md에 유지한다. 재사용 공수를 중복 산정하지 않는다.\n\n"
        + table(["이전 번호", "의미", "현재 역할/번호", "내용 대조 근거"],
                [[g["previousIds"], g["meaning"], g["currentTargets"], g["reason"]] for g in migration.get("groups", [])]))
    for sid, screen in screens.items():
        lines = f"# {sid} · {screen['title']}\n\n[전체 목록](index.md) · [검사 결과](warnings.md)\n\n- 라우트: `{screen['route'] or '설명 슬라이드(라우트 없음)'}`\n- 화면계획서 캡처 쪽수: **{screen['page']}**\n- 원본: {source_link(screen['source'], 3)}\n\n"
        rows_out = []
        for path, method, op in by_screen[sid]:
            fs_links = " · ".join(f"[{rid}](feature-{slug(rid)}.md)" for rid in op["x-zoop"]["fsIds"])
            rows_out.append([fs_links, f"[{op['operationId']}](../../api/out/zoop-api-spec.md#{op['operationId'].lower()})", f"{method.upper()} {path}", op["x-zoop"]["priority"]])
        lines += table(["기능", "목표 API", "경로", "우선순위"], rows_out) if rows_out else "이 쪽은 화면 규칙/설명 슬라이드이거나 현재 API 연결이 없는 화면이다. API를 임의로 만들지 않는다.\n"
        quality = list(dict.fromkeys(rid for _, _, op in by_screen[sid] for rid in op["x-zoop"]["nfsIds"]))
        if quality:
            lines += "\n공통 품질: " + " · ".join(f"[{rid}](feature-{slug(rid)}.md)" for rid in quality) + "\n"
        screen_only = [rid for rid, decision in decisions.items() if sid in decision.get("screenIds", [])]
        if screen_only:
            lines += "\n화면 구현 요구: " + " · ".join(f"[{rid}](feature-{slug(rid)}.md)" for rid in screen_only) + "\n"
        (OUT / f"screen-{slug(sid)}.md").write_text(lines)
    for rid, rec in specs.items():
        impl = implementations.get(rid, {})
        decision = decisions.get(rid, {})
        feature_screens = list(dict.fromkeys([sid for _, _, op in by_spec[rid] for sid in op["x-zoop"]["screenIds"]] + decision.get("screenIds", [])))
        lines = f"# {rid} · {rec['title']}\n\n[전체 목록](index.md) · [검사 결과](warnings.md)\n\n" + table(["항목", "원본/연결"], [["원본 우선순위·상태", f"{rec['priority']} · {rec['status']}"], ["원문 범위 분류", rec.get("scopeClass", "existing")], ["유효 구현 범위", effective_scope], ["유효 기준", f"{authority.get('decisionId')} · {authority.get('source')}"], ["완료·실행 경계", "요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님"], ["요구사항 번호", rec["requirementIds"]], ["API 대응", decision.get("apiDisposition", "연결됨" if by_spec[rid] else "미연결")], ["사유", decision.get("reason", "")], ["프로토타입 문서 판정", impl.get("status", "판정 없음")], ["코드 위치(실행 증거 아님)", list(dict.fromkeys(impl.get("codeLocations", []) + code_by_spec[rid]))]])
        lines += "\n## 원본과 의미\n\n" + source_link(rec["source"], 3) + "\n\n"
        for definition in rec["definitions"]:
            fields = definition["fields"]
            description = fields.get("기능 설명", fields.get("요구사항 설명", ""))
            # 한 쪽 요약에는 원문 요약문만 발췌하고 상세 정책/수용 기준은 고정본으로 연결한다.
            lines += f"- {source_link(definition['source'], 3)} — {fields.get('기능명', fields.get('요구사항명', ''))}: {description}\n"
        if impl:
            lines += f"\n문서 판정 출처: {source_link(impl['source'], 3)}. 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.\n"
        if decision.get("reusesSpecIds"):
            lines += "\n재사용 근거(상세 수용 기준의 구현 완료 증거 아님): " + " · ".join(f"[{target}](feature-{slug(target)}.md)" for target in decision["reusesSpecIds"]) + "\n"
        lines += "\n## WBS 편집 연결\n\n" + table(["WBS", "역할", "현재 업무", "연결 근거"],
            [[wid, tasks[wid].get("role", ""), tasks[wid]["title"], wbs_bindings.get(wid, {}).get("reason", decision.get("reason", ""))]
             for wid in dict.fromkeys(human_tasks[rid] + decision.get("wbsIds", [])) if wid in tasks])
        lines += "\n## 화면·목표 API\n\n" + " · ".join(f"[{sid}](screen-{slug(sid)}.md)" for sid in feature_screens) + "\n\n"
        if len(by_spec[rid]) <= 12:
            lines += table(["작업", "메서드·목표 경로", "WBS", "권한"], [[f"[{op['operationId']}](../../api/out/zoop-api-spec.md#{op['operationId'].lower()})", f"{method.upper()} {path}", op["x-zoop"]["wbsIds"], op["x-zoop"]["authority"]] for path, method, op in by_spec[rid]])
        else:
            groups = defaultdict(list)
            for path, method, op in by_spec[rid]:
                groups[path.split("/")[3]].append(op)
            lines += table(["도메인", "연결 작업 수", "작업 목록"], [[group, len(ops), "[전체 API 목록](../../api/out/zoop-api-spec.md#작업-목록)"] for group, ops in groups.items()])
            lines += "\n작업별 FS/NFS 역링크와 전체 연결은 API 명세서 및 xlsx 추적표에 보존한다.\n"
        feature_findings = [w for w in findings if w["target"] == rid]
        if feature_findings:
            lines += "\n## 확인 필요\n\n" + "".join(f"- {w['code']}: {w['message']}\n" for w in feature_findings)
        (OUT / f"feature-{slug(rid)}.md").write_text(lines)
    (OUT / "index.md").write_text("# 줍 연결 문서\n\n이 문서는 생성물이다. 변경은 catalog.yaml 가져오기, links.yaml 또는 docs/api/openapi.yaml 편집으로 한다.\n\n[현재 사용자 결정](../../share/day-work-2026-10-08.md) · [유효 기준 JSON](effective-authority.json) · [전체 수용 기준](acceptance-matrix.md) · [원문 정정 요청](source-corrections.md) · [API 명세서](../../api/out/zoop-api-spec.md) · [검사 결과](warnings.md) · [WBS 내용 기반 이행](wbs-migration.md) · [BFF 차이](api-differences.md) · [팀용 xlsx](zoop-trace.xlsx)\n\n"
        + f"전체 명세/WBS의 유효 구현 범위: **{effective_scope}**. 원문 상태는 아래에 별도로 보존하며 완료·실행 승인으로 해석하지 않는다.\n\n## 화면\n\n"
        + "\n".join(f"- [{sid} · {s['title']}](screen-{slug(sid)}.md) — {s['page']}쪽" for sid, s in screens.items())
        + "\n\n## 기존 원문 분류의 기능·비기능(현재 설계대상)\n\n"
        + "\n".join(f"- [{rid} · {s['title']}](feature-{slug(rid)}.md) — 원문 우선순위 {s['priority']}" for rid, s in specs.items() if s.get("scopeClass") != "proposal")
        + "\n\n## 원문 추가 제안 8개 · 현재 팀합의 설계대상\n\n"
        + "\n".join(f"- [{r['id']} · {r['title']}](feature-{slug(r['id'])}.md) — 원문 {r['priority']} · {r['status']} / 유효 {effective_scope}" for r in proposals) + "\n")
    api_md = "# 줍 정식 서버 목표 API 명세서\n\n생성물이다. 정본은 [openapi.yaml](../openapi.yaml)이다. WBS **6.1.2 API 명세 최종 검토·구현 기준 확정**, **6.11.1 API·스키마 계약 통합 점검**에 연결한다. API 공통 규칙은 사용자 **잠정 채택/시연 기준**이며 정식 구현 완료가 아니다. 전체 명세/WBS(FS074~081 포함)의 현재 범위는 팀합의요구/설계대상이며 원문 승인 표기·구현 증거·유료 실행 승인은 별개다. 프로토타입 관측과 구현 목표를 구분한다.\n\n[현재 사용자 결정](../../share/day-work-2026-10-08.md) · [유효 기준 JSON](../../system/out/effective-authority.json) · [추적표](../../system/out/index.md) · [현재 검사 결과](../../system/out/warnings.md) · [WBS 내용 기반 이행](../../system/out/wbs-migration.md) · [BFF 차이](../../system/out/api-differences.md)\n\n## 공통 규칙\n\n"
    for name, rule in api["x-zoop-common-rules"].items():
        api_md += f"### {name}\n\n{rule}\n\n"
    api_md += "## 오류 코드\n\n" + table(sheets["오류 코드"][0], error_rows) + "\n## 작업 목록\n\n" + table(["작업", "메서드", "목표 경로", "권한", "우선순위"], [[f"[{op['operationId']}](#{op['operationId'].lower()})", method.upper(), path, op["x-zoop"]["authority"], op["x-zoop"]["priority"]] for path, method, op in all_ops])
    for path, method, op in all_ops:
        x = op["x-zoop"]
        fslinks = " · ".join(f"[{rid}](../../system/out/feature-{slug(rid)}.md)" for rid in x["fsIds"] + x["nfsIds"])
        slinks = " · ".join(f"[{sid}](../../system/out/screen-{slug(sid)}.md)" for sid in x["screenIds"])
        body = deref(api, op.get("requestBody", {}))
        body_schemas = [v.get("schema", {}) for v in body.get("content", {}).values()]
        response_schemas = []
        for status, response in op["responses"].items():
            resp = deref(api, response)
            response_schemas += [f"{status}: {schema_md(v.get('schema', {}))}" for v in resp.get("content", {}).values()]
            if not resp.get("content"):
                response_schemas.append(f"{status}: 본문 없음")
        api_md += f"\n<a id=\"{op['operationId'].lower()}\"></a>\n\n## {op['operationId']} · {op['summary']}\n\n{op['description']}\n\n" + table(["항목", "계약"], [["메서드·경로", f"`{method.upper()} {path}`"], ["권한·우선순위", f"{x['authority']} · {x['priority']}"], ["요청 본문", [schema_md(v) for v in body_schemas] or "없음"], ["응답", response_schemas], ["오류 코드", x["errorCodes"]], ["FS/NFS", fslinks], ["화면", slinks], ["WBS", x["wbsIds"]], ["프로토타입 대응", x["prototype"].get("path") or "없음"], ["목표와 차이", x["prototype"]["differences"]], ["팀 확인 필요", x["teamQuestions"] or "해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다."]])
        if x.get("meaningQualifications"):
            api_md += "\n명세 의미 구분: " + " / ".join(f"{rid}: {meaning}" for rid, meaning in x["meaningQualifications"].items()) + "\n"
        parameter_rows = []
        for parameter in op.get("parameters", []):
            p = deref(api, parameter)
            parameter_rows.append([p["name"], p["in"], "필수" if p.get("required") else "선택", schema_label(p.get("schema", {})), p.get("description", "")])
        api_md += "\n### 요청 필드\n\n" + table(["이름", "위치", "필수", "형식", "설명"], parameter_rows)
        for schema in body_schemas:
            label = schema_label(schema)
            api_md += f"\n본문 스키마: [{label}](#schema-{slug(label).lower()}). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.\n"
    api_md += "\n## 공통 스키마\n\nnullable은 미제공/미판정이고 숫자 0 또는 빈 문자열로 대신하지 않는다. 필수 필드는 null 허용 여부와 별개다. JSON 필드 이름·중첩 참조의 정본은 OpenAPI다.\n"
    for name, schema in api["components"]["schemas"].items():
        api_md += f"\n<a id=\"schema-{slug(name).lower()}\"></a>\n\n### {name}\n\n{schema.get('description', '')}\n\n"
        if schema.get("properties"):
            api_md += table(["필드", "필수", "형식/참조", "설명"], inline_schema_rows(schema))
        else:
            api_md += schema_md(schema) + "\n"
    (API_OUT / "zoop-api-spec.md").write_text(api_md)
    print(f"생성: 명세 {len(specs)}, 목표 API {len(all_ops)}, 화면/설명 슬라이드 {len(screens)}")
    print("xlsx 데이터 행: " + ", ".join(f"{name} {len(rows)}" for name, (_, rows) in sheets.items()))
    counts = Counter(w["code"] for w in findings)
    print("검사 목록: " + ", ".join(f"{name} {count}" for name, count in sorted(counts.items())))
    if args.check:
        for w in findings:
            print(f"[{w['severity']}] {w['code']} {w['target']}: {w['message']}")
        print(f"검사 종료: {len(findings)}건. 전체 필드 차이·출처는 docs/system/out/에 보존했다.")
        return 1 if findings else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
