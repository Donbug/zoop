"""Wires the usage-insight services (events, statistics, votes, transcripts, member management)."""

from __future__ import annotations

from dataclasses import dataclass

from .accounts import AccountStore
from .admin_members import MemberAdminService
from .admin_services import AdminServices
from .feedback import FeedbackService
from .feedback_transcripts import TranscriptService
from .insights_common import SubjectKeys
from .telemetry import TelemetryService
from .telemetry_stats import StatsService


@dataclass(frozen=True)
class Insights:
    keys: SubjectKeys
    telemetry: TelemetryService
    stats: StatsService
    feedback: FeedbackService
    transcripts: TranscriptService
    members: MemberAdminService


def build_insights(admin: AdminServices, accounts: AccountStore) -> Insights:
    keys = SubjectKeys(admin.db)
    feedback = FeedbackService(admin.db, admin.clock, keys, accounts)
    return Insights(
        keys=keys,
        telemetry=TelemetryService(admin.db, admin.clock),
        stats=StatsService(admin.db, admin.clock, keys, feedback),
        feedback=feedback,
        transcripts=TranscriptService(admin.db, admin.clock, keys, admin.audit, accounts, feedback),
        members=MemberAdminService(admin.db, admin.clock, keys, admin.audit, accounts),
    )
