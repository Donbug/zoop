"""Usage statistics for the admin panel (requirement 74).

Everything is computed on read from three server-side sources: the client events (``telemetry_events``), the
chat records (AI questions) and the member records (onboarding, watch lists, virtual holdings). A ratio is
only given when its denominator reaches ``MIN_SAMPLE``; below that the counts stand alone. The windows are
KST calendar days. No figure here carries a real name, an e-mail address or an IP address.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any

from .accounts import UserState
from .audit import Clock
from .briefing_rounds import parse_round_id
from .dataset import Dataset
from .errors import ApiError
from .feedback import FeedbackService
from .insights_common import MIN_SAMPLE, SubjectKeys, day_range, kst_day, ratio, since_iso
from .insights_schemas import (
    InsightCompanyDetail,
    InsightCompanyRanking,
    CompanySeriesPoint,
    CompanyStatRow,
    DailyActivity,
    InsightsOverview,
    OverviewFeedback,
    OverviewMembers,
    RoundStat,
    StatsMetric,
    StatsSummary,
)
from .statedb import StateDb, utc_iso

Key = tuple[str, str]  # (subject kind, subject id)
HOLDINGS_NOTE = "관심 등록과 가상 보유는 지금 저장된 회원 설정을 센 값이라 기간과 무관하고, 추이 기록은 없어요."
RANKING_LIMIT = 100


def _count(key: str, group: str, label: str, unit: str, definition: str, n: int) -> StatsMetric:
    return StatsMetric(
        key=key, group=group, label=label, kind="count", unit=unit, definition=definition,  # type: ignore[arg-type]
        count=n, numerator=None, denominator=None, rate=None, sample_hidden=False,
    )


def _ratio(key: str, group: str, label: str, unit: str, definition: str, numerator: int, denominator: int) -> StatsMetric:
    return StatsMetric(
        key=key, group=group, label=label, kind="ratio", unit=unit, definition=definition,  # type: ignore[arg-type]
        count=None, numerator=numerator, denominator=denominator, rate=ratio(numerator, denominator),
        sample_hidden=denominator < MIN_SAMPLE,
    )


class StatsService:
    def __init__(self, db: StateDb, clock: Clock, keys: SubjectKeys, feedback: FeedbackService):
        self._db = db
        self._clock = clock
        self._keys = keys
        self._feedback = feedback

    # ---- sources
    def _events(self, since: str | None) -> list[Any]:
        return self._db.query(
            "SELECT at, subject, subject_kind, type, screen, target_id, target_kind, round_id, view_id, company_ids"
            " FROM telemetry_events" + (" WHERE at >= ?" if since else "") + " ORDER BY id",
            (since,) if since else (),
        )

    def _chats(self, since: str | None) -> list[Any]:
        return self._db.query(
            "SELECT m.at AS at, m.company_ids AS company_ids, s.owner_id AS owner_id, s.owner_kind AS owner_kind"
            " FROM chat_messages m JOIN chat_sessions s ON s.id = m.session_id"
            + (" WHERE m.at >= ?" if since else "")
            + " ORDER BY m.at",
            (since,) if since else (),
        )

    def _votes(self, since: str | None) -> list[Any]:
        return self._db.query(
            "SELECT subject, subject_kind, updated_at AS at FROM feedback" + (" WHERE updated_at >= ?" if since else ""),
            (since,) if since else (),
        )

    def _chat_key(self, row: Any) -> Key:
        subject = self._keys.subject(row["owner_kind"], row["owner_id"])
        return subject.kind, subject.id

    # ---- summary
    def summary(self, window: str, members: Sequence[UserState]) -> StatsSummary:
        since = since_iso(window, self._clock)
        events, chats, votes = self._events(since), self._chats(since), self._votes(since)
        chat_keys = [self._chat_key(c) for c in chats]

        active: set[Key] = {(e["subject_kind"], e["subject"]) for e in events}
        active |= set(chat_keys)
        active |= {(v["subject_kind"], v["subject"]) for v in votes}
        active_members = sum(1 for kind, _ in active if kind == "member")

        main_views = {e["view_id"] for e in events if e["type"] == "screen_view" and e["screen"] == "main"}
        node_events = [e for e in events if e["type"] == "graph_node_select"]
        edge_events = [e for e in events if e["type"] == "graph_edge_select"]
        node_views_hit = {e["view_id"] for e in node_events if e["view_id"]} & main_views
        edge_views_hit = {e["view_id"] for e in edge_events if e["view_id"]} & main_views

        briefing_events = [e for e in events if e["type"] == "briefing_view"]
        briefing_viewers = {(e["subject_kind"], e["subject"]) for e in briefing_events}
        briefing_view_ids = {e["view_id"] for e in briefing_events if e["view_id"]}
        opens = [e for e in events if e["type"] == "briefing_issue_open"]
        opens_hit = {e["view_id"] for e in opens if e["view_id"]} & briefing_view_ids
        likes, dislikes = self._feedback.totals(window, ("briefing_round", "briefing_issue"))

        cohort = [m for m in members if since is None or m.created_at >= since]
        onboarded = sum(1 for m in cohort if m.completed)

        metrics = [
            _count("active_users", "usage", "활성 사용자", "명",
                   "기간 안에 화면을 열었거나 AI에 질문했거나 평가를 남긴 사용자 수(회원 1명·비회원 세션 1개를 각각 1명으로 셉니다).", len(active)),
            _count("active_members", "usage", "활성 회원", "명", "활성 사용자 중 로그인한 회원.", active_members),
            _count("active_guests", "usage", "활성 비회원", "명", "활성 사용자 중 비회원 세션.", len(active) - active_members),
            _ratio("onboarding_completion", "usage", "온보딩 완료율", "명",
                   "기간 안에 가입한 회원 중 초기 설정을 마친 회원의 비율(서버에 저장된 회원 설정 기준).", onboarded, len(cohort)),
            _count("main_exposures", "usage", "메인 노출", "회", "메인 화면이 열린 횟수.", len(main_views)),
            _ratio("node_click", "usage", "노드 클릭률", "노출",
                   "메인 노출 중 기업·사건 노드를 한 번이라도 선택한 노출의 비율.", len(node_views_hit), len(main_views)),
            _count("node_selections", "usage", "노드 선택", "회", "기업·사건 노드를 선택한 총 횟수.", len(node_events)),
            _ratio("edge_click", "usage", "간선 클릭률", "노출",
                   "메인 노출 중 연결선을 한 번이라도 선택한 노출의 비율.", len(edge_views_hit), len(main_views)),
            _count("edge_selections", "usage", "간선 선택", "회", "연결선을 선택한 총 횟수.", len(edge_events)),
            _ratio("briefing_view_rate", "interest", "브리핑 조회율", "명",
                   "활성 사용자 중 브리핑 회차를 한 번이라도 연 사용자의 비율.", len(briefing_viewers), len(active)),
            _count("briefing_views", "interest", "브리핑 조회", "회", "브리핑 회차를 연 총 횟수.", len(briefing_events)),
            _ratio("issue_open_rate", "interest", "이슈 열기율", "조회",
                   "브리핑 조회 중 핵심 이슈를 한 번이라도 연 조회의 비율.", len(opens_hit), len(briefing_view_ids)),
            _count("issue_opens", "interest", "이슈 열기", "회", "브리핑에서 핵심 이슈를 연 총 횟수.", len(opens)),
            _ratio("briefing_like_rate", "interest", "브리핑 좋아요 비율", "표",
                   "브리핑 회차와 핵심 이슈에 남긴 표 중 좋아요의 비율.", likes, likes + dislikes),
            _ratio("ai_usage_rate", "ai", "AI 질문 이용률", "명",
                   "활성 사용자 중 AI에 질문을 한 번이라도 한 사용자의 비율(서버의 대화 기록 기준).", len(set(chat_keys)), len(active)),
            _count("ai_questions", "ai", "AI 질문", "회", "AI에 보낸 질문의 총 횟수.", len(chats)),
        ]

        first = min((r["at"] for r in (*events, *chats, *votes)), default=None)
        days = day_range(window, self._clock, first)
        trend = self._trend(days, events, chats, votes)
        return StatsSummary(
            window=window,  # type: ignore[arg-type]
            as_of=utc_iso(self._clock.now()),
            since=since,
            min_sample=MIN_SAMPLE,
            members_scope="가입일이 기간 안에 있는 회원" if since else "전체 회원",
            metrics=metrics,
            trend=trend,
            rounds=self._rounds(briefing_events, opens, since),
        )

    def _trend(self, days: list[str], events: list[Any], chats: list[Any], votes: list[Any]) -> list[DailyActivity]:
        active: dict[str, set[Key]] = defaultdict(set)
        counts: dict[str, Counter[str]] = defaultdict(Counter)
        for e in events:
            day = kst_day(e["at"])
            active[day].add((e["subject_kind"], e["subject"]))
            counts[day][e["type"]] += 1
        for c in chats:
            day = kst_day(c["at"])
            active[day].add(self._chat_key(c))
            counts[day]["ai_question"] += 1
        for v in votes:
            active[kst_day(v["at"])].add((v["subject_kind"], v["subject"]))
        return [
            DailyActivity(
                date=day,
                active_users=len(active[day]),
                node_selections=counts[day]["graph_node_select"],
                edge_selections=counts[day]["graph_edge_select"],
                briefing_views=counts[day]["briefing_view"],
                ai_questions=counts[day]["ai_question"],
            )
            for day in days
        ]

    def _rounds(self, views: list[Any], opens: list[Any], since: str | None) -> list[RoundStat]:
        viewers: dict[str, set[Key]] = defaultdict(set)
        view_counts: Counter[str] = Counter()
        for e in views:
            if e["round_id"]:
                view_counts[e["round_id"]] += 1
                viewers[e["round_id"]].add((e["subject_kind"], e["subject"]))
        open_counts = Counter(e["round_id"] for e in opens if e["round_id"])
        votes = self._feedback.round_votes(since)
        stats = []
        for round_id in sorted(set(view_counts) | set(open_counts) | set(votes), reverse=True):
            parsed = parse_round_id(round_id)
            if parsed is None:
                continue
            up, down = votes.get(round_id, (0, 0))
            stats.append(
                RoundStat(
                    round_id=round_id,
                    date=parsed[0].isoformat(),
                    edition=parsed[1],
                    views=view_counts[round_id],
                    viewers=len(viewers[round_id]),
                    issue_opens=open_counts[round_id],
                    likes=up,
                    dislikes=down,
                )
            )
        return stats

    # ---- companies
    @staticmethod
    def _member_counts(members: Sequence[UserState]) -> tuple[Counter[str], Counter[str]]:
        watch: Counter[str] = Counter()
        held: Counter[str] = Counter()
        for m in members:
            watch.update(set(m.watchlist_ids))
            if m.connection:
                held.update({h.company_id for h in m.connection.holdings})
        return watch, held

    def _company_activity(self, since: str | None) -> tuple[list[Any], list[Any]]:
        events = [
            e
            for e in self._events(since)
            if e["type"] in ("graph_node_select", "graph_edge_select") and (e["target_kind"] == "company" or e["company_ids"] != "[]")
        ]
        return events, [c for c in self._chats(since) if c["company_ids"] != "[]"]

    def companies(self, window: str, members: Sequence[UserState], ds: Dataset) -> InsightCompanyRanking:
        since = since_iso(window, self._clock)
        events, chats = self._company_activity(since)
        watch, held = self._member_counts(members)
        node_views: Counter[str] = Counter()
        edge_sel: Counter[str] = Counter()
        ai: Counter[str] = Counter()
        for e in events:
            if e["type"] == "graph_node_select" and e["target_kind"] == "company":
                node_views[e["target_id"]] += 1
            elif e["type"] == "graph_edge_select":
                edge_sel.update(json.loads(e["company_ids"]))
        for c in chats:
            ai.update(set(json.loads(c["company_ids"])))
        ids = set(watch) | set(held) | set(node_views) | set(edge_sel) | set(ai)
        rows = [
            CompanyStatRow(
                company_id=cid,
                name=ds.companies[cid].name if cid in ds.companies else cid,
                ticker=ds.companies[cid].ticker if cid in ds.companies else None,
                watchlist_members=watch[cid],
                holding_members=held[cid],
                node_views=node_views[cid],
                edge_selections=edge_sel[cid],
                ai_questions=ai[cid],
            )
            for cid in ids
        ]
        rows.sort(key=lambda r: (-r.node_views, -r.watchlist_members, -r.holding_members, -r.edge_selections, r.name))
        return InsightCompanyRanking(
            window=window,  # type: ignore[arg-type]
            as_of=utc_iso(self._clock.now()),
            total_companies=len(ds.companies),
            items=rows[:RANKING_LIMIT],
            holdings_note=HOLDINGS_NOTE,
        )

    def company(self, window: str, company_id: str, members: Sequence[UserState], ds: Dataset) -> InsightCompanyDetail:
        since = since_iso(window, self._clock)
        events, chats = self._company_activity(since)
        watch, held = self._member_counts(members)
        known = company_id in ds.companies
        per_day: dict[str, Counter[str]] = defaultdict(Counter)
        viewers: set[Key] = set()
        times: list[str] = []
        for e in events:
            ids = json.loads(e["company_ids"])
            if e["type"] == "graph_node_select" and e["target_kind"] == "company" and e["target_id"] == company_id:
                metric = "node"
            elif e["type"] == "graph_edge_select" and company_id in ids:
                metric = "edge"
            elif e["type"] == "graph_node_select" and e["target_kind"] == "issue" and company_id in ids:
                metric = "issue"
            else:
                continue
            per_day[kst_day(e["at"])][metric] += 1
            viewers.add((e["subject_kind"], e["subject"]))
            times.append(e["at"])
        for c in chats:
            if company_id in json.loads(c["company_ids"]):
                per_day[kst_day(c["at"])]["ai"] += 1
                times.append(c["at"])
        if not known and not times and not watch[company_id] and not held[company_id]:
            raise ApiError(404, "company_not_found", "통계에 나타난 적 없는 기업입니다.")
        series = [
            CompanySeriesPoint(
                date=day,
                node_views=per_day[day]["node"],
                edge_selections=per_day[day]["edge"],
                issue_selections=per_day[day]["issue"],
                ai_questions=per_day[day]["ai"],
            )
            for day in day_range(window, self._clock, min(times, default=None))
        ]
        return InsightCompanyDetail(
            window=window,  # type: ignore[arg-type]
            as_of=utc_iso(self._clock.now()),
            company_id=company_id,
            name=ds.companies[company_id].name if known else company_id,
            ticker=ds.companies[company_id].ticker if known else None,
            in_catalog=known,
            watchlist_members=watch[company_id],
            holding_members=held[company_id],
            node_views=sum(p.node_views for p in series),
            edge_selections=sum(p.edge_selections for p in series),
            issue_selections=sum(p.issue_selections for p in series),
            ai_questions=sum(p.ai_questions for p in series),
            viewers=len(viewers),
            min_sample=MIN_SAMPLE,
            series=series,
            note=HOLDINGS_NOTE,
        )

    # ---- dashboard card
    def overview(self, members: Sequence[UserState]) -> InsightsOverview:
        summary = self.summary("7d", members)
        wanted = ("active_users", "node_click", "briefing_view_rate", "ai_usage_rate")
        likes, dislikes = self._feedback.totals("7d", ("chatbot_answer", "briefing_round", "briefing_issue"))
        blocked = sum(1 for m in members if m.status == "blocked")
        return InsightsOverview(
            window="7d",
            as_of=summary.as_of,
            min_sample=MIN_SAMPLE,
            metrics=[m for key in wanted for m in summary.metrics if m.key == key],
            feedback=OverviewFeedback(up=likes, down=dislikes, rate=ratio(likes, likes + dislikes), sample_hidden=likes + dislikes < MIN_SAMPLE),
            members=OverviewMembers(registered=len(members), active=len(members) - blocked, blocked=blocked),
        )
