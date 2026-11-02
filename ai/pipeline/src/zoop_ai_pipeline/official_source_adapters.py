"""Official discovery protocols, with raw-container provenance and no publication grant.

The caller owns persistence, queue admission and authorization. Tasks are secret-free,
continuations are explicit, and executing one task never recursively fetches another.
OPENDART_API_KEY is supplied only at runtime; the API requires it on the wire, but
neither task URLs, returned observations nor transport logs contain it. Nothing here
reads environment variables or imports/executes the historical PoC.

Protocol references: OpenDART DS001/2019001, 2019003 and 2019018; SEC EDGAR
Application Programming Interfaces (2025-04-08); Federal Register documents API.
"""
from __future__ import annotations

import calendar
import io
import json
import logging
import re
import stat
import threading
import time
import zipfile
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

from lxml import etree, html
from pydantic import Field

from .collection import Fetcher, Fetched
from .collection_contracts import Policy
from .ingestion_contracts import IngestionFailure, MAX_RAW, byte_hash, digest
from .ingestion_parsers import _mapped, prepare
from .ingestion_url import canonical_url

SOURCES = ("fsc-press", "federal-register-bis", "opendart", "sec-edgar")
ORIGINS = {"fsc-press": "https://www.fsc.go.kr", "federal-register-bis": "https://www.federalregister.gov",
           "opendart": "https://opendart.fss.or.kr", "sec-edgar": "https://data.sec.gov"}
PROFILE = {"parser": "zoop-official-source-1", "mappingVersion": "unicode-copy-segments-1",
           "xmlEntities": "forbidden", "coordinates": "container-member-xpath-text-slot-1"}
FSC_SCOPE = "//*[contains(concat(' ',normalize-space(@class),' '),' board-view-wrap ')]//*[contains(concat(' ',normalize-space(@class),' '),' cont ')]"
MAX_MEMBERS = 1000
MAX_EXPANDED = 64_000_000
MAX_ROWS = 200_000
MEDIA = ["application/json", "application/xml", "text/xml", "application/zip", "application/x-zip-compressed",
         "application/octet-stream", "text/plain", "text/html"]
_SEC_LOCK = threading.Lock()
_SEC_LAST = 0.0


class OfficialPolicy(Policy):
    # Per-set resource bounds, not business/document/day quotas.
    max_requests: int = Field(ge=1)
    max_total_seconds: int = Field(ge=1)
    max_total_bytes: int = Field(ge=1)
    allowed_media_types: list[Literal["application/json", "application/xml", "text/xml", "application/zip",
                                    "application/x-zip-compressed", "application/octet-stream", "text/plain", "text/html"]]


@dataclass(frozen=True)
class OfficialTask:
    source_id: str
    kind: str
    url: str
    from_day: str
    through_day: str
    context: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class OfficialPlan:
    source_id: str
    tasks: tuple[OfficialTask, ...]
    prerequisites: tuple[str, ...]
    coverage: str


@dataclass(frozen=True)
class ResponseRef:
    source_id: str
    task_key: str
    request_url: str
    final_url: str
    observed_at: str
    media_type: str
    raw_sha256: str
    raw_bytes: int
    robots: tuple[dict, ...]


@dataclass(frozen=True)
class OfficialCandidate:
    source_id: str
    candidate_id: str
    url: str
    title: str | None
    publication: dict
    observed_at: str
    response_sha256: str
    source_ref: str
    facts: dict
    body_task: OfficialTask | None
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemberRef:
    name: str
    sha256: str
    size: int
    representation: str
    raw: bytes = field(repr=False)

    def metadata(self) -> dict:
        return {"name": self.name, "sha256": self.sha256, "bytes": self.size, "representation": self.representation}


@dataclass(frozen=True)
class OfficialResult:
    response: ResponseRef
    raw: bytes = field(repr=False)
    candidates: tuple[OfficialCandidate, ...] = ()
    next_tasks: tuple[OfficialTask, ...] = ()
    members: tuple[MemberRef, ...] = ()
    prepared: dict | None = None
    limitations: tuple[str, ...] = ()
    status: str = "ok"

    def extraction(self) -> dict:
        """A distinct v2 extraction envelope: raw remains the actual JSON/XML/ZIP/HTML."""
        return {"schemaVersion": "zoop-official-extraction-1", "backend": "official-source",
                "response": {**asdict(self.response), "robots": list(self.response.robots)}, "members": [member.metadata() for member in self.members],
                "prepared": self.prepared, "normalizationProfile": PROFILE,
                "limitations": list(self.limitations), "rights": "unconfirmed", "modelSend": False, "publicUse": False}


