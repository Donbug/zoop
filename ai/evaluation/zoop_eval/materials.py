"""Read-only external development intake. No runner, scorer, or provider integration."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .contracts import (
    KLUE_RE_LABELS, MATERIAL_ARTIFACT_FIELDS, MATERIAL_CASE_FIELDS, MATERIAL_OBJECT_FIELDS,
    Rejected, SCHEMA_MATERIAL_GOLD,
    SCHEMA_MATERIAL_INPUTS, SCHEMA_MATERIAL_VALIDATION, choice, flag, integer,
    mapping, parse_json, reject, sequence, text, unique,
)

DEFAULT_MATERIALS = Path(__file__).resolve().parent.parent / "corpus" / "external-pilot-v1"
DATASETS = ("klue-re", "tatqa")
MAX_FILE_BYTES = 8 * 1024 * 1024
FILES = {f"{dataset}.{role}s.json" if role == "input" else f"{dataset}.gold.json": role
         for dataset in DATASETS for role in ("input", "gold")}
LIMITS = [
    "Development intake already inspected; source-order selection, not representative or held-out.",
    "Upstream annotations are not Zoop human-adjudicated gold.",
    "KLUE HF row-to-observed-revision binding remains unverified.",
    "Hashes establish local integrity, not publisher authenticity, legal clearance, or model-send approval.",
    "No model execution, answer inference, formula execution, quality score, or S3 predicate mapping.",
    "Existing score, verify-score and summary-verify-score do not accept these artifact families.",
]
_SOURCE_COMMON = ("id", "title", "creators", "upstream", "retrievalUrl", "license", "licenseUrl",
                  "licenseEvidence", "citation", "warranty", "modifications", "counts", "files")
_SOURCE_EXTRA = {
    "klue-re": ("dataset", "revisionObserved", "revisionBindingVerified", "revisionNote"),
    "tatqa": ("sourceBlobSha1", "sourceBytes", "sourceBlobVerified", "sourceVerification"),
}


def canonical(document: Any) -> str:
    """Sorted compact UTF-8 JSON; Decimal tokens never pass through binary float.

    Arrays retain source order. Decimal's exact base-10 value and trailing precision
    are preserved; exponent spelling is normalized by Decimal, not evaluated.
    """
    if isinstance(document, Decimal):
        if not document.is_finite():
            reject("json_non_finite", "non-finite material number")
        return str(document)
    if isinstance(document, dict):
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + canonical(document[k])
                              for k in sorted(document)) + "}"
    if isinstance(document, list):
        return "[" + ",".join(canonical(item) for item in document) + "]"
    return json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def digest(document: Any) -> str:
    return hashlib.sha256(canonical(document).encode("utf-8")).hexdigest()


def _require(condition: bool, code: str = "materials_invalid") -> None:
    if not condition:
        reject(code, "material contract rejected")


def _string(value: Any, *, nullable: bool = False) -> Any:
    _require(isinstance(value, str) or (nullable and value is None))
    return value


def _hex(value: Any, length: int) -> None:
    _require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d}" % length, value) is not None)


def _unicode(value: Any) -> None:
    if isinstance(value, str):
        value.encode("utf-8", errors="strict")
    elif isinstance(value, dict):
        for key, item in value.items():
            _unicode(key)
            _unicode(item)
    elif isinstance(value, list):
        for item in value:
            _unicode(item)


def _read(directory: int, name: str, expected: dict | None = None) -> tuple[Any, str]:
    # Only fixed basenames ever reach openat; no manifest-controlled path traversal.
    _require(name == "manifest.json" or name in FILES, "materials_path")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        found = os.fstat(fd)
        _require(stat.S_ISREG(found.st_mode), "materials_file_type")
        _require(found.st_size <= MAX_FILE_BYTES, "materials_file_size")
        if expected is not None:
            _require(found.st_size == expected["bytes"], "materials_size_mismatch")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
        _require(len(raw) <= MAX_FILE_BYTES, "materials_file_size")
        sha = hashlib.sha256(raw).hexdigest()
        if expected is not None:
            _require(len(raw) == expected["bytes"], "materials_size_mismatch")
            _require(sha == expected["sha256"], "materials_hash_mismatch")
        document = parse_json(raw.decode("utf-8"), "material", parse_float=Decimal)
        _unicode(document)
        return document, sha
    finally:
        os.close(fd)


def _manifest(value: Any) -> tuple[dict, dict]:
    m = mapping(value, "manifest", ("id", "collectedAt", "purpose", "collectionExecution", "limitations", "sources", "files"))
    _require(m["id"] == "external-pilot-v1")
    text(m["collectedAt"], "collectedAt")
    text(m["purpose"], "purpose")
    execution = mapping(m["collectionExecution"], "collectionExecution",
                        ("modelsCalled", "upstreamCodeExecuted", "adapterOrScorerImplemented"))
    for value in execution.values():
        _require(flag(value, "collectionExecution") is False)
    for item in sequence(m["limitations"], "limitations", 1):
        text(item, "limitation")
    files = {}
    for item in sequence(m["files"], "files", 4):
        item = mapping(item, "file", ("path", "role", "sha256", "bytes"))
        path = text(item["path"], "path")
        _require(path in FILES, "materials_path")
        _require(path not in files, "materials_duplicate_id")
        _require(item["role"] == FILES[path], "materials_role")
        _hex(item["sha256"], 64)
        _require(0 < integer(item["bytes"], "bytes") <= MAX_FILE_BYTES, "materials_file_size")
        files[path] = item
    _require(set(files) == set(FILES))
    sources = {}
    for source in sequence(m["sources"], "sources", 2):
        _require(isinstance(source, dict))
        dataset = choice(source.get("id"), DATASETS, "source.id")
        source = mapping(source, "source", _SOURCE_COMMON + _SOURCE_EXTRA[dataset])
        _require(dataset not in sources, "materials_duplicate_id")
        for key in ("title", "upstream", "retrievalUrl", "license", "licenseUrl", "licenseEvidence", "citation", "warranty", "modifications"):
            text(source[key], key)
        for creator in sequence(source["creators"], "creators", 1):
            text(creator, "creator")
        _require(source["files"] == [f"{dataset}.inputs.json", f"{dataset}.gold.json"], "materials_role")
        keys = ("records", "entitySpansChecked") if dataset == "klue-re" else ("contexts", "questions")
        counts = mapping(source["counts"], "counts", keys)
        for count in counts.values():
            integer(count, "count", 1)
        if dataset == "klue-re":
            _require(source["license"] == "CC-BY-SA-4.0" and source["dataset"] == "https://huggingface.co/datasets/klue/klue")
            _hex(source["revisionObserved"], 40)
            _require(source["revisionBindingVerified"] is False)
            text(source["revisionNote"], "revisionNote")
        else:
            _require(source["license"] == "CC-BY-4.0")
            _hex(source["sourceBlobSha1"], 40)
            integer(source["sourceBytes"], "sourceBytes", 1)
            flag(source["sourceBlobVerified"], "sourceBlobVerified")
            text(source["sourceVerification"], "sourceVerification")
        sources[dataset] = source
    _require(set(sources) == set(DATASETS))
    return files, sources


def _provenance(manifest: dict, sha: str, sources: list[dict], files: list[dict]) -> dict:
    return {"manifestSha256": sha, "collectedAt": manifest["collectedAt"], "purpose": manifest["purpose"],
            "collectionExecution": manifest["collectionExecution"], "collectionLimitations": manifest["limitations"],
            "sources": sources, "verifiedFiles": files}


def _artifact(schema: str, **fields: Any) -> dict:
    document = {"schema": schema, "ok": True, "materialsId": "external-pilot-v1", "status": "development-intake",
                "limits": LIMITS, **fields}
    mapping(document["provenance"], "provenance", MATERIAL_OBJECT_FIELDS["provenance"])
    if schema != SCHEMA_MATERIAL_VALIDATION:
        for case in document["cases"]:
            mapping(case, "case", MATERIAL_CASE_FIELDS[(schema, document["dataset"])])
    if schema == SCHEMA_MATERIAL_INPUTS:
        mapping(document["normalization"], "normalization", MATERIAL_OBJECT_FIELDS["normalization"])
        for context in document["contexts"]:
            mapping(context, "context", MATERIAL_OBJECT_FIELDS["context"])
            for paragraph in context["paragraphs"]:
                mapping(paragraph, "paragraph", MATERIAL_OBJECT_FIELDS["paragraph"])
        if document["dataset"] == "klue-re":
            for case in document["cases"]:
                for key in ("subjectEntity", "objectEntity"):
                    mapping(case[key], "entity", MATERIAL_OBJECT_FIELDS["entity"])
                    mapping(case[key]["span"], "span", MATERIAL_OBJECT_FIELDS["span"])
    return mapping(document, "artifact", MATERIAL_ARTIFACT_FIELDS[schema])


def _entity(value: Any, sentence: str) -> dict:
    entity = mapping(value, "entity", ("word", "start_idx", "end_idx", "type"))
    word = text(entity["word"], "entity.word")
    start = integer(entity["start_idx"], "start_idx")
    end = integer(entity["end_idx"], "end_idx")
    _require(start <= end < len(sentence) and sentence[start:end + 1] == word, "materials_span")
    kind = choice(entity["type"], ("PER", "ORG", "POH", "DAT", "LOC", "NOH"), "entity.type")
    return {"text": word, "type": kind, "span": {"start": start, "end": end + 1, "unit": "unicode-codepoint", "endExclusive": True}}


def _klue_inputs(value: Any, source: dict) -> tuple[list, list]:
    doc = mapping(value, "klue input", ("dataset", "configuration", "split", "selection", "records"))
    _require(doc["dataset"] == "klue/klue" and doc["configuration"] == "re" and doc["split"] == "train")
    text(doc["selection"], "selection")
    cases = []
    for row in sequence(doc["records"], "records", 1):
        row = mapping(row, "record", ("guid", "sentence", "subject_entity", "object_entity", "source"))
        sentence = text(row["sentence"], "sentence")
        cases.append({"guid": text(row["guid"], "guid"), "sentence": sentence, "source": text(row["source"], "source"),
                      "subjectEntity": _entity(row["subject_entity"], sentence),
                      "objectEntity": _entity(row["object_entity"], sentence)})
    unique([case["guid"] for case in cases], "guids", "materials_duplicate_id")
    _require(source["counts"] == {"records": len(cases), "entitySpansChecked": 2 * len(cases)}, "materials_counts")
    return [], cases


def _tatqa_inputs(value: Any, source: dict) -> tuple[list, list]:
    doc = mapping(value, "tatqa input", ("dataset", "split", "selection", "records"))
    _require(doc["dataset"] == "NExTplusplus/TAT-QA" and doc["split"] == "dev")
    text(doc["selection"], "selection")
    contexts, cases, ids = [], [], []
    for row in sequence(doc["records"], "records", 1):
        row = mapping(row, "context", ("table", "paragraphs", "questions"))
        table = mapping(row["table"], "table", ("uid", "table"))
        uid = text(table["uid"], "table.uid")
        ids.append(uid)
        cells = sequence(table["table"], "table.cells", 1)
        for cells_row in cells:
            for cell in sequence(cells_row, "table.row", 1):
                _string(cell)
        paragraphs, orders = [], []
        for paragraph in sequence(row["paragraphs"], "paragraphs"):
            paragraph = mapping(paragraph, "paragraph", ("uid", "order", "text"))
            ids.append(text(paragraph["uid"], "paragraph.uid"))
            orders.append(integer(paragraph["order"], "paragraph.order", 1))
            _string(paragraph["text"])
            paragraphs.append(paragraph)
        unique(orders, "paragraph orders", "materials_duplicate_id")
        contexts.append({"tableUid": uid, "table": cells, "paragraphs": paragraphs})
        orders = []
        for question in sequence(row["questions"], "questions", 1):
            question = mapping(question, "question", ("uid", "order", "question"))
            ids.append(text(question["uid"], "question.uid"))
            orders.append(integer(question["order"], "question.order", 1))
            cases.append({"uid": question["uid"], "order": question["order"],
                          "question": text(question["question"], "question"), "contextId": uid})
        unique(orders, "question orders", "materials_duplicate_id")
    unique(ids, "source ids", "materials_duplicate_id")
    _require(source["counts"] == {"contexts": len(contexts), "questions": len(cases)}, "materials_counts")
    return contexts, cases


def _inputs(directory: int, dataset: str, manifest: dict, sha: str, files: dict, source: dict) -> dict:
    path = f"{dataset}.inputs.json"
    doc, _ = _read(directory, path, files[path])
    contexts, cases = (_klue_inputs if dataset == "klue-re" else _tatqa_inputs)(doc, source)
    normalization = {"split": doc["split"], "selection": doc["selection"],
                     "method": "inclusive-to-half-open-codepoint" if dataset == "klue-re" else "context-reference-and-source-order",
                     "modifications": "Preserved source text, IDs, order and units; no translation, date inference or formula execution."}
    return _artifact(SCHEMA_MATERIAL_INPUTS, dataset=dataset, validationScope="manifest-and-selected-input-only",
                     provenance=_provenance(manifest, sha, [source], [files[path]]), normalization=normalization,
                     contexts=contexts, cases=cases, choices=list(KLUE_RE_LABELS) if dataset == "klue-re" else [])


def _klue_gold(doc: Any, inputs: dict) -> tuple[str, list]:
    doc = mapping(doc, "klue gold", ("dataset", "annotationStatus", "labels", "records"))
    _require(doc["dataset"] == "klue/klue" and doc["labels"] == list(KLUE_RE_LABELS), "materials_labels")
    cases = {}
    for row in sequence(doc["records"], "gold.records", 1):
        row = mapping(row, "gold record", ("guid", "label", "labelName"))
        uid = text(row["guid"], "guid")
        _require(uid not in cases, "materials_duplicate_id")
        label = integer(row["label"], "label")
        _require(label < len(KLUE_RE_LABELS) and row["labelName"] == KLUE_RE_LABELS[label], "materials_labels")
        cases[uid] = {"guid": uid, "labelId": label, "label": KLUE_RE_LABELS[label]}
    _require(set(cases) == {case["guid"] for case in inputs["cases"]}, "materials_identity")
    _require(doc["annotationStatus"] == "upstream labels; not independently reviewed by Zoop")
    return doc["annotationStatus"], [cases[case["guid"]] for case in inputs["cases"]]


def _answer(value: Any) -> None:
    # Upstream span lists include empty strings. Null/empty unknowns remain unknown.
    if value is None or isinstance(value, str) or type(value) is int:
        return
    if isinstance(value, Decimal):
        _require(value.is_finite(), "json_non_finite")
        return
    if isinstance(value, list):
        for item in value:
            _string(item)
        return
    reject("materials_answer", "unsupported answer type")


def _tatqa_gold(doc: Any, inputs: dict) -> tuple[str, list]:
    doc = mapping(doc, "tatqa gold", ("dataset", "annotationStatus", "records"))
    _require(doc["dataset"] == "NExTplusplus/TAT-QA")
    contexts = {context["tableUid"]: context for context in inputs["contexts"]}
    expected = {case["uid"]: case["contextId"] for case in inputs["cases"]}
    seen, cases = set(), {}
    for row in sequence(doc["records"], "gold.records", 1):
        row = mapping(row, "gold context", ("tableUid", "questions"))
        uid = text(row["tableUid"], "tableUid")
        _require(uid not in seen, "materials_duplicate_id")
        _require(uid in contexts, "materials_identity")
        seen.add(uid)
        paragraphs = {str(p["order"]): p["uid"] for p in contexts[uid]["paragraphs"]}
        for question in sequence(row["questions"], "gold.questions", 1):
            question = mapping(question, "annotation", ("uid", "answer", "derivation", "answer_type", "answer_from",
                                                       "rel_paragraphs", "req_comparison", "scale"))
            qid = text(question["uid"], "question.uid")
            _require(qid not in cases, "materials_duplicate_id")
            _require(expected.get(qid) == uid, "materials_identity")
            _answer(question["answer"])
            for key in ("derivation", "answer_type", "answer_from", "scale"):
                _string(question[key], nullable=True)
            # These annotation strings are opaque upstream values, not guessed enums.
            # Null and empty values are retained without inventing an answer or support.
            if question["req_comparison"] is not None:
                flag(question["req_comparison"], "req_comparison")
            related = question["rel_paragraphs"]
            paragraph_ids = None
            if related is not None:
                related = sequence(related, "rel_paragraphs")
                for order in related:
                    _require(isinstance(order, str) and order in paragraphs, "materials_paragraph")
                unique(related, "rel_paragraphs", "materials_duplicate_id")
                paragraph_ids = [paragraphs[order] for order in related]
            cases[qid] = {**question, "contextId": uid, "paragraphIds": paragraph_ids}
    _require(seen == set(contexts) and set(cases) == set(expected), "materials_identity")
    _require(doc["annotationStatus"] == "upstream annotations; not independently reviewed by Zoop")
    return doc["annotationStatus"], [cases[case["uid"]] for case in inputs["cases"]]


def _gold(directory: int, dataset: str, inputs: dict, manifest: dict, sha: str, files: dict, source: dict) -> dict:
    path = f"{dataset}.gold.json"
    doc, _ = _read(directory, path, files[path])
    status, cases = (_klue_gold if dataset == "klue-re" else _tatqa_gold)(doc, inputs)
    return _artifact(SCHEMA_MATERIAL_GOLD, dataset=dataset, validationScope="manifest-and-selected-input-and-gold",
                     provenance=_provenance(manifest, sha, [source], [files[f"{dataset}.inputs.json"], files[path]]),
                     inputsSha256=digest(inputs), annotationStatus=status, cases=cases)


def convert_materials(command: str, materials: Path = DEFAULT_MATERIALS, dataset: str | None = None) -> dict:
    """All-or-nothing boundary; rejection messages never quote file content or paths."""
    directory = None
    try:
        _require(command in ("materials-inputs", "materials-gold", "materials-validate"))
        if command != "materials-validate":
            choice(dataset, DATASETS, "dataset")
        _require(not any(part.startswith(".env") for part in materials.parts), "materials_path")
        directory = os.open(materials, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        manifest, sha = _read(directory, "manifest.json")
        files, sources = _manifest(manifest)
        if command != "materials-validate":
            inputs = _inputs(directory, dataset, manifest, sha, files, sources[dataset])
            if command == "materials-inputs":
                return inputs
            return _gold(directory, dataset, inputs, manifest, sha, files, sources[dataset])
        counts, bindings = {}, {}
        for selected in DATASETS:
            inputs = _inputs(directory, selected, manifest, sha, files, sources[selected])
            gold = _gold(directory, selected, inputs, manifest, sha, files, sources[selected])
            counts[selected] = sources[selected]["counts"]
            bindings[selected] = gold["inputsSha256"]
        return _artifact(SCHEMA_MATERIAL_VALIDATION, validationScope="manifest-and-all-inputs-and-gold",
                         provenance=_provenance(manifest, sha, [sources[d] for d in DATASETS], list(files.values())),
                         counts=counts, inputsSha256=bindings)
    except Rejected as exc:
        raise Rejected(exc.code, "external material validation rejected; no artifact emitted") from None
    except OSError:
        raise Rejected("materials_unreadable", "required material is not safely readable") from None
    except (ValueError, TypeError, OverflowError, RecursionError, InvalidOperation):
        raise Rejected("materials_invalid", "external material structure or encoding rejected") from None
    finally:
        if directory is not None:
            os.close(directory)
