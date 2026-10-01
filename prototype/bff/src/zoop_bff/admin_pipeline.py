"""Admin pipeline view (requirement 76): the PoC ledger as candidates, review decisions, publication.

The ledger is only read (``PostgresRepository.inspect()`` and a few SELECTs). Decisions never touch it:
they are records in the state directory laid over the active graph version (see ``review.py``).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from typing import Any

from .admin_ledger import Ledger, Neo4jProbe
from .admin_schemas import (
    CandidateArticle,
    CandidateCompany,
    CandidateCounts,
    CandidateDetail,
    CandidateEvidence,
    CandidateList,
    CandidateMention,
    CandidateRelation,
    CandidateRow,
    DecisionRequest,
    DecisionResponse,
    ErrorInfo,
    FieldVerdictOut,
    GraphDbStatus,
    IssueCounts,
    LedgerCounts,
    LedgerRef,
    Neo4jStatus,
    ObservationOut,
    Overview,
    PolicyInfo,
    PublicationState,
    ReviewCounts,
    ReviewDecisionOut,
    VerdictOut,
    VerificationOut,
)
from .audit import Actor, AuditLog, Clock
from .errors import ApiError
from .graph_versions import GraphStore, GraphVersion, canonical
from .review import (
    Decision,
    ReviewStore,
    apply_reviews,
    has_quote,
    published_candidate_ids,
    published_relation_ids,
)
from .statedb import utc_iso

_INSPECT_TTL_SECONDS = 3.0
_PROJECTION_TTL_SECONDS = 5.0
_PAGE_MAX = 200


def decision_out(d: Decision) -> ReviewDecisionOut:
    return ReviewDecisionOut(
        id=d.id,
        target_type=d.target_type,
        target_id=d.target_id,
        decision=d.decision,
        reason=d.reason,
        admin_email=d.admin_email,
        decided_at=d.at,
        revision=d.id,
        origin=d.origin,
    )


def _companies(mention: Mapping[str, Any]) -> list[CandidateCompany]:
    return [
        CandidateCompany(company_id=p.get("company_id"), name=p.get("name") or "", role=p.get("role") or "")
        for p in mention.get("participants") or []
    ]


class PipelineService:
    def __init__(
        self,
        *,
        ledger: Ledger,
        neo4j: Neo4jProbe,
        reviews: ReviewStore,
        graphs: GraphStore,
        audit: AuditLog,
        clock: Clock,
    ):
        self._ledger = ledger
        self._neo4j = neo4j
        self._reviews = reviews
        self._graphs = graphs
        self._audit = audit
        self._clock = clock
        self._lock = threading.Lock()
        self._inspect_cache: tuple[float, dict[str, Any]] | None = None
        self._projection_cache: tuple[float, GraphDbStatus] | None = None
        self._effective_cache: tuple[Any, dict[str, Any]] | None = None

    # ---- ledger reads
    @property
    def database(self) -> str:
        return self._ledger.database

    def inspect(self, *, fresh: bool = False) -> dict[str, Any]:
        with self._lock:
            cached = self._inspect_cache
            if not fresh and cached is not None and time.monotonic() - cached[0] < _INSPECT_TTL_SECONDS:
                return cached[1]
        payload = self._ledger.inspect()  # may raise ledger_unavailable (503)
        with self._lock:
            self._inspect_cache = (time.monotonic(), payload)
        return payload

    def forget(self) -> None:
        """Drop cached ledger reads (after a publish or a finished job)."""
        with self._lock:
            self._inspect_cache = None
            self._projection_cache = None

    def effective_payload(self) -> dict[str, Any]:
        """What users see right now: the active version with the review records applied."""
        self._graphs.ensure_seed()
        active = self._graphs.active()
        if active is None:
            raise ApiError(503, "source_unavailable", "게시된 그래프 버전이 없습니다.")
        key = (active.id, self._reviews.revision())
        with self._lock:
            cached = self._effective_cache
            if cached is not None and cached[0] == key:
                return cached[1]
        payload = apply_reviews(self._graphs.read_payload(active), self._reviews.effective())
        with self._lock:
            self._effective_cache = (key, payload)
        return payload

    # ---- GraphDB projection (requirement 76: 미반영 실측)
    def projection_status(self, *, fresh: bool = False) -> GraphDbStatus:
        with self._lock:
            cached = self._projection_cache
            if not fresh and cached is not None and time.monotonic() - cached[0] < _PROJECTION_TTL_SECONDS:
                return cached[1]
        status = self._measure_projection()
        with self._lock:
            self._projection_cache = (time.monotonic(), status)
        return status

    def _measure_projection(self) -> GraphDbStatus:
        now = utc_iso(self._clock.now())
        outbox = self._ledger.projection()  # ledger_unavailable propagates: the dashboard maps it
        pending = int(outbox["pending"])
        ledger_relations: dict[str, set[str]] = {}
        neo4j: Neo4jStatus
        try:
            ledger_relations = {
                i["issue_id"]: {r["relation_id"] for r in i.get("relations") or []}
                for i in self.inspect()["issues"]
            }
            projected = self._neo4j.projected()
        except ApiError:
            raise
        except Exception as exc:  # Neo4j down, auth, driver: measured as unreachable, never guessed
            neo4j = Neo4jStatus(
                status="unreachable",
                issues_in_ledger=len(ledger_relations),
                issues_projected=None,
                missing_issue_ids=[],
                stale_issue_ids=[],
                error=ErrorInfo(code="neo4j_unreachable", message=f"Neo4j에 연결하지 못했습니다 ({type(exc).__name__})."),
            )
        else:
            # Same unit on both sides: ledger issues. A ledger issue is reflected when Neo4j holds it with
            # every relation. Issues Neo4j holds that the ledger does not have at all are foreign (the
            # zoop-poc instance also holds the synthetic ledger's projection): reported, but they are not
            # an unreflected ledger change and flush-graph cannot remove them.
            missing = sorted(
                i for i, relations in ledger_relations.items() if i not in projected or relations - projected[i]
            )
            diverged = [i for i, relations in ledger_relations.items() if i in projected and projected[i] - relations]
            foreign = [i for i in projected if i not in ledger_relations]
            neo4j = Neo4jStatus(
                status="reachable",
                issues_in_ledger=len(ledger_relations),
                issues_projected=len(ledger_relations) - len(missing),
                missing_issue_ids=missing,
                stale_issue_ids=sorted([*diverged, *foreign]),
                error=None,
            )
        if pending:
            status = "pending"
        elif neo4j.status == "unreachable":
            status = "unavailable"
        elif neo4j.missing_issue_ids or any(i in ledger_relations for i in neo4j.stale_issue_ids):
            status = "mismatch"
        else:
            status = "reflected"
        return GraphDbStatus(
            status=status,
            pending_jobs=pending,
            oldest_pending_at=outbox.get("oldest_pending_at"),
            last_completed_at=outbox.get("last_completed_at"),
            neo4j=neo4j,
            checked_at=now,
        )

    def ledger_counts(self) -> LedgerCounts:
        payload = self.inspect(fresh=True)
        rows = payload.get("candidates") or []
        counts = {"allow": 0, "hold": 0, "reject": 0, "inactive": 0}
        for row in rows:
            if not row.get("active"):
                counts["inactive"] += 1
            else:
                counts[str(row["status"]).lower()] = counts.get(str(row["status"]).lower(), 0) + 1
        issues = payload.get("issues") or []
        return LedgerCounts(
            captured_at=utc_iso(self._clock.now()),
            candidates=counts,
            issues=len(issues),
            relations=sum(len(i.get("relations") or []) for i in issues),
            pending_projections=int(self._ledger.projection()["pending"]),
        )

    # ---- overview
    def policy_info(self) -> PolicyInfo:
        policy = self._ledger.policy()
        metadata = policy.get("metadata") or {}
        return PolicyInfo(
            version=policy.get("version"),
            decision_policy=_camel_policy(metadata.get("decision_policy")),
            web_verification=bool(metadata.get("web")),
            validation_model=metadata.get("validation_model"),
        )

    def overview(self, runs: list[Any]) -> Overview:
        self._graphs.ensure_seed()
        payload = self.inspect(fresh=True)
        rows = payload.get("candidates") or []
        active_rows = [r for r in rows if r.get("active")]
        by_status = {s: sum(1 for r in active_rows if r["status"] == s) for s in ("ALLOW", "HOLD", "REJECT")}
        issues = payload.get("issues") or []
        articles = {a.get("article_id") for i in issues for a in i.get("articles") or []}
        effective = self._reviews.effective()
        active = self._graphs.active()
        pending = self._pending_hold(rows, effective)
        ledger_ids = {i["issue_id"] for i in issues}
        active_payload = self._graphs.read_payload(active) if active else {}
        active_ids = {i["issue_id"] for i in active_payload.get("issues") or []}
        now = utc_iso(self._clock.now())
        return Overview(
            as_of=now,
            ledger=LedgerRef(database=self.database, checked_at=now),
            policy=self.policy_info(),
            candidates=CandidateCounts(
                total=len(rows),
                active=len(active_rows),
                inactive=len(rows) - len(active_rows),
                allow=by_status["ALLOW"],
                hold=by_status["HOLD"],
                reject=by_status["REJECT"],
            ),
            issues=IssueCounts(
                approved=len(issues),
                relations=sum(len(i.get("relations") or []) for i in issues),
                articles=len(articles),
            ),
            review=ReviewCounts(
                revision=self._reviews.revision(),
                decisions=len(effective),
                allowed=sum(1 for d in effective if d.decision == "allow"),
                rejected=sum(1 for d in effective if d.decision == "reject"),
                hold_pending_review=pending,
            ),
            projection=self.projection_status(),
            publication=PublicationState(
                active_version_id=active.id if active else None,
                ledger_matches_active=bool(active) and _digest(payload) == active.sha256,
                issues_only_in_ledger=sorted(ledger_ids - active_ids)[:50],
                issues_only_in_active=sorted(active_ids - ledger_ids)[:50],
            ),
            runs=runs,
        )

    @staticmethod
    def _pending_hold(rows: list[dict[str, Any]], effective: list[Decision]) -> int:
        decided = {d.target_id for d in effective if d.target_type == "candidate"}
        return sum(
            1
            for r in rows
            if r.get("active") and r["status"] == "HOLD" and r["candidate"]["candidate_id"] not in decided
        )

    def hold_pending_review(self) -> int:
        return self._pending_hold(self.inspect().get("candidates") or [], self._reviews.effective())

    # ---- candidates
    def _row(
        self,
        raw: Mapping[str, Any],
        *,
        published: set[str],
        decisions: Mapping[str, Decision],
    ) -> CandidateRow:
        cand = raw["candidate"]
        mention = cand["mention"]
        validation = raw.get("validation") or {}
        reasons = [str(x) for x in raw.get("reasons") or []]
        if not reasons:
            reasons = [
                str(v.get("reason"))
                for v in validation.get("verdicts") or []
                if v.get("decision") != "ALLOW" and v.get("reason")
            ]
        if raw.get("invalidation_reason"):
            reasons.append(f"비활성: {raw['invalidation_reason']}")
        decision = decisions.get(cand["candidate_id"])
        return CandidateRow(
            candidate_id=cand["candidate_id"],
            issue_id=cand["issue_id"],
            status=raw["status"],
            active=bool(raw.get("active")),
            policy_version=cand.get("policy_version") or "",
            title=mention.get("title") or "",
            action=mention.get("action") or "",
            target=mention.get("target"),
            event_time=mention.get("event_time"),
            companies=_companies(mention),
            relation_types=sorted({r.get("relation_type") for r in cand.get("relations") or [] if r.get("relation_type")}),
            evidence_count=len(mention.get("evidence") or []),
            reasons=reasons,
            on_user_graph=cand["candidate_id"] in published,
            decision=decision_out(decision) if decision else None,
        )

    def candidates(
        self,
        *,
        status: str | None,
        decision: str | None,
        active: bool | None,
        published: bool | None,
        q: str | None,
        limit: int,
        cursor: str | None,
    ) -> CandidateList:
        payload = self.inspect()
        rows = list(reversed(payload.get("candidates") or []))  # the ledger orders oldest first
        on_graph = published_candidate_ids(self.effective_payload())
        decisions = {d.target_id: d for d in self._reviews.effective() if d.target_type == "candidate"}
        counts = {"ALLOW": 0, "HOLD": 0, "REJECT": 0, "inactive": 0}
        for r in rows:
            if r.get("active"):
                counts[r["status"]] += 1
            else:
                counts["inactive"] += 1
        needle = (q or "").strip().lower()

        def keep(r: Mapping[str, Any]) -> bool:
            cand = r["candidate"]
            cid = cand["candidate_id"]
            if status and r["status"] != status:
                return False
            if active is not None and bool(r.get("active")) != active:
                return False
            if published is not None and (cid in on_graph) != published:
                return False
            if decision == "none" and cid in decisions:
                return False
            if decision in ("allow", "reject") and (cid not in decisions or decisions[cid].decision != decision):
                return False
            if needle:
                mention = cand["mention"]
                hay = " ".join(
                    [cid, cand["issue_id"], mention.get("title") or "", *(p.get("name") or "" for p in mention.get("participants") or [])]
                ).lower()
                if needle not in hay:
                    return False
            return True

        matched = [r for r in rows if keep(r)]
        try:
            offset = max(0, int(cursor)) if cursor else 0
        except ValueError as exc:
            raise ApiError(422, "invalid_cursor", "cursor 값이 올바르지 않습니다.") from exc
        limit = max(1, min(limit, _PAGE_MAX))
        page = matched[offset : offset + limit]
        return CandidateList(
            items=[self._row(r, published=on_graph, decisions=decisions) for r in page],
            next_cursor=str(offset + limit) if offset + limit < len(matched) else None,
            counts=counts,
            as_of=utc_iso(self._clock.now()),
        )

    def _find(self, candidate_id: str, *, fresh: bool = False) -> dict[str, Any]:
        for raw in self.inspect(fresh=fresh).get("candidates") or []:
            if raw["candidate"]["candidate_id"] == candidate_id:
                return raw
        raise ApiError(404, "candidate_not_found", "후보를 찾을 수 없습니다.")

    def candidate(self, candidate_id: str) -> CandidateDetail:
        raw = self._find(candidate_id)
        effective_payload = self.effective_payload()
        on_graph = published_candidate_ids(effective_payload)
        on_graph_relations = published_relation_ids(effective_payload)
        decisions = {d.target_id: d for d in self._reviews.effective() if d.target_type == "candidate"}
        base = self._row(raw, published=on_graph, decisions=decisions)
        cand = raw["candidate"]
        mention = cand["mention"]
        validation = raw.get("validation") or {}
        trace = validation.get("trace") or {}
        articles = {a["article_id"]: a for a in cand.get("articles") or []}
        relation_decisions = {d.target_id: d for d in self._reviews.effective() if d.target_type == "relation"}
        policy_meta = self._ledger.policy()
        decision_policy = (
            _camel_policy((policy_meta.get("metadata") or {}).get("decision_policy"))
            if policy_meta.get("version") == cand.get("policy_version")
            else None
        )
        relation_ids = [r["relation_id"] for r in cand.get("relations") or []]
        history = sorted(
            [*self._reviews.history("candidate", candidate_id), *(h for rid in relation_ids for h in self._reviews.history("relation", rid))],
            key=lambda d: -d.id,
        )
        return CandidateDetail(
            **base.model_dump(),
            mention=CandidateMention(
                mention_id=mention.get("mention_id") or "",
                title=mention.get("title") or "",
                action=mention.get("action") or "",
                target=mention.get("target"),
                event_time=mention.get("event_time"),
                period=mention.get("period"),
                assertion_status=mention.get("assertion_status"),
                background=bool(mention.get("background")),
                countries=list(mention.get("countries") or []),
                keywords=list(mention.get("keywords") or []),
                participants=_companies(mention),
            ),
            articles=[
                CandidateArticle(
                    article_id=a["article_id"],
                    title=a.get("title"),
                    publisher=a.get("publisher"),
                    url=a.get("url"),
                    published_at=a.get("published_at"),
                    synthetic=a.get("synthetic") is not False,
                )
                for a in articles.values()
            ],
            evidence=[
                CandidateEvidence(
                    article_id=e["article_id"],
                    article_version=e.get("article_version") or "",
                    start=int(e["start"]),
                    end=int(e["end"]),
                    quote=e.get("quote") or "",
                    article_title=articles.get(e["article_id"], {}).get("title"),
                    url=articles.get(e["article_id"], {}).get("url"),
                )
                for e in mention.get("evidence") or []
            ],
            relations=[
                CandidateRelation(
                    relation_id=r["relation_id"],
                    relation_type=r.get("relation_type") or "",
                    source=r.get("source") or "",
                    target=r.get("target") or "",
                    role=r.get("role"),
                    assertion_status=r.get("assertion_status"),
                    evidence_count=len(r.get("evidence") or []),
                    on_user_graph=r["relation_id"] in on_graph_relations,
                    decision=decision_out(relation_decisions[r["relation_id"]]) if r["relation_id"] in relation_decisions else None,
                )
                for r in cand.get("relations") or []
            ],
            verification=VerificationOut(
                provider=trace.get("provider"),
                model=trace.get("model"),
                verifier_version=validation.get("verifier_version"),
                decision_policy=decision_policy,
                verdicts=[
                    VerdictOut(target=v.get("target") or "", decision=v.get("decision") or "", reason=v.get("reason") or "")
                    for v in validation.get("verdicts") or []
                ],
                field_verdicts=[
                    FieldVerdictOut(field=v.get("field") or "", decision=v.get("decision") or "", reason=v.get("reason") or "")
                    for v in validation.get("field_verdicts") or []
                ],
                observations=[
                    ObservationOut(
                        target=o.get("target") or "",
                        check=o.get("check") or "",
                        choice=o.get("choice") or "",
                        confidence=o.get("confidence"),
                        probabilities={str(k): float(v) for k, v in (o.get("probabilities") or {}).items()},
                    )
                    for o in trace.get("observations") or []
                ],
            ),
            invalidation_reason=raw.get("invalidation_reason"),
            history=[decision_out(h) for h in history],
        )

    # ---- decisions
    def decide(self, candidate_id: str, body: DecisionRequest, admin: Actor) -> DecisionResponse:
        raw = self._find(candidate_id, fresh=True)
        cand = raw["candidate"]
        relation: dict[str, Any] | None = None
        if body.relation_id:
            relation = next((r for r in cand.get("relations") or [] if r["relation_id"] == body.relation_id), None)
            if relation is None:
                raise ApiError(422, "unknown_relation", "이 후보에 없는 관계입니다.", {"relationId": body.relation_id})
            target_type, target_id = "relation", body.relation_id
        else:
            target_type, target_id = "candidate", candidate_id

        current = self._reviews.current(target_type, target_id)
        if current is not None and current.decision == body.decision:
            return self._decision_response(current, idempotent=True)

        if raw["status"] == "REJECT":
            raise ApiError(409, "status_not_reviewable", "PoC가 거부(REJECT)한 후보는 검수 대상이 아닙니다.", {"status": raw["status"]})
        if not raw.get("active"):
            raise ApiError(409, "candidate_inactive", "비활성 후보(정책 변경·기사 철회 등)는 검수할 수 없습니다.", {"invalidationReason": raw.get("invalidation_reason")})

        payload: dict[str, Any] | None = None
        if body.decision == "allow":
            if relation is None:
                if not has_quote(raw):
                    raise ApiError(422, "evidence_required", "원문 인용 근거가 없어 허용할 수 없습니다.")
                payload = {"candidate": cand, "validation": raw.get("validation"), "status": raw["status"], "active": True}
            else:
                if not relation.get("evidence"):
                    raise ApiError(422, "evidence_required", "원문 인용 근거가 없어 허용할 수 없습니다.", {"relationId": body.relation_id})
                if cand["issue_id"] not in {i["issue_id"] for i in self.effective_payload().get("issues") or []}:
                    raise ApiError(409, "issue_not_published", "출발 이슈가 사용자 그래프에 없어 관계만 허용할 수 없습니다.", {"issueId": cand["issue_id"]})
                payload = {"relation": relation, "issue_id": cand["issue_id"]}

        decision, idempotent = self._reviews.record(
            target_type,  # type: ignore[arg-type]
            target_id,
            body.decision,
            body.reason,
            admin_id=admin.id,
            admin_email=admin.email or admin.id,
            payload=payload,
        )
        if not idempotent:
            self._audit.record(
                admin,
                "review.decide",
                f"review-{target_type}",
                target_id,
                reason=body.reason,
                detail={
                    "decision": body.decision,
                    "candidateId": candidate_id,
                    "status": raw["status"],
                    "revision": decision.id,
                    "previous": current.decision if current else None,
                },
            )
        return self._decision_response(decision, idempotent=idempotent)

    def _decision_response(self, decision: Decision, *, idempotent: bool) -> DecisionResponse:
        effective = self.effective_payload()
        if decision.target_type == "candidate":
            on_graph = decision.target_id in published_candidate_ids(effective)
        else:
            on_graph = decision.target_id in published_relation_ids(effective)
        active = self._graphs.active()
        return DecisionResponse(
            decision=decision_out(decision),
            idempotent=idempotent,
            on_user_graph=on_graph,
            graph_version=active.id if active else "",
            review_revision=self._reviews.revision(),
        )

    # ---- publication
    def publish(self, admin: Actor, reason: str) -> tuple[GraphVersion, str | None]:
        payload = self.inspect(fresh=True)
        outbox = self._ledger.projection()
        policy = self._ledger.policy()
        pending = int(outbox["pending"])
        graph_db = {
            "status": "pending" if pending else "reflected",
            "pendingJobsAtCreation": pending,
            "note": "게시 시점 PoC outbox 미완료 투영 작업 수 기준" if pending else "게시 시점 PoC outbox에 미완료 투영 작업 없음",
        }
        version, previous = self._graphs.publish(
            payload,
            admin=admin,
            reason=reason,
            source_label=f"ledger:{self.database}",
            policy_version=policy.get("version"),
            graph_db=graph_db,
        )
        self._audit.record(
            admin,
            "graph.publish",
            "graph-version",
            version.id,
            reason=reason,
            detail={
                "previousActiveVersionId": previous,
                "issueCount": version.issue_count,
                "relationCount": version.relation_count,
                "sha256": version.sha256[:16],
            },
        )
        return version, previous


def _digest(payload: dict[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(canonical(payload)).hexdigest()


def _camel_policy(raw: Mapping[str, Any] | None) -> dict[str, float] | None:
    if not raw:
        return None
    return {
        "supportMin": float(raw["support_min"]),
        "contradictionMax": float(raw["contradiction_max"]),
        "rejectMin": float(raw["reject_min"]),
    }
