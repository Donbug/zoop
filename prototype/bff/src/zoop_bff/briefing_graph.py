"""Relationship graph of a briefing round (FS032, D03): the relations and evidence it was published with.

A round stores the graph version, the review-decision revision and the publication-rule revision it was built
from. All three are immutable or append-only (a version file is written once and checksum-verified, decisions
and rule switches only ever gain rows), so cutting them at those numbers rebuilds exactly what the round saw,
whatever has been reviewed, switched or published since. The result is checked against the published payload
(same key issues, evidence and companies) before it is served. When the version, its file or that match is
missing the round says so (``unavailable``); the newest graph is never substituted.

Suspended rounds serve no graph, like their briefing body. Corrections stay beside the original (counted here,
shown on the briefing); they do not rewrite the graph.
"""

from __future__ import annotations

import logging
from typing import Any

from .briefing_rounds import BriefingService, Row, parse_round_id
from .dataset import Dataset
from .errors import ApiError, SourceUnavailable, not_found
from .review import ReviewStore
from .schemas import BriefingGraphBasis
from .sources import DataProvider, Pin
from .views import company_links

log = logging.getLogger("zoop_bff.briefing_graph")

NOT_PUBLISHED = "발행된 회차가 아니라서 관계 그래프가 없어요."
SUSPENDED = "이 회차는 제공을 잠시 중단했어요."
UNAVAILABLE = "이 회차를 발행할 당시의 관계 자료를 찾지 못했어요. 최신 자료로 바꿔 보여드리지 않아요."


class BriefingGraphs:
    def __init__(self, rounds: BriefingService, provider: DataProvider, reviews: ReviewStore):
        self._rounds = rounds
        self._provider = provider
        self._reviews = reviews

    def basis(self, round_id: str) -> BriefingGraphBasis:
        return self._resolve(round_id)[0]

    def dataset(self, round_id: str) -> Dataset:
        """The graph of the round as published; raises when the round has none to show."""
        basis, dataset = self._resolve(round_id)
        if dataset is not None:
            return dataset
        if basis.status == "suspended":
            raise ApiError(403, "briefing_round_suspended", basis.message or SUSPENDED)
        if basis.status == "not_published":
            raise not_found("briefing_not_published", basis.message or NOT_PUBLISHED)
        raise not_found("briefing_graph_unavailable", basis.message or UNAVAILABLE)

    # ------------------------------------------------------------------ internals
    def _resolve(self, round_id: str) -> tuple[BriefingGraphBasis, Dataset | None]:
        parsed = parse_round_id(round_id)
        if parsed is None:
            raise not_found("briefing_round_not_found", "브리핑 회차를 찾을 수 없습니다.")
        day, edition = parsed
        row = self._rounds.record(round_id)
        fields: dict[str, Any] = {
            "round_id": round_id,
            "date": day.isoformat(),
            "edition": edition,
            "message": None,
            "reason": None,
            "published_at": None,
            "data_as_of": None,
            "graph_version": None,
            "key_issue_ids": [],
            "company_ids": [],
            "correction_count": 0,
        }
        if row is None or row.payload is None:
            return BriefingGraphBasis(status="not_published", **{**fields, "message": NOT_PUBLISHED}), None
        payload = row.payload
        fields.update(
            published_at=row.data.get("published_at"),
            data_as_of=payload["dataWindow"]["end"],
            graph_version=payload["graphVersion"],
            correction_count=self._rounds.correction_count(round_id),
        )
        if row.status == "suspended":
            reason = (row.data.get("suspension") or {}).get("reason")
            return BriefingGraphBasis(status="suspended", **{**fields, "message": SUSPENDED, "reason": reason}), None
        try:
            dataset = self._provider.get_pinned(self._pin(row))
            if not _matches_payload(dataset, payload):
                raise SourceUnavailable(
                    "기준 시점 그래프가 발행된 회차와 맞지 않습니다.",
                    {"source": "graph-version", "cause": "PayloadMismatch", "round": round_id},
                )
        except SourceUnavailable as exc:
            log.warning("briefing graph of %s unavailable: %s %s", round_id, exc.message, exc.details)
            return BriefingGraphBasis(status="unavailable", **{**fields, "message": UNAVAILABLE}), None
        return (
            BriefingGraphBasis(
                status="available",
                **{
                    **fields,
                    "key_issue_ids": [i["eventId"] for i in payload["items"]],
                    "company_ids": list(payload["references"]["companyIds"]),
                },
            ),
            dataset,
        )

    def _pin(self, row: Row) -> Pin:
        payload = row.payload
        assert payload is not None
        version_id = payload.get("graphVersion")
        if not version_id:
            raise SourceUnavailable("회차에 그래프 버전이 기록되어 있지 않습니다.", {"source": "graph-version", "cause": "NoVersion"})
        rule_revision = payload.get("ruleRevision")
        if rule_revision is None:
            # Published before the rule revision was recorded: the rule log as it stood when the round was generated.
            rule_revision = self._reviews.rules.revision_at(payload["generatedAt"])
        return Pin(version_id, int(payload["reviewRevision"]), int(rule_revision))


def _matches_payload(dataset: Dataset, payload: dict[str, Any]) -> bool:
    """Every published key issue exists in the rebuilt graph with the same title, evidence and companies."""
    for item in payload["items"]:
        issue = dataset.issues.get(item["eventId"])
        if issue is None or issue.title != item["title"]:
            return False
        if set(issue.evidence_ids) != set(item["evidenceIds"]):
            return False
        if [c.id for c in company_links(dataset, issue)] != [c["id"] for c in item["companies"]]:
            return False
    return True
