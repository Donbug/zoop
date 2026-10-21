"""One-off HTTP acquisition of explicitly listed document URLs into hash-bound ingestion inputs.

This is the only pipeline process that opens a network connection for source documents, and it is deliberately small:
no discovery, crawling, scheduling, search, authentication or automatic retry. Per URL it checks the source-owned grant,
the exact host list, robots.txt, then fetches with a DNS result it validated itself and connects to THAT address (Host header and
TLS SNI/certificate name stay the requested host), so a second, different DNS answer can never redirect the connection. The same
validation repeats for every robots fetch and every redirect hop. Proxy environment variables are ignored, TLS verification
is never disabled, no cookie or credential is ever sent, and errors are stable codes without URLs or headers.

Output is written under `<source.inputRoot>/collections/<collectionId>/` and consumed unchanged by `zoop-ai-ingest run`.
"""
from __future__ import annotations

import asyncio
import fcntl
import ipaddress
import json
import os
import re
import socket
import ssl
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import httpx
from pydantic import ValidationError

from .collection_contracts import SCHEMA, Policy, Request, Target, declared_published
from .ingestion_contracts import (MAX_INPUT, Authority, Collected, FileRef, IngestionFailure, Item, Manifest, Receipt, byte_hash,
    canonical, digest, now, reserved_state_roots)
from .ingestion_url import LOOPBACK_HOSTS, canonical_url

REDIRECTS = frozenset({301, 302, 303, 307, 308})
ROBOTS_BYTES = 512_000
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
Resolver = Callable[[str, int], list[str]]


# --------------------------------------------------------------------------------------------- robots.txt (RFC 9309)

def _octets(value: str) -> str:
    value = quote(value, safe="/%:?#[]@!$&'()*+,;=-._~")
    return re.sub(r"%([0-9a-fA-F]{2})", lambda m: chr(int(m[1], 16)) if chr(int(m[1], 16)) in _UNRESERVED else m[0].upper(), value)


def _matches(pattern: str, target: str) -> bool:
    anchored = pattern.endswith("$")
    parts = (pattern[:-1] if anchored else pattern).split("*")
    if not target.startswith(parts[0]):
        return False
    offset = len(parts[0])
    for index, part in enumerate(parts[1:], 1):
        if anchored and index == len(parts) - 1:
            return target.endswith(part) and len(target) - len(part) >= offset
        found = target.find(part, offset)
        if found < 0:
            return False
        offset = found + len(part)
    return not anchored or offset == len(target)


@dataclass(frozen=True)
class Rules:
    rules: tuple[tuple[bool, str], ...] = ()
    delay: float = 0.0

    def permits(self, url: str) -> bool:
        parts = urlsplit(url)
        target = _octets(parts.path + ("?" + parts.query if parts.query else ""))
        hits = [(len(p.replace("*", "").rstrip("$")), allow) for allow, p in self.rules if _matches(p, target)]
        return not hits or max(hits)[1]


def parse_robots(data: bytes, user_agent: str) -> Rules:
    """Longest-match allow/disallow for our product token. Anything uninterpretable is `robots_malformed`, which denies."""
    product = (re.match(r"[A-Za-z0-9_-]+", user_agent) or re.match("", "")).group(0).lower()
    try:
        groups: list[tuple[list[str], list[tuple[str, str]]]] = []
        agents: list[str] = []
        directives: list[tuple[str, str]] = []
        for raw in data.decode("utf-8-sig").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            name, separator, value = line.partition(":")
            name, value = name.strip().lower(), value.strip()
            if not separator or not re.fullmatch(r"[a-z-]+", name):
                raise ValueError("directive")
            if name == "user-agent":
                if directives:
                    groups.append((agents, directives))
                    agents, directives = [], []
                if not re.fullmatch(r"[A-Za-z0-9_.*-]+(?:/[A-Za-z0-9_.-]+)?", value):
                    raise ValueError("agent")
                agents.append(value.split("/")[0].lower())
            elif name in {"allow", "disallow", "crawl-delay"}:
                if not agents:
                    raise ValueError("orphan rule")
                if name != "crawl-delay" and value and not value.startswith(("/", "*")):
                    raise ValueError("path rule")
                if name == "crawl-delay" and not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
                    raise ValueError("delay")
                directives.append((name, value))
            elif name != "sitemap" and not agents:
                raise ValueError("unrecognized")
        if agents:
            groups.append((agents, directives))
        best, selected = -1, []
        for names, rules in groups:
            scores = [0 if n == "*" else len(n) for n in names if n == "*" or n == product]
            if scores and max(scores) >= best:
                if max(scores) > best:
                    selected, best = [], max(scores)
                selected.extend(rules)
        return Rules(tuple((n == "allow", _octets(v)) for n, v in selected if n in {"allow", "disallow"} and v),
                     max([float(v) for n, v in selected if n == "crawl-delay"], default=0.0))
    except (UnicodeError, ValueError, OverflowError) as exc:
        raise IngestionFailure("robots_malformed") from exc