def _day(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return parsed
    except (ValueError, TypeError):
        raise IngestionFailure("official_date_invalid") from None


def _window(first: str, last: str) -> tuple[date, date]:
    begin, end = _day(first), _day(last)
    if not 0 <= (end - begin).days < 366:
        raise IngestionFailure("official_window_exceeds_366_days")
    return begin, end


def _origin(source: str, synthetic_origin: str | None) -> str:
    if source not in SOURCES:
        raise IngestionFailure("official_source_unsupported")
    if synthetic_origin is None:
        return ORIGINS[source]
    try:
        parts = urlsplit(synthetic_origin)
        if (parts.hostname != "127.0.0.1" or parts.scheme != "http" or not parts.port or
                synthetic_origin != f"http://127.0.0.1:{parts.port}"):
            raise ValueError
    except ValueError:
        raise IngestionFailure("official_synthetic_origin_invalid") from None
    return synthetic_origin


def _task(source, kind, origin, path, first, last, context=None, params=None):
    return OfficialTask(source, kind, origin + path + ("?" + urlencode(params) if params else ""), first, last, context or {})


def _dart_list(origin, first, last, *, corp=None, page=1):
    params = {"bgn_de": first.replace("-", ""), "end_de": last.replace("-", ""), "last_reprt_at": "N",
              "sort": "date", "sort_mth": "desc", "page_count": "100", "page_no": str(page)}
    if corp is not None:
        params["corp_code"] = corp
    return _task("opendart", "dart-list", origin, "/api/list.json", first, last,
                 {"corpCode": corp, "page": page}, params)


def _bis_list(origin, first, last, page=1):
    return _task("federal-register-bis", "bis-list", origin, "/api/v1/documents.json", first, last,
                 {"page": page}, {"conditions[agencies][]": "industry-and-security-bureau",
                 "conditions[publication_date][gte]": first, "conditions[publication_date][lte]": last,
                 "order": "oldest", "per_page": "1000", "page": str(page)})


def plan(source_id: str, from_day: str, through_day: str, *, tickers: tuple[str, ...] = (),
         ciks: tuple[str, ...] = (), synthetic_origin: str | None = None) -> OfficialPlan:
    begin, end = _window(from_day, through_day)
    origin = _origin(source_id, synthetic_origin)
    if source_id == "fsc-press":
        tasks = (_task(source_id, "fsc-rss", origin, "/about/fsc_bbs_rss/?fid=0111", from_day, through_day),)
        return OfficialPlan(source_id, tasks, (), "rolling RSS only; older archive and attachments unassessed")
    if source_id == "federal-register-bis":
        return OfficialPlan(source_id, (_bis_list(origin, from_day, through_day),), (),
                            "agency-filtered Federal Register only; unofficial presentation, not all BIS announcements")
    if source_id == "sec-edgar":
        if any(not re.fullmatch(r"[0-9]{1,10}", cik) or int(cik) == 0 for cik in ciks):
            raise IngestionFailure("official_cik_invalid")
        tasks = tuple(_task(source_id, "sec-submissions", origin, f"/submissions/CIK{int(cik):010d}.json",
                            from_day, through_day, {"cik": str(int(cik))}) for cik in dict.fromkeys(ciks))
        return OfficialPlan(source_id, tasks, ("declared SEC operator company/contact User-Agent",) +
                            (() if ciks else ("operator-selected actual CIK identifiers",)),
                            "recent submissions and overlapping advertised past files; primary documents only")
    if any(not re.fullmatch(r"[0-9]{6}", ticker) for ticker in tickers):
        raise IngestionFailure("official_ticker_invalid")
    if tickers:
        tasks = (_task(source_id, "dart-corps", origin, "/api/corpCode.xml", from_day, through_day,
                       {"tickers": list(dict.fromkeys(tickers))}),)
    else:
        tasks_list = []
        cursor = begin
        while cursor <= end:
            # No corp_code: OpenDART's current documented limit is three calendar months.
            month = cursor.month - 1 + 3
            year, month = cursor.year + month // 12, month % 12 + 1
            boundary = date(year, month, min(cursor.day, calendar.monthrange(year, month)[1]))
            last = min(end, boundary - timedelta(days=1))
            tasks_list.append(_dart_list(origin, cursor.isoformat(), last.isoformat()))
            cursor = last + timedelta(days=1)
        tasks = tuple(tasks_list)
    return OfficialPlan(source_id, tasks, ("runtime OPENDART_API_KEY (40 characters; never persisted)",),
                        "all paginated receipts including corrections; KIND coverage is not implied")


def source_matrix(from_day: str, through_day: str) -> list[dict]:
    return [{"sourceId": source, "adapter": "official-source", "implemented": True,
             "state": "credential-blocked" if source == "opendart" else "operator-prerequisite" if source == "sec-edgar" else "supported",
             "prerequisites": list((p := plan(source, from_day, through_day)).prerequisites), "coverage": p.coverage,
             "liveAccess": "unchecked", "publicUse": False} for source in SOURCES]


class _SecretFilter(logging.Filter):
    def __init__(self, secret):
        super().__init__()
        self.secret = secret

    def filter(self, record):
        # httpx logs URLs at INFO, even on successful requests. Never let the secret
        # reach a handler; also cover exception messages containing an echoed URL.
        return self.secret not in record.getMessage()


class OfficialFetcher(Fetcher):
    """Existing DNS/robots/resource guards; credentials never enter public task URLs.

    SEC pacing is process-wide across data.sec.gov and www.sec.gov. The controller
    must serialize SEC processes too: the SEC's ten-rps limit covers the operator,
    not one client instance. No automatic retry on status/timeout/redirect.
    """
    def __init__(self, policy: OfficialPolicy, source_id: str, *, synthetic_origin: str | None = None,
                 sec_company: str | None = None, sec_contact: str | None = None, **options):
        self.source_id, self.origin = source_id, _origin(source_id, synthetic_origin)
        self.synthetic_origin = synthetic_origin
        if bool(synthetic_origin) != policy.synthetic_loopback:
            raise IngestionFailure("official_synthetic_policy_mismatch")
        if source_id == "sec-edgar":
            if (not sec_company or not sec_contact or not sec_company.strip() or
                    not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", sec_contact) or
                    any(ord(c) < 32 or ord(c) > 126 for c in sec_company + sec_contact) or
                    len(sec_company + sec_contact) > 198):
                raise IngestionFailure("sec_operator_contact_required")
            if not synthetic_origin and (sec_contact.rsplit("@", 1)[1].lower().endswith(
                    (".example", ".invalid", ".test", ".localhost")) or
                    sec_contact.rsplit("@", 1)[1].lower() in {"example.com", "example.org", "example.net"}):
                raise IngestionFailure("sec_operator_contact_required")
            policy = policy.model_copy(update={"user_agent": sec_company + " " + sec_contact, "contact_url": None,
                                               "min_interval_seconds": max(0.1, policy.min_interval_seconds)})
        hosts = [urlsplit(self.origin).hostname]
        if source_id == "sec-edgar" and not synthetic_origin:
            hosts.append("www.sec.gov")
        super().__init__(policy, hosts, **options)
        self._runtime_key = None

    def _guard(self, value):
        url, host = super()._guard(value)
        parts = urlsplit(url)
        if any(key.lower() in {"crtfc_key", "api_key", "apikey", "token"} for key, _ in parse_qsl(parts.query)):
            raise IngestionFailure("official_secret_in_task_url")
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin != self.origin and not (self.source_id == "sec-edgar" and not self.synthetic_origin and origin == "https://www.sec.gov"):
            raise IngestionFailure("official_source_binding_mismatch")
        if parts.path != "/robots.txt" and not _route(self.source_id, parts.path):
            raise IngestionFailure("official_source_binding_mismatch")
        return url, host

    def _check(self, response, host, limit):
        super()._check(response, host, limit)
        if 300 <= response.status_code < 400:
            # In particular, a credentialed redirect is never followed or retained.
            raise IngestionFailure("official_redirect_not_allowed")

    def _get(self, url, host, deadline, limit):
        key = self._runtime_key if self.source_id == "opendart" and urlsplit(url).path != "/robots.txt" else None
        if self.source_id == "opendart" and self._runtime_key is None:
            raise IngestionFailure("opendart_credentials_required")
        if key is not None:
            url += ("&" if urlsplit(url).query else "?") + urlencode({"crtfc_key": key})
        filters = []
        if key:
            for name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"):
                logger = logging.getLogger(name)
                guard = _SecretFilter(key)
                logger.addFilter(guard)
                filters.append((logger, guard))
        failure = None
        try:
            if self.source_id == "sec-edgar":
                global _SEC_LAST
                with _SEC_LOCK:
                    wait = _SEC_LAST + 0.1 - time.monotonic()
                    if wait > 0:
                        if wait >= self._remaining(deadline):
                            raise IngestionFailure("rate_limit")
                        time.sleep(wait)
                    _SEC_LAST = time.monotonic()
                    result = super()._get(url, host, deadline, limit)
            else:
                result = super()._get(url, host, deadline, limit)
            if key and (key.encode() in result[2] or any(key in value for value in result[1].values())):
                failure = "official_secret_echo_refused"
        except IngestionFailure as exc:
            failure = exc.code
        finally:
            for logger, guard in filters:
                logger.removeFilter(guard)
        if failure is not None:
            # Raised outside the except block: no credential-bearing exception chain.
            raise IngestionFailure(failure)
        return result

    def fetch_task(self, task: OfficialTask, *, runtime_key: str | None = None) -> Fetched:
        if task.source_id != self.source_id:
            raise IngestionFailure("official_source_binding_mismatch")
        validate_task(task, synthetic_origin=self.synthetic_origin)
        if self.source_id == "opendart":
            if runtime_key is None:
                raise IngestionFailure("opendart_credentials_required")
            if not isinstance(runtime_key, str) or not re.fullmatch(r"[A-Za-z0-9]{40}", runtime_key):
                raise IngestionFailure("opendart_credentials_invalid")
        self._runtime_key = runtime_key
        try:
            return super().fetch(task.url)
        finally:
            self._runtime_key = None


def _route(source, path):
    routes = {"opendart": r"/api/(?:corpCode\.xml|list\.json|document\.xml)",
              "federal-register-bis": r"/(?:api/v1/documents(?:/[0-9]{4}-[0-9]+)?\.json|documents/(?:full_text/(?:text|html)/)?[0-9]{4}/[0-9]{2}/[0-9]{2}/[0-9]{4}-[0-9]+(?:\.(?:txt|html)|/[^/?]+)?)",
              "fsc-press": r"/(?:about/fsc_bbs_rss/|no010101/[0-9]+)",
              "sec-edgar": r"/(?:submissions/CIK[0-9]{10}(?:-submissions-[0-9]+)?\.json|Archives/edgar/data/[0-9]+/[0-9]{18}/[A-Za-z0-9_.-]+)"}
    return re.fullmatch(routes[source], path) is not None


def _bound_link(source, value, synthetic_origin=None):
    try:
        parsed, host = canonical_url(value)
        parts = urlsplit(parsed)
        allowed = {_origin(source, synthetic_origin)}
        if source == "sec-edgar" and synthetic_origin is None:
            allowed.add("https://www.sec.gov")
        if (f"{parts.scheme}://{parts.netloc}" not in allowed or not _route(source, parts.path) or
                any(key.lower() in {"crtfc_key", "api_key", "apikey", "token"} for key, _ in parse_qsl(parts.query))):
            raise ValueError
        return parsed
    except (ValueError, TypeError, IngestionFailure):
        raise IngestionFailure("official_source_binding_mismatch") from None


def validate_task(task: OfficialTask, *, synthetic_origin: str | None = None):
    _window(task.from_day, task.through_day)
    origin = _origin(task.source_id, synthetic_origin)
    _bound_link(task.source_id, task.url, synthetic_origin)
    c = task.context
    if task.kind == "dart-list":
        expected = _dart_list(origin, task.from_day, task.through_day, corp=c.get("corpCode"), page=c.get("page"))
        corp, page = c.get("corpCode"), c.get("page")
        if type(page) is not int or page < 1 or corp is not None and not re.fullmatch(r"[0-9]{8}", corp):
            raise IngestionFailure("official_task_invalid")
        if corp is None:
            planned = plan("opendart", task.from_day, task.through_day, synthetic_origin=synthetic_origin)
            if len(planned.tasks) != 1:
                raise IngestionFailure("official_task_invalid")
    elif task.kind == "bis-list":
        if type(c.get("page")) is not int or c["page"] < 1:
            raise IngestionFailure("official_task_invalid")
        expected = _bis_list(origin, task.from_day, task.through_day, c["page"])
    elif task.kind in {"dart-corps", "sec-submissions", "fsc-rss"}:
        options = {"tickers": tuple(c.get("tickers", ()))} if task.kind == "dart-corps" else {"ciks": (c.get("cik", ""),)} if task.kind == "sec-submissions" else {}
        expected = plan(task.source_id, task.from_day, task.through_day, synthetic_origin=synthetic_origin, **options).tasks[0]
    else:
        kinds = {"dart-document": "opendart", "bis-detail": "federal-register-bis", "bis-body": "federal-register-bis",
                 "fsc-body": "fsc-press", "sec-past": "sec-edgar", "sec-body": "sec-edgar"}
        if kinds.get(task.kind) != task.source_id:
            raise IngestionFailure("official_task_invalid")
        if task.kind == "dart-document":
            receipt = c.get("candidateId", "")
            if not re.fullmatch(r"[0-9]{14}", receipt):
                raise IngestionFailure("official_task_invalid")
            expected = replace(task, url=origin + "/api/document.xml?" + urlencode({"rcept_no": receipt}))
        elif task.kind == "bis-detail":
            number = c.get("candidateId", "")
            if not re.fullmatch(r"[0-9]{4}-[0-9]+", number):
                raise IngestionFailure("official_task_invalid")
            expected = replace(task, url=origin + "/api/v1/documents/" + number + ".json")
        elif task.kind == "sec-past":
            cik = c.get("cik", "")
            if not re.fullmatch(r"[0-9]{1,10}", cik) or not re.fullmatch(
                    rf"/submissions/CIK{int(cik):010d}-submissions-[0-9]+\.json", urlsplit(task.url).path):
                raise IngestionFailure("official_task_invalid")
            expected = task
        else:
            expected = task
            identifier = c.get("candidateId")
            if not identifier or not re.fullmatch(r"[0-9a-f]{64}", c.get("discoverySha256", "")):
                raise IngestionFailure("official_task_invalid")
            parts = urlsplit(task.url)
            if task.kind == "fsc-body":
                valid = parts.path == "/no010101/" + identifier
            elif task.kind == "bis-body":
                valid = not parts.query and re.fullmatch(
                    r"/documents/full_text/(?:text|html)/[0-9]{4}/[0-9]{2}/[0-9]{2}/" +
                    re.escape(identifier) + r"\.(?:txt|html)", parts.path)
            else:
                cik = c.get("facts", {}).get("cik", "")
                valid = (not parts.query and re.fullmatch(r"[0-9]{1,10}", cik) and
                         re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", identifier) and
                         re.fullmatch(r"/Archives/edgar/data/" + re.escape(cik) + "/" +
                                      identifier.replace("-", "") + r"/[A-Za-z0-9_][A-Za-z0-9_.-]*", parts.path) and
                         ".." not in parts.path)
            if not valid:
                raise IngestionFailure("official_task_invalid")
    if expected != task:
        raise IngestionFailure("official_task_invalid")


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result
    try:
        data = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (ValueError, UnicodeError):
        raise IngestionFailure("official_json_invalid") from None


def _xml(raw):
    if b"<!DOCTYPE" in raw.replace(b"\x00", b"").upper() or b"<!ENTITY" in raw.replace(b"\x00", b"").upper():
        raise IngestionFailure("official_xml_entities_forbidden")
    try:
        return etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False))
    except etree.XMLSyntaxError:
        raise IngestionFailure("official_xml_invalid") from None


