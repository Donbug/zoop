"""One-off document URL collection protocol. Only explicitly listed URLs are fetched; nothing is discovered or scheduled.

Every limit is mandatory in the operator's policy file: there is no default user agent and no default budget. Descriptive
metadata (title, dates, kind, publisher) comes only from the request and is never scraped from the fetched page or guessed from the host.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .ingestion_contracts import MAX_RAW, Declared, Published, Wire

SCHEMA = "zoop-collection-1"
POLICY_SCHEMA = "zoop-collection-policy-1"
MAX_POLICY = 100_000
COLLECTION_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})$")
_LOCAL = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?$")


class Policy(Wire):
    schema_version: Literal["zoop-collection-policy-1"]
    user_agent: str = Field(min_length=1, max_length=200)
    timeout_seconds: int = Field(ge=1, le=300)
    max_total_seconds: int = Field(ge=1, le=3600)
    max_redirects: int = Field(ge=0, le=5)
    max_requests: int = Field(ge=1, le=200)
    max_response_bytes: int = Field(ge=1, le=MAX_RAW)
    max_total_bytes: int = Field(ge=1, le=200_000_000)
    min_interval_seconds: float = Field(ge=0, le=60)
    allowed_media_types: list[Literal["text/html", "application/pdf"]] = Field(min_length=1, max_length=2)
    # Explicit synthetic-test switch: http and non-default ports are allowed ONLY for localhost/127.0.0.1 resolving to loopback.
    synthetic_loopback: bool = False

    @field_validator("user_agent")
    @classmethod
    def printable(cls, value: str) -> str:
        if any(not 0x20 <= ord(c) <= 0x7E for c in value):
            raise ValueError("user agent must be printable ASCII")
        return value

    @model_validator(mode="after")
    def ordered(self):
        if self.max_response_bytes > self.max_total_bytes or self.timeout_seconds > self.max_total_seconds:
            raise ValueError("per-item limits exceed the run limits")
        return self


def declared_published(value: str | None) -> Published:
    """Classify a declared publication time without ever turning a date into a midnight or assuming a timezone."""
    if value is None:
        return Published(raw=None, precision="unknown", date=None, basis="not declared by the operator")
    if _DATE.match(value):
        date.fromisoformat(value)
        return Published(raw=value, precision="day", date=value, basis="declared calendar date; no time or timezone claimed")
    if _INSTANT.match(value):
        datetime.fromisoformat(value)
        return Published(raw=value, precision="instant", date=None, basis="declared instant with explicit UTC offset")
    if _LOCAL.match(value):
        datetime.fromisoformat(value)
        return Published(raw=value, precision="unresolved", date=None, basis="declared date-time without UTC offset; timezone not assumed")
    raise ValueError("unsupported publication time")


class Target(Declared):
    candidate_id: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=4000)
    supplier_document_id: str | None = Field(default=None, min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=2000)
    document_kind: Literal["news", "disclosure"]
    published_at: str | None = None
    modified_at: str | None = None
    source_revision: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def declared(self):
        declared_published(self.published_at)
        if self.modified_at is not None and not _INSTANT.match(self.modified_at):
            raise ValueError("modified time needs an explicit UTC offset")
        if self.modified_at is not None:
            datetime.fromisoformat(self.modified_at)
        return self


class Request(Wire):
    schema_version: Literal["zoop-collection-1"]
    collection_id: str = Field(pattern=COLLECTION_ID)
    source_id: str = Field(min_length=1, max_length=200)
    scope_id: str = Field(min_length=1, max_length=200)
    targets: list[Target] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique(self):
        if len({t.candidate_id for t in self.targets}) != len(self.targets) or len({t.url for t in self.targets}) != len(self.targets):
            raise ValueError("duplicate target")
        return self
