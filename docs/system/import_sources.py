#!/usr/bin/env python3
"""고정본을 읽어 기계 추출 레지스트리만 교체한다. 사람이 편집한 파일은 읽거나 쓰지 않는다."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "docs/system/catalog.yaml"
SPEC_ID = re.compile(r"(?:NFS|FS)[0-9?]+(?:-[0-9?]+)?")
VALID_ID = re.compile(r"(?:NFS|FS)\d{3}(?:-\d{2})?")


def relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def csv_rows(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.reader(stream))


def origin(path: Path, row: int) -> dict:
    # CSV의 물리적 줄이 아니라 csv.reader의 레코드 번호다. 고정본의 xlsx 행과 같다.
    return {"path": relative(path), "row": row, "rowUnit": "xlsx-row"}


def number(value: str) -> str:
    return value.removesuffix(".0").strip()


def header(rows: list[list[str]], expected: list[str], path: Path) -> tuple[int, dict[str, int]]:
    matches = [(n, row) for n, row in enumerate(rows, 1) if row[:len(expected)] == expected]
    if len(matches) != 1:
        raise ValueError(f"고정 열 헤더 불일치: {path} (기대: {expected})")
    n, row = matches[0]
    return n, {name: index for index, name in enumerate(row[:len(expected)])}


def import_specs(folder: Path, warnings: list[dict]) -> list[dict]:
    files = sorted(folder.glob("*.csv"))
    indexes = [p for p in files if any(r and r[0] == "명세 ID" for r in csv_rows(p))]
    if len(indexes) != 1:
        raise ValueError(f"명세 목차 CSV는 하나여야 한다: {folder} ({len(indexes)})")
    header(csv_rows(indexes[0]), ["명세 ID", "영역별 시트", "기능·요구사항명", "원본 우선순위",
                                "원본 상태", "요구사항 ID", "상세 위치", "v1.2 변경"], indexes[0])
    records = []
    for row_no, row in enumerate(csv_rows(indexes[0]), 1):
        if not row or not SPEC_ID.fullmatch(row[0].strip()):
            continue
        row += [""] * max(0, 8 - len(row))
        raw = row[0].strip()
        records.append({"id": raw, "title": row[2], "section": row[1],
                        "priority": row[3], "status": row[4],
                        "requirementIds": [number(x) for x in row[5].split(",") if x.strip()],
                        "source": origin(indexes[0], row_no), "detailRange": row[6],
                        "change": row[7], "definitions": []})
    by_id = {r["id"]: r for r in records}
    for path in files:
        rows = csv_rows(path)
        starts = [(n, r[1].strip()) for n, r in enumerate(rows, 1)
                  if len(r) > 1 and r[0].strip() in ("기능 ID", "비기능 ID")]
        for index, (row_no, raw) in enumerate(starts):
            end = starts[index + 1][0] - 2 if index + 1 < len(starts) else len(rows)
            fields = {r[0].strip(): r[1] for r in rows[row_no:end]
                      if len(r) > 1 and r[0].strip() and r[1].strip()}
            if raw not in by_id:
                meta = " ".join(" ".join(r) for r in rows[max(0, row_no - 3):row_no - 1])
                priority = re.search(r"우선순위:\s*(P[12])", meta)
                rec = {"id": raw, "title": fields.get("기능명", fields.get("요구사항명", raw)),
                       "section": path.stem, "priority": priority[1] if priority else "미기재",
                       "status": "목차 없음", "requirementIds": [], "source": origin(path, row_no),
                       "detailRange": "", "change": "목차 밖 정의", "definitions": []}
                records.append(rec)
                by_id[raw] = rec
                warnings.append({"code": "SPEC_NOT_IN_INDEX", "id": raw, "message": "상세 시트에만 있는 ID를 원문 그대로 보존했다.", "source": origin(path, row_no)})
            by_id[raw]["definitions"].append({"source": origin(path, row_no), "fields": fields})
            if not VALID_ID.fullmatch(raw):
                warnings.append({"code": "MALFORMED_SPEC_ID", "id": raw, "message": "명세 ID 형식 오류. 번호를 추정하거나 고치지 않는다.", "source": origin(path, row_no)})
    for rec in records:
        # 원문 추가 제안 8개의 분류다. 현재 구현 범위는 links.yaml.authority에서 별도로 해석한다.
        rec["scopeClass"] = "proposal" if "추가 제안" in rec["status"] and "파이프라인 상세 추가" in rec["change"] else "existing"
        if rec["id"] == "FS042" and "재무" in rec["title"] and any(
                "시점" in d["fields"].get("기능명", "") for d in rec["definitions"]):
            warnings.append({"code": "SPEC_ID_MEANING_CONFLICT", "id": rec["id"],
                             "message": "목차 FS042는 재무·실적, 상세 FS042는 FS0??를 승계한 시점 관계 그래프다. ID 정리는 완료됐지만 재무 폐기 선언은 없다. 두 의미를 별도로 추적한다.",
                             "source": rec["source"]})
        if len(rec["definitions"]) > 1:
            warnings.append({"code": "MULTIPLE_SPEC_DEFINITIONS", "id": rec["id"], "message": "동일 ID의 여러 상세 정의가 공존한다. 우선 문서를 자동 선택하지 않는다.", "source": rec["source"]})
        if not rec["definitions"]:
            warnings.append({"code": "SPEC_DETAIL_MISSING", "id": rec["id"], "message": "목차 ID에 대응하는 상세 정의가 없다.", "source": rec["source"]})
    return records


def import_requirements(folder: Path, warnings: list[dict]) -> list[dict]:
    files = [p for p in sorted(folder.glob("*.csv"))
             if any(r and r[0] == "요구사항 ID" and "필요 기능" in r for r in csv_rows(p))]
    if len(files) != 1:
        raise ValueError(f"요구사항 정의 CSV는 하나여야 한다: {folder} ({len(files)})")
    header(csv_rows(files[0]), ["요구사항 ID", "구분", "서비스(메뉴)", "필요 기능", "기능상세설명",
                              "Column 6", "우선순위", "확정 상태"], files[0])
    result = []
    for n, row in enumerate(csv_rows(files[0]), 1):
        if not row or not re.fullmatch(r"\d+(?:\.0)?", row[0].strip()):
            continue
        row += [""] * max(0, 8 - len(row))
        result.append({"id": number(row[0]), "group": row[1], "section": row[2],
                       "title": row[3], "description": row[4], "priority": row[6].strip(),
                       "status": row[7], "source": origin(files[0], n)})
    counts = Counter(r["id"] for r in result)
    for rec in result:
        if counts[rec["id"]] > 1:
            warnings.append({"code": "DUPLICATE_REQUIREMENT_ID", "id": rec["id"], "message": "중복 요구사항 번호. 모든 원본 행을 보존했다.", "source": rec["source"]})
    return result


def import_wbs(folder: Path, warnings: list[dict]) -> tuple[list[dict], dict]:
    files = [p for p in sorted(folder.glob("*.csv"))
             if any(len(r) > 2 and r[:3] == ["구분", "WBS", "업무"] for r in csv_rows(p))]
    if len(files) != 1:
        raise ValueError(f"WBS CSV는 하나여야 한다: {folder} ({len(files)})")
    path = files[0]
    rows = csv_rows(path)
    header_row, columns = header(rows, ["구분", "WBS", "업무", "유형", "산출물", "수행인력",
                                     "시작일", "종료일", "가중치", "진행률"], path)
    result = []
    for n, row in enumerate(rows, 1):
        if len(row) < len(columns) or not re.fullmatch(r"\d+(?:\.\d+)*", row[columns["WBS"]].strip()):
            continue
        value = lambda name: row[columns[name]]
        title = value("업무").strip()
        role = "FE" if "(FE)" in title else "BE" if "(BE)" in title else "공통/통합"
        result.append({"id": value("WBS").strip(), "title": title, "type": value("유형"),
                       "role": role, "deliverable": value("산출물"), "owners": value("수행인력"),
                       "start": value("시작일").split(" ")[0], "end": value("종료일").split(" ")[0],
                       "weight": value("가중치"), "progress": value("진행률"),
                       "rawSpecIds": list(dict.fromkeys(SPEC_ID.findall(title + " " + value("산출물")))),
                       "source": origin(path, n)})
        if not title:
            warnings.append({"code": "WBS_TITLE_MISSING", "id": value("WBS").strip(),
                             "message": "업무명이 비어 있다. 옛 번호의 업무를 현재 의미로 승계하지 않는다.",
                             "source": origin(path, n)})
    if len({r["id"] for r in result}) != len(result):
        raise ValueError("WBS 본문에 중복 ID가 있다.")
    ancillary = {relative(p): [{"source": origin(p, n), "cells": row}
                              for n, row in enumerate(csv_rows(p), 1) if any(row)]
                 for p in sorted(folder.glob("*.csv")) if p != path}
    proposal_tasks = [r for r in result if re.match(r"\(BE\)", r["title"]) and
                      any(f"FS{i:03}" in r["rawSpecIds"] for i in range(74, 82)) and
                      r["id"].startswith("6.6.") and 13 <= int(r["id"].split(".")[-1]) <= 20]
    for source_path, records in ancillary.items():
        for record in records:
            if any("6.5.13" in text and "6.5.20" in text for text in record["cells"]) and proposal_tasks:
                warnings.append({"code": "WBS_COVER_BODY_CONFLICT", "id": "FS074~FS081",
                                 "message": "표지/요약은 6.5.13~20·일정/가중치 미산정으로 소개하지만 본문은 6.6.13~20·P1·실명/기간/양수 가중치다. 원문 충돌은 정정 요청으로 보존하며 현재 요구 범위는 사용자 결정과 별도로 표시한다.",
                                 "source": record["source"]})
    return result, {"bodyHeader": {"source": origin(path, header_row), "columns": columns},
                    "ancillaryRows": ancillary}


def import_implementation(path: Path) -> list[dict]:
    """§5 기준선에 §0.1→0.2→0.3 반영 행을 덮는다. 원본 행과 설명은 남긴다."""
    baseline, updates = {}, []
    section = ""
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if line.startswith("## 5."):
            section = "baseline"
        elif line.startswith("### 0."):
            section = "update"
        elif line.startswith("## ") and not line.startswith("## 5."):
            section = ""
        if not line.startswith("| "):
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if not cols or not SPEC_ID.fullmatch(cols[0]):
            continue
        status = None
        if section == "baseline" and len(cols) >= 6:
            status = cols[3].replace("**", "")
            detail = cols[5]
        elif section == "update" and len(cols) >= 4:
            match = re.search(r"→\s*\*\*(.*?)\*\*", cols[2])
            if match:
                status = match[1]
            detail = cols[3]
        if status:
            rec = {"specId": cols[0], "status": status, "detail": detail,
                   "source": {"path": relative(path), "row": n, "rowUnit": "text-line"},
                   "codeLocations": re.findall(r"`(prototype/[^`]+)`", detail),
                   "evidenceKind": "문서 판정 인용(이번 생성기의 실행 검증 아님)"}
            if section == "baseline":
                baseline[cols[0]] = rec
            else:
                updates.append(rec)
    for rec in updates:
        baseline[rec["specId"]] = rec
    return list(baseline.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec-dir", type=Path, required=True)
    parser.add_argument("--wbs-dir", type=Path, required=True)
    parser.add_argument("--requirements-dir", type=Path, required=True)
    parser.add_argument("--screens", type=Path, default=ROOT / "docs/screen-plan/captures/slide-index.json")
    parser.add_argument("--gap", type=Path, default=ROOT / "docs/evidence/spec-v1.2-gap.md")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    warnings: list[dict] = []
    specs = import_specs(args.spec_dir, warnings)
    requirements = import_requirements(args.requirements_dir, warnings)
    tasks, wbs_sources = import_wbs(args.wbs_dir, warnings)
    screens = json.loads(args.screens.read_text())
    inputs = sorted({p for folder in (args.spec_dir, args.wbs_dir, args.requirements_dir)
                     for p in folder.iterdir() if p.suffix in (".csv", ".xlsx") or p.name == "_collection-manifest.json"}
                    | {args.screens, args.gap})
    catalog = {"schemaVersion": 1, "sources": {"specDir": relative(args.spec_dir), "wbsDir": relative(args.wbs_dir),
               "requirementsDir": relative(args.requirements_dir), "screens": relative(args.screens), "gap": relative(args.gap)},
               "fingerprints": {relative(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
               "specs": specs, "requirements": requirements, "wbs": tasks, "wbsSources": wbs_sources,
               "screens": [{**s, "source": {"path": relative(args.screens), "row": s["page"], "rowUnit": "slide-page"}}
                           for s in screens], "implementation": import_implementation(args.gap), "warnings": warnings}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(yaml.safe_dump(catalog, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"가져오기: 명세 {len(specs)}, 요구사항 원본 행 {len(requirements)}, WBS {len(tasks)}, 화면/설명 슬라이드 {len(screens)}, 경고 {len(warnings)}")
    print(f"기계 추출 원본: {relative(args.out)} (links.yaml·openapi.yaml은 변경하지 않음)")


if __name__ == "__main__":
    main()