def _zip(raw):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_MEMBERS or sum(info.file_size for info in infos) > MAX_EXPANDED:
                raise IngestionFailure("official_zip_size_limit")
            names, members = set(), []
            for info in infos:
                path = PurePosixPath(info.filename)
                mode = info.external_attr >> 16
                if (info.filename in names or info.orig_filename != info.filename or "\\" in info.filename or
                        path.is_absolute() or any(part in {"..", "."} for part in info.filename.split("/")) or
                        ":" in info.filename or info.flag_bits & 1 or stat.S_ISLNK(mode) or
                        info.is_dir() or info.file_size > MAX_RAW or
                        info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}):
                    raise IngestionFailure("official_zip_member_unsafe")
                names.add(info.filename)
                content = archive.read(info)
                if len(content) != info.file_size:
                    raise IngestionFailure("official_zip_size_limit")
                is_html = re.match(rb"(?:\xef\xbb\xbf)?\s*(?:<!doctype\s+html[^>]*>\s*)?<html(?:\s|>)", content, re.I)
                representation = "html" if is_html else "xml" if path.suffix.lower() == ".xml" else "unsupported"
                members.append(MemberRef(info.filename, byte_hash(content), len(content), representation, content))
            return tuple(members)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError):
        raise IngestionFailure("official_zip_invalid") from None


