"""Pinned local routes to native owners; current grant bytes remain live authority."""
from __future__ import annotations

import json
import os
import re
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .extraction import Sources
from .extraction_contracts import ExtractionFailure, ObservationRef
from .graph_projection import Paths, Source
from .handoff_contracts import SourcePin
from .ingestion_contracts import Authority, IngestionFailure, Wire, byte_hash, canonical, read_file, reserved_state_roots

SCHEMA = "zoop-handoff-source-contexts-1"
MAX_BYTES = 2_000_000


def identity(value) -> str:
    return canonical(value.wire())


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


class Context(Wire):
    context_id: str = Field(min_length=1, max_length=200)
    relation_state_directory: str
    extraction_state_directory: str
    ingestion_state_directory: str
    sources: str
    source_pins: list[SourcePin] = Field(min_length=1)
    observations: list[ObservationRef] = Field(min_length=1)

    @model_validator(mode="after")
    def paths_absolute(self):
        for value in (self.relation_state_directory, self.extraction_state_directory, self.ingestion_state_directory, self.sources):
            if not os.path.isabs(value) or os.path.normpath(value) != value:
                raise ValueError("absolute normalized path required")
        return self

    def paths(self, canonical_path: Path) -> Paths:
        return Paths(Path(self.relation_state_directory), Path(self.extraction_state_directory), Path(self.ingestion_state_directory),
                     Path(self.sources), canonical_path)


class Inventory(Wire):
    schema_version: Literal["zoop-handoff-source-contexts-1"]
    contexts: list[Context] = Field(min_length=1)


@dataclass(frozen=True)
class Route:
    context_id: str
    paths: Paths


class Contexts:
    """One concrete route table for both explicit inventories and singular source-path input."""

    def __init__(self, routes: tuple[Route, ...], pins: dict[str, Route], observations: dict[str, Route], *,
                 file: Path | None = None, sha256: str | None = None):
        self.routes, self.pins, self.observations = routes, pins, observations
        self.file, self.sha256 = file, sha256

    @classmethod
    def single(cls, paths: Paths) -> Contexts:
        return cls((Route("single", paths),), {}, {})

    @classmethod
    def read(cls, file: Path, sha256: str, canonical_path: Path) -> Contexts:
        if not isinstance(sha256, str) or re.fullmatch(r"[a-f0-9]{64}", sha256) is None:
            raise ExtractionFailure("source_contexts_invalid")
        try:
            raw = read_file(file, MAX_BYTES)
            if byte_hash(raw) != sha256:
                raise ExtractionFailure("source_contexts_changed")
            inventory = Inventory.model_validate(json.loads(raw, object_pairs_hook=_object))
        except (IngestionFailure, OSError, ValueError):
            raise ExtractionFailure("source_contexts_invalid") from None
        routes, pins, observations, jobs, upstreams, ids = [], {}, {}, {}, {}, set()
        for context in inventory.contexts:
            if context.context_id in ids:
                raise ExtractionFailure("source_context_route_duplicate")
            ids.add(context.context_id)
            route = Route(context.context_id, context.paths(canonical_path))
            routes.append(route)
            for pin in context.source_pins:
                key = identity(pin)
                owner = (context.context_id, pin.relation.input_digest, identity(pin.upstream))
                if key in pins or (pin.relation.job_id in jobs and jobs[pin.relation.job_id] != owner):
                    raise ExtractionFailure("source_context_route_duplicate")
                previous = upstreams.get(pin.upstream.job_id)
                upstream = (context.context_id, identity(pin.upstream))
                if previous is not None and previous != upstream:
                    raise ExtractionFailure("source_context_route_duplicate")
                pins[key], jobs[pin.relation.job_id], upstreams[pin.upstream.job_id] = route, owner, upstream
            for ref in context.observations:
                key = identity(ref)
                if key in observations:
                    raise ExtractionFailure("source_context_route_duplicate")
                observations[key] = route
        result = cls(tuple(routes), pins, observations, file=file, sha256=sha256)
        result.check_roots()
        return result

    def check_roots(self) -> None:
        roots = self.roots()
        forbidden = reserved_state_roots()
        for i, root in enumerate(roots):
            if any(root == other or root.is_relative_to(other) or other.is_relative_to(root) for other in (*roots[:i], *forbidden)):
                raise ExtractionFailure("state_namespace_conflict")
            if self.file is not None and self.file.absolute().is_relative_to(root):
                raise ExtractionFailure("state_namespace_conflict")
            if any(parent.is_symlink() for parent in (*root.parents, root)):
                raise ExtractionFailure("state_namespace_invalid")
        for route in self.routes:
            if any(route.paths.sources == root or route.paths.sources.is_relative_to(root) for root in roots):
                raise ExtractionFailure("state_namespace_conflict")

    def roots(self) -> tuple[Path, ...]:
        return tuple(p for route in self.routes for p in (route.paths.relation, route.paths.extraction, route.paths.ingestion))

    def unchanged(self) -> None:
        if self.file is not None:
            try:
                same = byte_hash(read_file(self.file, MAX_BYTES)) == self.sha256
            except (IngestionFailure, OSError):
                same = False
            if not same:
                raise ExtractionFailure("source_contexts_changed")

    def for_pin(self, pin: SourcePin) -> Route:
        if self.file is None:
            return self.routes[0]
        route = self.pins.get(identity(pin))
        if route is None:
            raise ExtractionFailure("source_context_pin_missing")
        return route

    def for_observation(self, ref: ObservationRef) -> Route:
        if self.file is None:
            return self.routes[0]
        route = self.observations.get(identity(ref))
        if route is None:
            raise ExtractionFailure("source_context_observation_missing")
        return route

    def bound(self, pin: SourcePin, ref: ObservationRef) -> None:
        if self.for_pin(pin) != self.for_observation(ref):
            raise ExtractionFailure("source_context_observation_misrouted")

    @contextmanager
    def open(self, pins):
        self.unchanged()
        selected = {self.for_pin(pin).context_id for pin in pins}
        with ExitStack() as stack:
            readers = {route.context_id: stack.enter_context(Source(route.paths)) for route in self.routes if route.context_id in selected}
            yield readers
            self.unchanged()

    def export(self, ref: ObservationRef, *, send=None) -> dict:
        self.unchanged()
        paths = self.for_observation(ref).paths
        result = Sources(paths.ingestion, Authority(paths.sources)).export(ref, send=send)
        self.unchanged()
        return result

    def authorize_model_send(self, ref: ObservationRef, purpose: str, recipient: str) -> None:
        self.export(ref, send=(purpose, recipient))


def source_flags(parser) -> None:
    parser.add_argument("--source-contexts", type=Path)
    parser.add_argument("--source-contexts-sha256")


def configured(args, *, sourced: bool) -> bool:
    single = (args.relation_state_dir, args.extraction_state_dir, args.ingestion_state_dir, args.sources)
    routed = (args.source_contexts, args.source_contexts_sha256)
    if not sourced:
        return all(value is None for value in (*single, *routed))
    return ((all(value is not None for value in single) and all(value is None for value in routed))
            or (all(value is None for value in single) and all(value is not None for value in routed)))
