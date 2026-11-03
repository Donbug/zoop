"""Pinned finite AI civil calendar and conservative inventory retrieval proof."""
from __future__ import annotations

import hashlib
import json
from datetime import date as CivilDate, datetime, time, timedelta, timezone
from typing import Literal

from pydantic import Field, model_validator

from .ingestion_contracts import IngestionFailure, Wire, timestamp

KST = timezone(timedelta(hours=9))


class Coverage(Wire):
    start_date: CivilDate = Field(strict=False)
    end_date: CivilDate = Field(strict=False)
    lookahead_end_date: CivilDate = Field(strict=False)


class CalendarSource(Wire):
    id: str = Field(min_length=1, max_length=200)
    url: str = Field(pattern=r"^https://", max_length=2000)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    retrieved_at: str

    @model_validator(mode="after")
    def valid_time(self):
        if len(self.retrieved_at) == 10:
            CivilDate.fromisoformat(self.retrieved_at)
        else:
            timestamp(self.retrieved_at)
        return self


class CalendarDate(Wire):
    date: CivilDate = Field(strict=False)
    is_business_day: bool = Field(strict=True)
    holiday_names: list[str]
    source_ids: list[str]


class Calendar(Wire):
    schema_version: Literal[1]
    timezone: Literal["Asia/Seoul"]
    coverage: Coverage
    calendar_kind: Literal["KR_CIVIL_WEEKDAY_PUBLIC_HOLIDAYS"]
    evidence_cutoff: CivilDate = Field(strict=False)
    dates: list[CalendarDate] = Field(min_length=1, max_length=36600)
    sources: list[CalendarSource] = Field(min_length=1)
    operational_approval: bool = Field(strict=True)

    @model_validator(mode="after")
    def complete_dates(self):
        c = self.coverage
        if not c.start_date <= c.end_date < c.lookahead_end_date:
            raise ValueError("calendar horizon")
        expected = (c.lookahead_end_date - c.start_date).days + 1
        if len(self.dates) != expected or any(row.date != c.start_date + timedelta(days=i) for i, row in enumerate(self.dates)):
            raise ValueError("calendar dates must be explicit and contiguous")
        ids = {source.id for source in self.sources}
        if len(ids) != len(self.sources):
            raise ValueError("duplicate calendar source")
        for row in self.dates:
            if not row.source_ids or not set(row.source_ids) <= ids or row.is_business_day != (row.date.weekday() < 5 and not row.holiday_names):
                raise ValueError("civil weekday evidence mismatch")
        return self


class CalendarEligibility(Wire):
    kind: Literal["through-next-business-day-close-1"]
    calendar_json: str = Field(max_length=1_500_000)
    calendar_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    inventory_max_age_seconds: int = Field(gt=0, strict=True)

    def calendar(self):
        raw = self.calendar_json.encode("utf-8")
        if len(raw) > 1_500_000:
            raise IngestionFailure("calendar_invalid")
        if hashlib.sha256(raw).hexdigest() != self.calendar_sha256:
            raise IngestionFailure("calendar_digest_mismatch")
        try:
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate calendar key")
                    result[key] = value
                return result
            doc = Calendar.model_validate(json.loads(raw, object_pairs_hook=unique))
        except ValueError:
            raise IngestionFailure("calendar_invalid") from None
        return ReviewedCalendar(doc, self.inventory_max_age_seconds)


class ReviewedCalendar:
    def __init__(self, doc, retrieval_bound):
        self.doc = doc
        self.days = {row.date: row.is_business_day for row in doc.dates}
        self.deadlines = {}
        following = None
        for row in reversed(doc.dates):
            if doc.coverage.start_date <= row.date <= doc.coverage.end_date and row.is_business_day:
                if following is None:
                    raise IngestionFailure("calendar_horizon_unavailable")
                self.deadlines[row.date] = datetime.combine(following, time(18, 5), KST)
            if row.is_business_day:
                following = row.date
        if not self.deadlines:
            raise IngestionFailure("calendar_horizon_unavailable")
        self.required_bound = int(max((deadline - datetime.combine(day, time(9, 5), KST)).total_seconds()
                                      for day, deadline in self.deadlines.items()))
        if retrieval_bound < self.required_bound:
            raise IngestionFailure("calendar_inventory_bound_insufficient")

    def business(self, value):
        day = value.astimezone(KST).date()
        if not self.doc.coverage.start_date <= day <= self.doc.coverage.end_date:
            raise IngestionFailure("calendar_horizon_unavailable")
        return self.days[day]

    def eligible(self, origin, as_of):
        # Only original ordinary slots inside the reviewed admission horizon have deadlines.
        when, now = timestamp(origin).astimezone(KST), timestamp(as_of).astimezone(KST)
        self.business(now)
        if not self.doc.coverage.start_date <= when.date() <= self.doc.coverage.end_date:
            raise IngestionFailure("calendar_origin_unavailable")
        if not self.days[when.date()] or not (9 <= when.hour < 18 and when.minute in (5, 35) and when.second == when.microsecond == 0):
            raise IngestionFailure("calendar_origin_invalid")
        return when <= now <= self.deadlines[when.date()]


def review(value):
    if set(value) != {"schemaVersion", "eligibility", "asOf", "slot"} or value["schemaVersion"] != "zoop-ai-round-calendar-check-1":
        raise IngestionFailure("input_or_configuration_invalid")
    policy = CalendarEligibility.model_validate(value["eligibility"])
    calendar = policy.calendar()
    slot, now = timestamp(value["slot"]), timestamp(value["asOf"])
    slot_business = calendar.business(slot)
    now_business = calendar.business(now)
    return {"schemaVersion": value["schemaVersion"], "calendarSha256": policy.calendar_sha256,
            "requiredInventoryMaxAgeSeconds": calendar.required_bound,
            "businessDay": slot_business and now_business}