def _publication(raw, field_name, *, compact=False, rss=False):
    if raw is None or raw == "":
        return {"raw": raw, "value": None, "day": None, "precision": "unknown", "field": field_name}
    value = raw
    try:
        if compact:
            if not re.fullmatch(r"[0-9]{8}", raw):
                raise ValueError
            value = f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
        elif rss:
            parsed = parsedate_to_datetime(raw)
            if parsed.tzinfo is None:
                raise ValueError
            value = parsed.isoformat()
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            _day(value)
            precision, day = "day", value
        else:
            parsed = datetime.fromisoformat(value)
            precision, day = ("instant" if parsed.tzinfo is not None else "unresolved"), value[:10]
        return {"raw": raw, "value": value, "day": day, "precision": precision, "field": field_name}
    except (ValueError, TypeError, IngestionFailure):
        raise IngestionFailure("official_publication_invalid") from None


def _context(candidate_id, publication, title, ref, facts=None):
    return {"candidateId": candidate_id, "publication": publication, "title": title,
            "discoverySha256": ref.raw_sha256, "facts": facts or {}}


def _candidate(task, ref, identifier, url, title, publication, pointer, facts, body, limitations=()):
    return OfficialCandidate(task.source_id, identifier, url, title, publication, ref.observed_at,
                             ref.raw_sha256, pointer, facts, body, limitations)


