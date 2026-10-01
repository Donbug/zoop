"""Where the user-facing dataset comes from: the active published graph version plus review records."""

from __future__ import annotations

import json
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .dataset import CompanyRec, Dataset, DatasetFormatError, build_dataset, parse_companies
from .errors import SourceUnavailable
from .graph_versions import GraphStore, GraphVersion
from .review import ReviewStore

log = logging.getLogger("zoop_bff.sources")

PINNED_CACHE_SIZE = 8


@dataclass(frozen=True)
class Pin:
    """A past graph state: the immutable version file plus both append-only review logs cut at a revision."""

    version_id: str
    review_revision: int
    rule_revision: int


class PublishedSource:
    """The active graph version overlaid with the admin review records (never the PoC DB)."""

    mode = "snapshot"

    def __init__(self, store: GraphStore, reviews: ReviewStore):
        self._store = store
        self._reviews = reviews

    def _active(self):
        self._store.ensure_seed()
        version = self._store.active()
        if version is None:
            raise SourceUnavailable(
                "게시된 그래프 버전이 없습니다.", {"source": "graph-version", "cause": "NoActiveVersion"}
            )
        return version

    @property
    def label(self) -> str:
        return self._active().source_label

    @property
    def graph_version(self) -> str | None:
        return self._active().id

    def stamp(self) -> object:
        """(version id, review revision, (file stamp, rule revision)): the briefing service records the first two."""
        active = self._active()
        return (active.id, self._reviews.revision(), (self._store.file_stamp(active), self._reviews.rules.revision()))

    def warnings(self) -> list[str]:
        return self._store.warnings()

    def load(self) -> tuple[dict[str, Any], str]:
        version = self._active()
        payload = self._store.read_payload(version)
        return self._reviews.apply(payload), version.source_as_of

    def load_pinned(self, pin: Pin) -> tuple[dict[str, Any], GraphVersion]:
        """A past state: that exact version file (checksum-verified) with the review logs cut at the pin.

        Never falls back to the active version: a missing version or file raises ``SourceUnavailable``.
        """
        version = self._store.get(pin.version_id)
        if version is None:
            raise SourceUnavailable(
                "기준 시점의 그래프 버전이 등록되어 있지 않습니다.",
                {"source": "graph-version", "cause": "VersionNotRegistered", "version": pin.version_id},
            )
        payload = self._store.read_payload(version)
        return self._reviews.apply_as_of(payload, pin.review_revision, pin.rule_revision), version

    def pinned_file_stamp(self, pin: Pin) -> tuple[int, int] | None:
        version = self._store.get(pin.version_id)
        return self._store.file_stamp(version) if version else None


def _load_catalog(path: Path | None) -> tuple[list[CompanyRec], list[str], object]:
    """Company records from any JSON whose top level has ``companies`` (e.g. PoC settings.json)."""
    if path is None:
        return [], [], None
    try:
        stat = path.stat()
        data = json.loads(path.read_text(encoding="utf-8"))
        catalog, warnings = parse_companies(data.get("companies", []), "poc-settings")
        return catalog, warnings, (stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError, AttributeError, DatasetFormatError) as exc:
        log.warning("company catalog %s unusable: %s", path, exc)
        return [], [f"company catalog unreadable: {path.name} ({type(exc).__name__})"], None


class DataProvider:
    """Builds the normalized dataset on demand; failures raise ``SourceUnavailable`` (never empty data)."""

    def __init__(self, settings: Settings, source: PublishedSource):
        self._settings = settings
        self.source = source
        self._lock = threading.Lock()
        self._cached: Dataset | None = None
        self._key: object | None = None
        self._catalog_cache: tuple[object, list[CompanyRec], list[str]] | None = None
        self._pinned: OrderedDict[object, Dataset] = OrderedDict()

    def _catalog(self) -> tuple[list[CompanyRec], list[str], object]:
        path = self._settings.company_catalog
        try:
            stamp: object = (
                (path.stat().st_mtime_ns, path.stat().st_size) if path else None
            )
        except OSError:
            stamp = "missing"
        cached = self._catalog_cache
        if cached is not None and cached[0] == stamp:
            return cached[1], cached[2], stamp
        catalog, warnings, _ = _load_catalog(path)
        self._catalog_cache = (stamp, catalog, warnings)
        return catalog, warnings, stamp

    def get(self) -> Dataset:
        with self._lock:
            catalog, warnings, catalog_stamp = self._catalog()
            try:
                stamp = self.source.stamp()
            except SourceUnavailable:
                self._cached = None
                raise
            key = (stamp, catalog_stamp)
            if self._cached is not None and key == self._key:
                return self._cached
            self._cached = None
            payload, as_of = self.source.load()
            seed_warnings = self.source.warnings()
            try:
                dataset = build_dataset(
                    payload,
                    source_mode="snapshot",
                    source_label=self.source.label,
                    as_of=as_of,
                    catalog=catalog,
                    warnings=[*warnings, *seed_warnings],
                    graph_version=self.source.graph_version,
                )
            except (DatasetFormatError, KeyError, TypeError, AttributeError) as exc:
                log.warning("inspect payload malformed: %r", exc)
                raise SourceUnavailable(
                    "승인 데이터의 형식이 올바르지 않습니다.",
                    {"source": self.source.mode, "cause": type(exc).__name__, "reason": str(exc)},
                ) from exc
            self._cached, self._key = dataset, key
            return dataset

    def get_pinned(self, pin: Pin) -> Dataset:
        """The dataset of a past state (see ``PublishedSource.load_pinned``); built once, then served from a small cache.

        The key holds the version file's (mtime, size), so a file that vanished or changed is read (and
        checksum-verified) again instead of being answered from memory.
        """
        with self._lock:
            catalog, warnings, catalog_stamp = self._catalog()
            key = (pin, self.source.pinned_file_stamp(pin), catalog_stamp)
            cached = self._pinned.get(key)
            if cached is not None:
                self._pinned.move_to_end(key)
                return cached
            payload, version = self.source.load_pinned(pin)
            try:
                dataset = build_dataset(
                    payload,
                    source_mode="snapshot",
                    source_label=version.source_label,
                    as_of=version.source_as_of,
                    catalog=catalog,
                    warnings=warnings,
                    graph_version=version.id,
                )
            except (DatasetFormatError, KeyError, TypeError, AttributeError) as exc:
                log.warning("pinned inspect payload malformed: %r", exc)
                raise SourceUnavailable(
                    "기준 시점 승인 데이터의 형식이 올바르지 않습니다.",
                    {"source": "graph-version", "cause": type(exc).__name__, "version": version.id},
                ) from exc
            self._pinned[key] = dataset
            while len(self._pinned) > PINNED_CACHE_SIZE:
                self._pinned.popitem(last=False)
            return dataset