# ------------------------------------------------------------------------------------------------ address policy

def public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Globally routable only. IPv4-mapped and NAT64-embedded IPv4 are judged by the IPv4 they carry."""
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return public_address(address.ipv4_mapped)
        if address in ipaddress.ip_network("64:ff9b::/96"):
            return public_address(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
    return address.is_global


def system_resolver(host: str, port: int) -> list[str]:
    return [row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


def _resolve(resolver: Resolver, host: str, port: int, seconds: float) -> list[str]:
    if resolver is system_resolver:
        # libc getaddrinfo is not cancellable. Bound the production lookup in a child that
        # subprocess.run kills AND reaps on timeout; a timed-out DNS query leaves no live thread.
        script = ("import json,socket,sys; "
                  "print(json.dumps([r[4][0] for r in socket.getaddrinfo(sys.argv[1],int(sys.argv[2]),type=socket.SOCK_STREAM)]))")
        try:
            child = subprocess.run([sys.executable, "-I", "-B", "-c", script, host, str(port)], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=max(seconds, 0.001), check=False,
                                   env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"})
            if child.returncode:
                raise IngestionFailure("dns_failed")
            addresses = json.loads(child.stdout)
            if not isinstance(addresses, list) or any(not isinstance(value, str) for value in addresses):
                raise IngestionFailure("dns_failed")
        except subprocess.TimeoutExpired as exc:
            raise IngestionFailure("timeout") from exc
        except (OSError, ValueError) as exc:
            raise IngestionFailure("dns_failed") from exc
        return list(dict.fromkeys(addresses))

    # Injected synthetic test resolvers can be closures; preserve that seam. The real system
    # resolver above never runs in a thread and is reaped on timeout.
    box: dict = {}

    def work():
        try:
            box["addresses"] = resolver(host, port)
        except Exception as exc:  # noqa: BLE001 - any resolver failure is the same closed code
            box["error"] = exc

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    thread.join(max(seconds, 0.001))
    if thread.is_alive():
        raise IngestionFailure("timeout")
    if "error" in box:
        raise IngestionFailure("dns_failed")
    return list(dict.fromkeys(box["addresses"]))


# ------------------------------------------------------------------------------------------------------ fetching

@dataclass
class Fetched:
    requested_url: str
    final_url: str
    status: int
    content_type: str
    media_type: str
    body: bytes
    headers: dict
    redirects: list
    robots: list
    requests: int
    fetched_at: str = field(default_factory=now)


def _require_sync_context() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise IngestionFailure("collector_async_context_unsupported")


class _AuthorityChanged(IngestionFailure):
    """Authority failures terminate the whole run, rather than becoming failed targets."""


class Fetcher:
    def __init__(self, policy: Policy, hosts: list[str], resolver: Resolver = system_resolver,
                 authority_guard: Callable[[], None] | None = None):
        self.policy, self.hosts, self.resolver = policy, frozenset(hosts), resolver
        self.authority_guard = authority_guard
        self.requests = self.downloaded = 0
        self.run_deadline = time.monotonic() + policy.max_total_seconds
        self._last: dict[str, float] = {}
        self._delay: dict[str, float] = {}
        self._robots: dict[str, Rules | IngestionFailure] = {}
        self._observed: dict[str, dict] = {}
        self._blocked: set[str] = set()

    # Every URL (target, redirect hop, robots) passes through here before any DNS lookup or connection.
    def _guard(self, value: str) -> tuple[str, str]:
        try:
            url, host = canonical_url(value)
        except IngestionFailure as exc:
            raise IngestionFailure("url_invalid") from exc
        parts = httpx.URL(url)
        loopback = host in LOOPBACK_HOSTS
        if host not in self.hosts:
            raise IngestionFailure("host_not_allowed")
        if loopback and not self.policy.synthetic_loopback:
            raise IngestionFailure("private_address")
        if parts.scheme == "http" and not loopback:
            raise IngestionFailure("scheme_not_allowed")
        if host.endswith(".localhost") and not loopback:
            raise IngestionFailure("private_address")
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None and not loopback and not public_address(literal):
            raise IngestionFailure("private_address")
        if host in self._blocked:
            raise IngestionFailure("host_blocked")
        return url, host

    def _remaining(self, deadline: float) -> float:
        remaining = min(deadline, self.run_deadline) - time.monotonic()
        if remaining <= 0:
            raise IngestionFailure("timeout")
        return remaining

    def _pin(self, url: httpx.URL, host: str, deadline: float) -> str:
        """The one address this request may connect to, validated now (never trusting an earlier lookup)."""
        port = url.port or (443 if url.scheme == "https" else 80)
        addresses = _resolve(self.resolver, host, port, self._remaining(deadline))
        if not addresses:
            raise IngestionFailure("dns_failed")
        loopback_only = self.policy.synthetic_loopback and host in LOOPBACK_HOSTS
        for text in addresses:
            try:
                address = ipaddress.ip_address(text)
            except ValueError as exc:
                raise IngestionFailure("private_address") from exc
            if not (address.is_loopback if loopback_only else public_address(address)):
                raise IngestionFailure("private_address")
        return min(addresses, key=lambda a: ":" in a) if loopback_only else addresses[0]

    def _get(self, url: str, host: str, deadline: float, limit: int) -> tuple[int, httpx.Headers, bytes]:
        _require_sync_context()
        if self.requests >= self.policy.max_requests:
            raise IngestionFailure("request_budget")
        if self.downloaded >= self.policy.max_total_bytes:
            raise IngestionFailure("byte_budget")
        wait = self._last.get(host, 0.0) + max(self.policy.min_interval_seconds, self._delay.get(host, 0.0)) - time.monotonic()
        if wait > 0:
            if wait >= self._remaining(deadline):
                raise IngestionFailure("rate_limit")
            time.sleep(wait)
        target = httpx.URL(url)
        pinned = target.copy_with(host=self._pin(target, host, deadline))
        headers = {"User-Agent": self.policy.user_agent, "Accept": "text/html, application/pdf;q=0.9", "Accept-Encoding": "identity",
                   "Host": target.netloc.decode("ascii")}
        extensions = {"sni_hostname": host, "timeout": dict.fromkeys(("connect", "read", "write", "pool"), self._remaining(deadline))}

        async def receive() -> tuple[int, httpx.Headers, bytes]:
            # A fresh client per request: no pooled connection can carry one host's certificate check over to another.
            # Cancellation closes the async stream/socket; unlike a worker thread, no timed-out request continues running.
            async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
                if self.authority_guard is not None:
                    self.authority_guard()  # Last step before opening this GET, including robots and redirect hops.
                self.requests += 1
                self._last[host] = time.monotonic()
                async with client.stream("GET", pinned, headers=headers, extensions=extensions) as response:
                    self._check(response, host, limit)
                    body = bytearray()
                    async for chunk in response.aiter_raw():
                        self.downloaded += len(chunk)
                        self._remaining(deadline)
                        if self.downloaded > self.policy.max_total_bytes:
                            raise IngestionFailure("byte_budget")
                        if len(body) + len(chunk) > limit:
                            raise IngestionFailure("response_too_large")
                        body.extend(chunk)
                    self._remaining(deadline)
                    return response.status_code, response.headers, bytes(body)

        try:
            # I/O timeouts only bound inactivity. wait_for also bounds the whole DNS-pinned connect,
            # TLS handshake, header assembly and body against the original target/run deadline.
            remaining = self._remaining(deadline)
            result = asyncio.run(asyncio.wait_for(receive(), timeout=remaining))
            self._remaining(deadline)
            return result
        except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
            raise IngestionFailure("timeout") from exc
        except httpx.HTTPError as exc:
            chain, seen = exc, 0
            while chain is not None and seen < 8:
                if isinstance(chain, ssl.SSLError):
                    raise IngestionFailure("tls_error") from exc
                chain, seen = chain.__cause__ or chain.__context__, seen + 1
            raise IngestionFailure("network_error") from exc

    def _check(self, response: httpx.Response, host: str, limit: int) -> None:
        if response.status_code in {401, 403, 429}:
            self._blocked.add(host)
            raise IngestionFailure(f"http_{response.status_code}")
        if response.headers.get("content-encoding", "identity").strip().lower() not in {"", "identity"}:
            raise IngestionFailure("content_encoding")
        size = response.headers.get("content-length", "")
        if size.isdecimal():
            if len(size) > 20 or int(size) > limit:
                raise IngestionFailure("response_too_large")
            if int(size) > self.policy.max_total_bytes - self.downloaded:
                raise IngestionFailure("byte_budget")

    def _rules(self, url: str, deadline: float) -> Rules:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            try:
                self._robots[origin] = self._load_robots(origin, deadline)
            except IngestionFailure as exc:
                if not exc.code.startswith("robots_"):
                    raise  # a timeout or budget stop says nothing durable about the site's policy
                self._robots[origin] = exc
        cached = self._robots[origin]
        if isinstance(cached, IngestionFailure):
            raise IngestionFailure(cached.code)
        return cached

    def _load_robots(self, origin: str, deadline: float) -> Rules:
        robots_url = origin + "/robots.txt"
        for hop in range(self.policy.max_redirects + 1):
            url, host = self._guard(robots_url)
            status, headers, data = self._get(url, host, deadline, min(self.policy.max_response_bytes, ROBOTS_BYTES))
            self._observed[origin] = {"url": url, "status": status}
            if status in REDIRECTS:
                if hop == self.policy.max_redirects or not headers.get("location"):
                    raise IngestionFailure("robots_unavailable")
                try:
                    robots_url = canonical_url(urljoin(url, headers["location"]))[0]
                except IngestionFailure as exc:
                    raise IngestionFailure("robots_unavailable") from exc
                if urlsplit(robots_url)[:2] != urlsplit(origin)[:2]:
                    raise IngestionFailure("robots_unavailable")
                continue
            if status == 404:
                return Rules()
            if status != 200:
                raise IngestionFailure("robots_unavailable")
            rules = parse_robots(data, self.policy.user_agent)
            self._delay[host] = max(self._delay.get(host, 0.0), rules.delay)
            return rules
        raise IngestionFailure("robots_unavailable")

    def fetch(self, value: str) -> Fetched:
        started = self.requests
        deadline = time.monotonic() + self.policy.timeout_seconds
        requested, _ = self._guard(value)
        url, redirects, touched = requested, [], []
        for hop in range(self.policy.max_redirects + 1):
            url, host = self._guard(url)
            rules = self._rules(url, deadline)
            origin_parts = urlsplit(url)
            touched.append(f"{origin_parts.scheme}://{origin_parts.netloc}")
            if not rules.permits(url):
                raise IngestionFailure("robots_denied")
            status, headers, body = self._get(url, host, deadline, self.policy.max_response_bytes)
            if status in REDIRECTS:
                if hop == self.policy.max_redirects or not headers.get("location"):
                    raise IngestionFailure("redirect_limit")
                try:
                    following = canonical_url(urljoin(url, headers["location"]))[0]
                except IngestionFailure as exc:
                    raise IngestionFailure("redirect_invalid") from exc
                if urlsplit(url).scheme == "https" and urlsplit(following).scheme != "https":
                    raise IngestionFailure("redirect_blocked")
                redirects.append(following)
                url = following
                continue
            if not 200 <= status < 300:
                raise IngestionFailure(f"http_{status}")
            content_type = headers.get("content-type", "")
            media_type = content_type.split(";", 1)[0].strip().lower()
            if media_type not in self.policy.allowed_media_types:
                raise IngestionFailure("media_type_not_allowed")
            seen = {o: self._observed[o] for o in dict.fromkeys(touched) if o in self._observed}
            return Fetched(requested, url, status, content_type[:200], media_type, body,
                           {k: (headers.get(k) or None) for k in ("content-length", "etag", "last-modified", "date")},
                           redirects, list(seen.values()), self.requests - started)
        raise IngestionFailure("redirect_limit")


# ------------------------------------------------------------------------------------------------- output namespace

class Output:
    """`<inputRoot>/collections/` opened without following any symlink, locked, and written through directory descriptors only.

    A run writes into a private `.tmp-<id>-...` directory it created itself and publishes it with one rename; a failed run removes
    exactly the names it created. Stale temporaries of a killed process are neither adopted nor deleted."""

    def __init__(self, root: str):
        path = Path(os.path.abspath(root))
        if any(path == r or path.is_relative_to(r) or r.is_relative_to(path) for r in reserved_state_roots()):
            raise IngestionFailure("state_namespace_conflict")
        self.fds: list[int] = []
        self.tmp: tuple[int, str] | None = None
        self.subdirs: dict[str, int] = {}
        self.created: list[tuple[str, int, str]] = []
        try:
            fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
            self.fds.append(fd)
            for part in path.parts[1:]:
                fd = self._open(fd, part)
            self.collections = self._open(fd, "collections", create=True)
            self.lock = os.open(".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=self.collections)
            self.fds.append(self.lock)
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise IngestionFailure("collector_busy") from exc
            with os.scandir(self.collections) as entries:
                if any(e.name != ".lock" and not e.is_dir(follow_symlinks=False) for e in entries):
                    raise IngestionFailure("collection_namespace_conflict")
        except OSError as exc:
            self.close()
            raise IngestionFailure("collection_namespace_invalid") from exc
        except BaseException:
            self.close()
            raise

    def _open(self, parent: int, name: str, create: bool = False) -> int:
        if create:
            try:
                os.mkdir(name, 0o700, dir_fd=parent)
            except FileExistsError:
                pass
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        self.fds.append(fd)
        return fd

    def close(self) -> None:
        for fd in reversed(self.fds):
            try:
                os.close(fd)
            except OSError:
                pass
        self.fds = []

    def stored(self, collection_id: str) -> dict | None:
        """The finished collection.json of an earlier run of this id, or None. A directory without one is foreign: refuse."""
        try:
            os.stat(collection_id, dir_fd=self.collections, follow_symlinks=False)
        except FileNotFoundError:
            return None
        try:
            directory = os.open(collection_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.collections)
            try:
                fd = os.open("collection.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                try:
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_INPUT:
                        raise IngestionFailure("collection_namespace_conflict")
                    with os.fdopen(fd, "rb", closefd=False) as stream:
                        raw = stream.read(MAX_INPUT + 1)
                    if len(raw) > MAX_INPUT:
                        raise IngestionFailure("collection_namespace_conflict")
                    return json.loads(raw)
                finally:
                    os.close(fd)
            finally:
                os.close(directory)
        except (OSError, ValueError) as exc:
            raise IngestionFailure("collection_namespace_conflict") from exc

    def begin(self, collection_id: str) -> None:
        name = f".tmp-{collection_id}-{os.getpid()}-{int.from_bytes(os.urandom(4), 'big'):08x}"
        os.mkdir(name, 0o700, dir_fd=self.collections)
        self.created.append(("dir", self.collections, name))
        self.tmp = (self._open(self.collections, name), name)

    def write(self, relative: str, data: bytes) -> None:
        """Create `relative` (at most one subdirectory deep) exclusively. An identical content-addressed name is already there."""
        assert self.tmp is not None
        parent, _, leaf = relative.rpartition("/")
        fd = self.tmp[0]
        if parent:
            if parent not in self.subdirs:
                os.mkdir(parent, 0o700, dir_fd=fd)
                self.created.append(("dir", fd, parent))
                self.subdirs[parent] = self._open(fd, parent)
            fd = self.subdirs[parent]
        try:
            out = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        except FileExistsError:
            return
        self.created.append(("file", fd, leaf))
        with os.fdopen(out, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())

    def commit(self, collection_id: str, guard: Callable[[], None]) -> None:
        assert self.tmp is not None
        for fd in (*self.subdirs.values(), self.tmp[0]):
            os.fsync(fd)
        guard()  # Recheck after slow fsync, immediately before publishing the private directory.
        temporary = self.tmp[1]
        os.rename(temporary, collection_id, src_dir_fd=self.collections, dst_dir_fd=self.collections)
        try:
            os.fsync(self.collections)
            guard()  # A revocation during publication must not become a stale return.
        except BaseException:
            # Retract only the directory whose still-open fd proves we created it. Abort then
            # removes its files using those owned descriptors; never remove a foreign replacement.
            try:
                visible = os.stat(collection_id, dir_fd=self.collections, follow_symlinks=False)
                owned = os.fstat(self.tmp[0])
                if (visible.st_dev, visible.st_ino) == (owned.st_dev, owned.st_ino):
                    os.rename(collection_id, temporary, src_dir_fd=self.collections, dst_dir_fd=self.collections)
                    os.fsync(self.collections)
            except OSError:
                pass
            raise
        self.tmp, self.created = None, []

    def abort(self) -> None:
        """Remove exactly what this process created, newest first."""
        for kind, fd, name in reversed(self.created):
            try:
                (os.unlink if kind == "file" else os.rmdir)(name, dir_fd=fd)
            except OSError:
                pass
        self.tmp, self.created = None, []



# ---------------------------------------------------------------------------------------------------- collection

def _target_item(target: Target, fetched: Fetched, collected: Collected) -> Item:
    return Item.model_validate({"candidateId": target.candidate_id, "supplierDocumentId": target.supplier_document_id, "url": fetched.requested_url,
                                "bodyRef": collected.body_sha256, "mediaType": fetched.media_type, "title": target.title,
                                "publishedAt": collected.published.raw if collected.published.precision == "instant" else None,
                                "modifiedAt": target.modified_at, "sourceRevision": target.source_revision, "publisher": target.publisher,
                                "collection": collected.wire()})


def collect(registry: Path, policy: Policy, request: Request, resolver: Resolver = system_resolver) -> dict:
    """Run (or replay) one immutable collection. Returns the stored result plus where the ingestion manifest is."""
    _require_sync_context()
    authority = Authority(registry)
    source, scope = authority.check(request.source_id, request.scope_id)
    if source.adapter != "collected-http":
        raise IngestionFailure("source_adapter_mismatch")
    config = source.configuration(scope)
    grant = {"grantId": source.grant.grant_id, "revision": source.grant.revision}
    seen = set()
    for target in request.targets:
        try:
            url, host = canonical_url(target.url)
        except IngestionFailure as exc:
            raise IngestionFailure("target_invalid") from exc
        if host not in source.allowed_hosts or url in seen:
            raise IngestionFailure("target_invalid")
        seen.add(url)
    request_digest = digest({"request": request.wire(), "configuration": config, "grant": grant, "policy": policy.wire()})
    output = Output(source.input_root)
    try:
        previous = output.stored(request.collection_id)
        if previous is not None:
            if previous.get("requestDigest") != request_digest:
                raise IngestionFailure("collection_input_conflict")
            try:
                manifest = FileRef.model_validate(previous["manifest"])
            except (ValidationError, KeyError, TypeError) as exc:
                raise IngestionFailure("collection_namespace_conflict") from exc
            authority.check(request.source_id, request.scope_id, config=config)
            return {**previous, "replayed": True, "manifestPath": str(Path(source.input_root) / manifest.file)}
        return _run(authority, source, scope, config, grant, policy, request, request_digest, output, resolver)
    finally:
        output.close()



def _run(authority, source, scope, config, grant, policy, request, request_digest, output: Output, resolver) -> dict:
    started = now()

    def current_grant() -> None:
        try:
            authority.check(request.source_id, request.scope_id, config=config)
        except IngestionFailure as exc:
            raise _AuthorityChanged(exc.code) from exc

    fetcher = Fetcher(policy, source.allowed_hosts, resolver, authority_guard=current_grant)
    base = f"collections/{request.collection_id}"
    outcomes, items, documents = [], [], {}
    output.begin(request.collection_id)
    try:
        for target in request.targets:
            outcome = {"candidateId": target.candidate_id, "url": canonical_url(target.url)[0], "outcome": "failed", "code": None,
                       "bodySha256": None, "receiptSha256": None}
            # Re-read the operator registry before each target and each actual GET (including robots/redirects).
            current_grant()
            try:
                fetched = fetcher.fetch(target.url)
                current_grant()  # Never materialize fetched bytes under a grant revoked during the response.
                body_hash = byte_hash(fetched.body)
                # Loopback is reachable only through the explicit synthetic switch; say so instead of calling it an external document.
                network = "synthetic_loopback" if LOOPBACK_HOSTS & {canonical_url(fetched.requested_url)[1], canonical_url(fetched.final_url)[1]} else "external"
                receipt = Receipt.model_validate({
                    "schemaVersion": "zoop-collection-receipt-1", "collectionId": request.collection_id, "sourceId": source.source_id,
                    "scopeId": scope.scope_id, "candidateId": target.candidate_id, "grantId": grant["grantId"], "grantRevision": grant["revision"],
                    "requestedUrl": fetched.requested_url, "finalUrl": fetched.final_url, "redirects": fetched.redirects, "httpStatus": fetched.status,
                    "contentType": fetched.content_type, "mediaType": fetched.media_type,
                    "contentLength": fetched.headers["content-length"], "etag": fetched.headers["etag"],
                    "lastModified": fetched.headers["last-modified"], "serverDate": fetched.headers["date"],
                    "bodySha256": body_hash, "bodyBytes": len(fetched.body), "fetchedAt": fetched.fetched_at, "userAgent": policy.user_agent,
                    "network": network, "robots": fetched.robots, "requestCount": max(fetched.requests, 1)})
                receipt_bytes = canonical(receipt.wire()).encode("utf-8")
                receipt_hash = byte_hash(receipt_bytes)
                collected = Collected.model_validate({
                    "provenance": "collected_http", "collectionId": request.collection_id,
                    "receipt": {"file": f"{base}/receipts/{receipt_hash}.json", "sha256": receipt_hash}, "fetchedAt": fetched.fetched_at,
                    "finalUrl": fetched.final_url, "httpStatus": fetched.status, "contentType": fetched.content_type, "bodySha256": body_hash,
                    "documentKind": target.document_kind, "network": network, "published": declared_published(target.published_at).wire()})
                item = _target_item(target, fetched, collected)
                current_grant()  # Metadata preparation can also take time; guard immediately before the first write.
                output.write(f"receipts/{receipt_hash}.json", receipt_bytes)
                current_grant()  # A revocation while writing the receipt also forbids storing the body.
                output.write(f"bodies/{body_hash}.bin", fetched.body)
                documents[body_hash] = {"file": f"{base}/bodies/{body_hash}.bin", "sha256": body_hash}
                items.append(item.wire())
                outcome.update(outcome="collected", bodySha256=body_hash, receiptSha256=receipt_hash)
            except _AuthorityChanged:
                raise
            except IngestionFailure as exc:
                outcome["code"] = exc.code
            except ValidationError:
                outcome["code"] = "receipt_invalid"
            outcomes.append(outcome)
        collected_count = sum(o["outcome"] == "collected" for o in outcomes)
        state = "complete" if collected_count == len(outcomes) else "partial" if collected_count else "failed"
        page_bytes = canonical({"items": items, "more": False, "nextCursor": None}).encode("utf-8")
        page_hash = byte_hash(page_bytes)
        output.write("page-0.json", page_bytes)
        manifest = Manifest.model_validate({
            "schemaVersion": "zoop-ingestion-s2-1", "sourceId": source.source_id, "scopeId": scope.scope_id,
            "pages": [{"pageId": f"collection-{request.collection_id}", "cursor": scope.initial_cursor,
                       "response": {"file": f"{base}/page-0.json", "sha256": page_hash},
                       "status": {"complete": "ok", "partial": "partial", "failed": "failed"}[state], "nextCursor": None, "terminal": True,
                       "coverageThrough": None}],
            "documents": {k: FileRef.model_validate(v).wire() for k, v in documents.items()}})
        manifest_bytes = canonical(manifest.wire()).encode("utf-8")
        result = {"schemaVersion": SCHEMA, "collectionId": request.collection_id, "requestDigest": request_digest, "sourceId": source.source_id,
                  "scopeId": scope.scope_id, "provenance": "collected_http", "state": state, "startedAt": started, "completedAt": now(), "grant": grant,
                  "manifest": {"file": f"{base}/manifest.json", "sha256": byte_hash(manifest_bytes)}, "targets": outcomes,
                  "usage": {"requests": fetcher.requests, "bytes": fetcher.downloaded, "targets": len(outcomes), "collected": collected_count}}
        output.write("manifest.json", manifest_bytes)
        output.write("collection.json", canonical(result).encode("utf-8"))
        output.commit(request.collection_id, current_grant)
        return {**result, "replayed": False, "manifestPath": str(Path(source.input_root) / result["manifest"]["file"])}
    except BaseException:
        output.abort()
        raise