def _in_window(task, publication):
    return publication["day"] is None or task.from_day <= publication["day"] <= task.through_day


def _dart_status(data):
    code = data.get("status")
    if code == "000":
        return "ok"
    if code in {"013", "014"}:
        return "empty"
    if code in {"010", "011", "012", "020", "901"}:
        raise IngestionFailure("opendart_auth_or_quota_" + code)
    raise IngestionFailure("opendart_api_failure")


def _tree_prepared(members, container_hash):
    parts, sources, limitations = [], [], []
    for member in members:
        if member.representation == "unsupported":
            limitations.append("unsupported_member:" + member.name)
            continue
        if member.representation == "html":
            # Valid HTML doctype is allowed; declarations/entities are not.
            probe = re.sub(rb"<!doctype\s+html\s*>", b"", member.raw, flags=re.I)
            if b"<!DOCTYPE" in probe.replace(b"\x00", b"").upper() or b"<!ENTITY" in probe.replace(b"\x00", b"").upper():
                raise IngestionFailure("official_xml_entities_forbidden")
            try:
                member.raw.decode("utf-8-sig")
                encoding = "utf-8"
            except UnicodeDecodeError:
                encoding = None
            root = html.document_fromstring(member.raw, parser=html.HTMLParser(encoding=encoding, no_network=True, huge_tree=False))
        else:
            root = _xml(member.raw)
        tree = root.getroottree()
        def walk(node):
            tag = node.tag.rsplit("}", 1)[-1].lower() if isinstance(node.tag, str) else ""
            if tag in {"head", "script", "style", "iframe", "noscript", "hidden"} or not tag:
                parts.append(None)
                return
            if node.text:
                index = len(sources)
                sources.append({"text": node.text, "memberRef": member.name, "memberSha256": member.sha256,
                                "containerSha256": container_hash, "xpath": tree.getpath(node), "slot": "text"})
                parts.append((index, 0, len(node.text)))
            for child in node:
                walk(child)
                if child.tail:
                    index = len(sources)
                    sources.append({"text": child.tail, "memberRef": member.name, "memberSha256": member.sha256,
                                    "containerSha256": container_hash, "xpath": tree.getpath(child), "slot": "tail"})
                    parts.append((index, 0, len(child.tail)))
            if tag in {"p", "div", "tr", "table", "section", "title", "preamble", "body", "document"}:
                parts.append(None)
        parts.append(None)
        walk(root)
    return _mapped(parts, sources, limitations)


def execute(task: OfficialTask, fetcher: OfficialFetcher, *, runtime_key: str | None = None) -> OfficialResult:
    fetched = fetcher.fetch_task(task, runtime_key=runtime_key)
    try:
        return parse_response(task, fetched, synthetic_origin=fetcher.synthetic_origin)
    except (KeyError, ValueError, TypeError, AttributeError, IndexError, etree.LxmlError):
        raise IngestionFailure("official_response_invalid") from None


def parse_response(task: OfficialTask, fetched: Fetched, *, synthetic_origin: str | None = None) -> OfficialResult:
    validate_task(task, synthetic_origin=synthetic_origin)
    if (fetched.requested_url != task.url or fetched.final_url != task.url or fetched.redirects or
            fetched.status != 200 or len(fetched.body) > MAX_RAW):
        raise IngestionFailure("official_response_binding_mismatch")
    _bound_link(task.source_id, fetched.final_url, synthetic_origin)
    ref = ResponseRef(task.source_id, task.key, task.url, fetched.final_url, fetched.fetched_at,
                      fetched.media_type, byte_hash(fetched.body), len(fetched.body), tuple(fetched.robots))
    raw, origin = fetched.body, _origin(task.source_id, synthetic_origin)
    base = OfficialResult(ref, raw)
    if task.kind in {"dart-corps", "dart-document"}:
        if not raw.startswith(b"PK"):
            root = _xml(raw)
            status = _dart_status({"status": root.findtext("status")})
            return replace(base, status=status)
        members = _zip(raw)
        if task.kind == "dart-document":
            return replace(base, members=members, prepared=_tree_prepared(members, ref.raw_sha256),
                           limitations=("filing originals; unsupported attachments are not parsed",))
        wanted, found, mappings = set(task.context["tickers"]), {}, []
        for member in members:
            if member.representation != "xml":
                raise IngestionFailure("opendart_corp_member_invalid")
            root = _xml(member.raw)
            for index, row in enumerate(root.findall("list")):
                stock, corp = (row.findtext("stock_code") or "").strip(), (row.findtext("corp_code") or "").strip()
                if stock not in wanted:
                    continue
                if not re.fullmatch(r"[0-9]{8}", corp) or stock in found:
                    raise IngestionFailure("opendart_corp_mapping_ambiguous")
                found[stock] = corp
                mappings.append(_candidate(task, ref, corp, task.url, row.findtext("corp_name"),
                    _publication(None, "none"), f"{member.name}#/result/list[{index + 1}]",
                    {"corpCode": corp, "stockCode": stock, "corpName": row.findtext("corp_name"),
                     "modifyDate": row.findtext("modify_date"), "memberRef": member.name, "memberSha256": member.sha256}, None))
        return replace(base, members=members, candidates=tuple(mappings),
                       next_tasks=tuple(_dart_list(origin, task.from_day, task.through_day, corp=found[stock]) for stock in sorted(found)),
                       limitations=tuple("ticker_not_in_actual_records:" + stock for stock in sorted(wanted - found.keys())))
    if task.kind == "dart-list":
        data = _json(raw)
        status = _dart_status(data)
        if status == "empty":
            return replace(base, status=status)
        page, total = data.get("page_no"), data.get("total_page")
        if type(page) is not int or type(total) is not int or page != task.context["page"] or total < page:
            raise IngestionFailure("opendart_pagination_invalid")
        rows = data.get("list")
        if not isinstance(rows, list) or len(rows) > 100 or not rows:
            raise IngestionFailure("opendart_rows_invalid")
        candidates = []
        for index, row in enumerate(rows):
            receipt, corp = row.get("rcept_no", ""), row.get("corp_code", "")
            if (not re.fullmatch(r"[0-9]{14}", receipt) or not re.fullmatch(r"[0-9]{8}", corp) or
                    task.context["corpCode"] is not None and task.context["corpCode"] != corp):
                raise IngestionFailure("opendart_receipt_binding_mismatch")
            publication = _publication(row.get("rcept_dt"), "rcept_dt", compact=True)
            if not _in_window(task, publication) or publication["day"] is None:
                raise IngestionFailure("opendart_receipt_date_mismatch")
            facts = dict(row)
            title = row.get("report_nm")
            facts["correction"] = isinstance(title, str) and "정정" in title
            body = _task(task.source_id, "dart-document", origin, "/api/document.xml", task.from_day, task.through_day,
                         _context(receipt, publication, title, ref, facts), {"rcept_no": receipt})
            candidates.append(_candidate(task, ref, receipt, "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + receipt,
                                         title, publication, f"/list/{index}", facts, body))
        return replace(base, candidates=tuple(candidates), next_tasks=(_dart_list(origin, task.from_day, task.through_day,
                       corp=task.context["corpCode"], page=page + 1),) if page < total else ())
    if task.kind == "fsc-rss":
        root = _xml(raw)
        candidates = []
        for index, item in enumerate(root.findall("./channel/item")):
            link = _bound_link(task.source_id, (item.findtext("link") or "").strip(), synthetic_origin)
            if not re.fullmatch(r"/no010101/[0-9]+", urlsplit(link).path):
                raise IngestionFailure("official_source_binding_mismatch")
            publication = _publication(item.findtext("pubDate"), "pubDate", rss=True)
            if not _in_window(task, publication):
                continue
            identifier = urlsplit(link).path.rsplit("/", 1)[1]
            title = item.findtext("title")
            body = OfficialTask(task.source_id, "fsc-body", link, task.from_day, task.through_day,
                                _context(identifier, publication, title, ref))
            candidates.append(_candidate(task, ref, identifier, link, title, publication,
                                         f"/rss/channel/item[{index + 1}]", {"guid": item.findtext("guid")}, body))
        return replace(base, candidates=tuple(candidates), limitations=("rolling_feed_not_historical_exhaustion", "attachments_unassessed"))
    if task.kind in {"bis-list", "bis-detail"}:
        data = _json(raw)
        rows = data.get("results") if task.kind == "bis-list" else [data]
        if not isinstance(rows, list) or len(rows) > 1000:
            raise IngestionFailure("bis_rows_invalid")
        candidates, next_tasks = [], []
        for index, row in enumerate(rows):
            number = row.get("document_number", "")
            if not re.fullmatch(r"[0-9]{4}-[0-9]+", number):
                raise IngestionFailure("bis_document_identity_invalid")
            if not any(agency.get("slug") == "industry-and-security-bureau" for agency in row.get("agencies", []) if isinstance(agency, dict)):
                raise IngestionFailure("bis_agency_binding_mismatch")
            if task.kind == "bis-detail" and number != task.context["candidateId"]:
                raise IngestionFailure("bis_document_binding_mismatch")
            publication = _publication(row.get("publication_date"), "publication_date")
            if not _in_window(task, publication) or publication["day"] is None:
                raise IngestionFailure("bis_document_date_mismatch")
            link = _bound_link(task.source_id, row.get("html_url"), synthetic_origin)
            title, facts = row.get("title"), dict(row)
            context = _context(number, publication, title, ref, facts)
            if task.kind == "bis-list":
                body = _task(task.source_id, "bis-detail", origin, "/api/v1/documents/" + number + ".json",
                             task.from_day, task.through_day, context)
            else:
                body_url = row.get("raw_text_url") or row.get("body_html_url")
                body_url = _bound_link(task.source_id, body_url, synthetic_origin)
                if not re.fullmatch(r"/documents/full_text/(?:text|html)/[0-9]{4}/[0-9]{2}/[0-9]{2}/" +
                                    re.escape(number) + r"\.(?:txt|html)", urlsplit(body_url).path):
                    raise IngestionFailure("bis_body_binding_mismatch")
                body = OfficialTask(task.source_id, "bis-body", body_url, task.from_day, task.through_day, context)
                next_tasks.append(body)
            candidates.append(_candidate(task, ref, number, link, title, publication, f"/results/{index}" if task.kind == "bis-list" else "/",
                                         facts, body, ("FederalRegister.gov is an unofficial presentation",)))
        if task.kind == "bis-list":
            total = data.get("total_pages")
            if type(total) is not int or total < 0 or total and total < task.context["page"]:
                raise IngestionFailure("bis_pagination_invalid")
            if task.context["page"] < total:
                if not rows:
                    raise IngestionFailure("bis_pagination_invalid")
                next_tasks.append(_bis_list(origin, task.from_day, task.through_day, task.context["page"] + 1))
        return replace(base, candidates=tuple(candidates), next_tasks=tuple(next_tasks))
    if task.kind in {"sec-submissions", "sec-past"}:
        data = _json(raw)
        cik = task.context["cik"]
        next_tasks = []
        if task.kind == "sec-submissions":
            if str(data.get("cik")).lstrip("0") != cik:
                raise IngestionFailure("sec_cik_binding_mismatch")
            columns = data.get("filings", {}).get("recent")
            files = data.get("filings", {}).get("files", [])
            if not isinstance(files, list) or len(files) > MAX_ROWS:
                raise IngestionFailure("sec_past_files_invalid")
            for item in files:
                name = item.get("name", "")
                if not re.fullmatch(rf"CIK{int(cik):010d}-submissions-[0-9]+\.json", name):
                    raise IngestionFailure("sec_past_file_binding_mismatch")
                first, last = _day(item.get("filingFrom")), _day(item.get("filingTo"))
                if first > last:
                    raise IngestionFailure("sec_past_files_invalid")
                if first.isoformat() <= task.through_day and last.isoformat() >= task.from_day:
                    next_tasks.append(_task(task.source_id, "sec-past", origin, "/submissions/" + name,
                                           task.from_day, task.through_day, {"cik": cik}))
        else:
            columns = data
        fields = ("accessionNumber", "filingDate", "form", "primaryDocument")
        if not isinstance(columns, dict) or any(not isinstance(columns.get(name), list) for name in fields):
            raise IngestionFailure("sec_columns_invalid")
        length = len(columns["accessionNumber"])
        if length > MAX_ROWS or any(len(values) != length for values in columns.values() if isinstance(values, list)):
            raise IngestionFailure("sec_columns_invalid")
        candidates = []
        for index in range(length):
            accession = columns["accessionNumber"][index]
            if not isinstance(accession, str) or not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession):
                raise IngestionFailure("sec_accession_invalid")
            publication = _publication(columns["filingDate"][index], "filingDate")
            if publication["precision"] != "day":
                raise IngestionFailure("sec_filing_date_invalid")
            if not _in_window(task, publication):
                continue
            document = columns["primaryDocument"][index]
            if not isinstance(document, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", document) or ".." in document:
                raise IngestionFailure("sec_primary_document_invalid")
            article_origin = synthetic_origin or "https://www.sec.gov"
            link = article_origin + f"/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{document}"
            facts = {name: values[index] for name, values in columns.items() if isinstance(values, list)}
            facts.update({"cik": cik, "publisher": None, "publisherFact": "filing registrant is not asserted to be article publisher"})
            title = columns["form"][index]
            limitations = ("primary_filing_only; inline-XBRL semantics and attachments unsupported",)
            body = OfficialTask(task.source_id, "sec-body", link, task.from_day, task.through_day,
                                _context(accession, publication, title, ref, facts)) if document.lower().endswith((".htm", ".html", ".txt")) else None
            candidates.append(_candidate(task, ref, accession, link, title, publication,
                                         ("/filings/recent/" if task.kind == "sec-submissions" else "/") + str(index), facts, body,
                                         limitations + (() if body else ("unsupported_primary_document_type",))))
        return replace(base, candidates=tuple(candidates), next_tasks=tuple(next_tasks))
    if task.kind == "fsc-body":
        if fetched.media_type != "text/html":
            raise IngestionFailure("official_body_media_mismatch")
        prepared = prepare(raw, "text/html", FSC_SCOPE)
        for source in prepared["sources"]:
            source["containerSha256"] = ref.raw_sha256
        return replace(base, prepared=prepared, limitations=("attachments_unassessed",))
    if task.kind in {"bis-body", "sec-body"}:
        if fetched.media_type == "text/plain":
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeError:
                raise IngestionFailure("official_text_encoding_invalid") from None
            prepared = _mapped([(0, 0, len(text))], [{"text": text, "containerSha256": ref.raw_sha256,
                                                      "coordinate": "decoded-utf8-codepoints"}], [])
        elif fetched.media_type == "text/html":
            member = MemberRef("$response", ref.raw_sha256, len(raw), "html", raw)
            prepared = _tree_prepared((member,), ref.raw_sha256)
        else:
            raise IngestionFailure("official_body_media_mismatch")
        return replace(base, prepared=prepared, limitations=("primary text only; attachments and inline-XBRL semantics unassessed",))
    raise IngestionFailure("official_task_invalid")


def verify_extraction(envelope: dict, raw: bytes, task: OfficialTask, *, synthetic_origin: str | None = None) -> dict:
    """Reprepare retained original bytes without network; reject changed members or coordinates."""
    try:
        response = envelope["response"]
        if envelope["schemaVersion"] != "zoop-official-extraction-1" or response["task_key"] != task.key:
            raise ValueError
        fetched = Fetched(response["request_url"], response["final_url"], 200, response["media_type"],
                          response["media_type"], raw, {}, [], list(response["robots"]), 0, response["observed_at"])
        expected = parse_response(task, fetched, synthetic_origin=synthetic_origin).extraction()
        if expected != envelope or expected["prepared"] is None:
            raise ValueError
        return expected["prepared"]
    except (KeyError, ValueError, TypeError, AttributeError):
        raise IngestionFailure("official_extraction_invalid") from None


def load_config(path):
    from .official_source_intake import load_config as load
    return load(path)


def run(config, command="run", *, runtime_key=None):
    from .official_source_intake import run as execute_run
    return execute_run(config, command, runtime_key=runtime_key)


def status(config):
    from .official_source_intake import status as inspect_status
    return inspect_status(config)


def retained_items(config):
    from .official_source_intake import retained_items as items
    return items(config)


def verify_record(record, raw, *, extraction_raw, body_raw):
    from .official_source_intake import verify_record as verify
    return verify(record, raw, extraction_raw=extraction_raw, body_raw=body_raw)


def source_hosts(source_id: str) -> tuple[str, ...]:
    origin = _origin(source_id, None)
    return (urlsplit(origin).hostname, "www.sec.gov") if source_id == "sec-edgar" else (urlsplit(origin).hostname,)
