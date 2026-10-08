"""AI usage, errors and cost (requirement 77).

Chatbot and briefing are rule based today: their requests, failures and latencies are measured here
(``ai_events``) while model calls stay 0. News analysis is the PoC: runs are read from the ledger
(``investmate.runs``) and, when the ledger cannot be read, from the documented figures in
``docs/evidence/poc-backend.md`` sections 8 and 9.2. No unit price is ever invented: the PoC's
``estimated_cost`` is null, so cost is reported as unavailable.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Literal

from .admin_ledger import Ledger
from .admin_schemas import (
    AiFeature,
    AiUsageResponse,
    FeatureCost,
    FeatureUsage,
    LatencyOut,
    PastRun,
    RecentError,
    UsageOut,
)
from .audit import Clock
from .errors import ApiError
from .statedb import StateDb, utc_iso

Window = Literal["24h", "7d", "30d", "all"]
PAID_JOB_KINDS = frozenset({"retry-model-errors", "ingest-run"})  # job kinds that spend model calls
_WINDOWS: dict[str, timedelta | None] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "all": None,
}
NO_COST_REASON = "PoC가 보고한 estimated_cost가 없고 단가 기준도 정해지지 않아 실제·추정 비용을 제공하지 않습니다."
RULE_BASED_COST_REASON = "모델 호출이 없는 규칙 기반 기능이라 비용이 발생하지 않습니다(호출 0회)."

# docs/evidence/poc-backend.md section 8 (strict, web verification) and 9.2 (relaxed, no web). Totals only:
# the document does not break the token figures down per run.
_DOCUMENT_RUNS: tuple[PastRun, ...] = (
    PastRun(
        run_id=None,
        label="엄격 정책(웹 검증) 3회 합계",
        policy_group="strict-web",
        source="document",
        processed=65,
        approved=1,
        held=64,
        rejected=0,
        pending=None,
        error_count=None,
        usage=UsageOut(calls=600, replay_calls=0, input_tokens=7_896_703, output_tokens=577_694, elapsed_seconds=5342.65, estimated_cost=None),
    ),
    PastRun(
        run_id=None,
        label="완화 정책(웹 검증 없음) 2회 합계",
        policy_group="relaxed-no-web",
        source="document",
        processed=None,
        approved=None,
        held=None,
        rejected=None,
        pending=None,
        error_count=None,
        usage=UsageOut(calls=400, replay_calls=0, input_tokens=2_714_408, output_tokens=508_128, elapsed_seconds=4014.63, estimated_cost=None),
    ),
)


def usage_from_report(raw: dict[str, Any] | None) -> UsageOut:
    raw = raw or {}
    cost = raw.get("estimated_cost")
    return UsageOut(
        calls=int(raw.get("calls") or 0),
        replay_calls=int(raw.get("replay_calls") or 0),
        input_tokens=int(raw.get("input_tokens") or 0),
        output_tokens=int(raw.get("output_tokens") or 0),
        elapsed_seconds=float(raw.get("elapsed_seconds") or 0.0),
        estimated_cost=float(cost) if isinstance(cost, (int, float)) else None,
    )


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * len(ordered) + 0.5)) - 1))
    return ordered[index]


def _latency(values: list[float]) -> LatencyOut | None:
    if not values:
        return None
    return LatencyOut(avg=sum(values) / len(values), p95=_percentile(values, 0.95), max=max(values))


class UsageService:
    def __init__(self, db: StateDb, clock: Clock, ledger: Ledger):
        self._db = db
        self._clock = clock
        self._ledger = ledger
        self.briefing_views = 0  # user reads of GET /api/briefings since this process started

    # ---- recording (chatbot, briefing)
    def record(
        self,
        feature: Literal["chatbot", "briefing", "document-sentiment", "briefing-outlook"],
        ok: bool,
        duration_ms: float,
        *,
        code: str | None = None,
        message: str | None = None,
        model_calls: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> int:
        cursor = self._db.execute(
            "INSERT INTO ai_events(at,feature,ok,duration_ms,code,message,model_calls,input_tokens,output_tokens) VALUES (?,?,?,?,?,?,?,?,?)",
            (utc_iso(self._clock.now()), feature, int(ok), duration_ms, code, (message or "")[:300] or None,
             model_calls, input_tokens, output_tokens),
        )
        return int(cursor.lastrowid)

    @contextmanager
    def measure(self, feature: Literal["chatbot", "briefing"]) -> Iterator[None]:
        """Times the block. A 4xx ``ApiError`` (bad input, wrong owner) is not an AI request and is not
        counted; a 5xx ``ApiError`` or any other exception counts as a failed request."""
        started = time.perf_counter()
        try:
            yield
        except ApiError as exc:
            if exc.status >= 500:
                self.record(feature, False, (time.perf_counter() - started) * 1000, code=exc.code, message=exc.message)
            raise
        except Exception as exc:
            self.record(feature, False, (time.perf_counter() - started) * 1000, code=type(exc).__name__, message=str(exc))
            raise
        else:
            self.record(feature, True, (time.perf_counter() - started) * 1000)

    # ---- reading
    def _events(self, feature: str, since: datetime | None) -> list[Any]:
        if since is None:
            return self._db.query("SELECT * FROM ai_events WHERE feature=? ORDER BY id", (feature,))
        return self._db.query("SELECT * FROM ai_events WHERE feature=? AND at>=? ORDER BY id", (feature, utc_iso(since)))

    def _rule_feature(
        self, feature: Literal["chatbot", "briefing"], label: str, engine: str, note: str, since: datetime | None
    ) -> AiFeature:
        rows = self._events(feature, since)
        failed = [r for r in rows if not r["ok"]]
        return AiFeature(
            feature=feature,
            label=label,
            engine=engine,
            model_backed=False,
            requests=len(rows),
            succeeded=len(rows) - len(failed),
            failed=len(failed),
            latency_ms=_latency([float(r["duration_ms"]) for r in rows]),
            usage=FeatureUsage(model_calls=0, input_tokens=0, output_tokens=0),
            cost=FeatureCost(status="unavailable", actual=None, estimated=None, currency=None, reason=RULE_BASED_COST_REASON),
            source="measured",
            recent_errors=[RecentError(at=r["at"], code=r["code"], message=r["message"]) for r in reversed(failed[-5:])],
            note=note,
        )

    def _sentiment_feature(self, feature: Literal["document-sentiment", "briefing-outlook", "document-summary", "semantic-verification"], label: str, since: datetime | None) -> AiFeature:
        rows = self._events(feature, since)
        failed = [r for r in rows if not r["ok"]]
        replay = retries = 0
        for row in rows:
            attempt = self._db.one("SELECT replay,retry FROM sentiment_attempts WHERE event_id=?", (row["id"],))
            if attempt:
                replay += int(attempt["replay"])
                retries += int(attempt["retry"])
        worker = self._db.query("SELECT payload FROM document_analysis_calls WHERE stage=? ORDER BY at,attempt_id", (feature,))
        calls = [json.loads(r["payload"]) for r in worker]
        if since:
            calls = [c for c in calls if datetime.fromisoformat(c["startedAt"]) >= since]
        worker_failed = [c for c in calls if c["state"] != "validated"]
        def tokens(key: str, column: str) -> int | None:
            reported = [(c.get("usage") or {}).get(key) for c in calls]
            return None if any(v is None for v in reported) else sum(reported) + sum(int(r[column]) for r in rows)
        return AiFeature(
            feature=feature, label=label, engine="S1 문서·기존 회차 판정 worker · 명시적 실행", model_backed=True,
            requests=len(rows) + len(calls), succeeded=len(rows) - len(failed) + len(calls) - len(worker_failed),
            failed=len(failed) + len(worker_failed),
            latency_ms=_latency([float(r["duration_ms"]) for r in rows] + [c["durationMs"] for c in calls if c["durationMs"] is not None]),
            usage=FeatureUsage(model_calls=sum(int(r["model_calls"]) for r in rows) + sum(c["mode"] == "live" for c in calls),
                               input_tokens=tokens("inputTokens", "input_tokens"), output_tokens=tokens("outputTokens", "output_tokens"),
                               replay_calls=replay + sum(c["mode"] == "replay" for c in calls), retries=retries),
            cost=FeatureCost(status="unavailable", actual=None, estimated=None, currency=None,
                             reason="모델 단가·금액 예산은 미정입니다. 미보고 토큰과 비용은 null, 합성 재생은 유료 호출과 분리합니다."),
            source="measured",
            recent_errors=([RecentError(at=r["at"], code=r["code"], message=r["message"]) for r in reversed(failed[-5:])] +
                           [RecentError(at=c["startedAt"], code=c["error"], message=c["error"]) for c in reversed(worker_failed[-5:])])[-5:],
            note="조회와 동일 영수증 재수입은 시도를 추가하지 않습니다. 문서 생성·별도 의미 검증과 기존 회차 exact 정책을 구분합니다. 회사·시장 요약은 S5 계획입니다.",
        )

    def past_runs(self, admin_job_runs: list[PastRun]) -> list[PastRun]:
        """Ledger runs (``investmate.runs``); the documented totals when the ledger cannot be read."""
        job_run_ids = {r.run_id for r in admin_job_runs if r.run_id}
        try:
            reports = self._ledger.run_reports()
        except ApiError:
            return [*_DOCUMENT_RUNS, *admin_job_runs]
        rows: list[PastRun] = []
        for entry in reports:
            report = entry["report"] or {}
            run_id = entry["run_id"]
            if run_id in job_run_ids:
                group: Literal["strict-web", "relaxed-no-web", "admin-job"] = "admin-job"
                title = "관리자 작업 재처리"
            elif report.get("web_policy_fingerprint"):
                group, title = "strict-web", "엄격 정책(웹 검증)"
            else:
                group, title = "relaxed-no-web", "완화 정책(웹 검증 없음)"
            rows.append(
                PastRun(
                    run_id=run_id,
                    label=f"{title} · {run_id[:8]}",
                    policy_group=group,
                    source="ledger-db",
                    processed=int(report.get("processed") or 0),
                    approved=int(report.get("approved") or 0),
                    held=int(report.get("held") or 0),
                    rejected=int(report.get("rejected") or 0),
                    pending=int(report.get("pending") or 0),
                    error_count=len(report.get("errors") or []),
                    usage=usage_from_report({**(report.get("usage") or {}), "elapsed_seconds": (report.get("usage") or {}).get("elapsed_seconds", report.get("elapsed_seconds"))}),
                )
            )
        known = {r.run_id for r in rows}
        rows += [r for r in admin_job_runs if r.run_id not in known]  # reported by a job, not (yet) in the ledger
        order = {"strict-web": 0, "relaxed-no-web": 1, "admin-job": 2}
        rows.sort(key=lambda r: order[r.policy_group])  # stable: keeps the ledger's insertion order
        return rows

    def response(self, window: Window, jobs: list[Any]) -> AiUsageResponse:
        """``jobs``: finished paid jobs as ``(job_dict, started_iso)``-style dicts from the job runner."""
        span = _WINDOWS.get(window)
        now = self._clock.now()
        since = now - span if span else None
        job_runs = [self._job_run(j) for j in jobs if j.get("report")]
        runs = self.past_runs([r for r in job_runs if r is not None])

        in_window = [
            j
            for j in jobs
            if j["kind"] in PAID_JOB_KINDS
            and j["status"] in ("succeeded", "failed")
            and (since is None or (j.get("finishedAt") and j["finishedAt"] >= utc_iso(since)))
        ]
        calls = sum(int(((j.get("report") or {}).get("usage") or {}).get("calls") or 0) for j in in_window)
        input_tokens = sum(int(((j.get("report") or {}).get("usage") or {}).get("inputTokens") or 0) for j in in_window)
        output_tokens = sum(int(((j.get("report") or {}).get("usage") or {}).get("outputTokens") or 0) for j in in_window)
        failures = [j for j in in_window if j["status"] == "failed"]
        latencies = [float(j["durationSeconds"]) * 1000 for j in in_window if j.get("durationSeconds") is not None]
        news_source: Literal["measured", "job-runner", "ledger-db", "document"] = "job-runner"
        requests, succeeded, failed = len(in_window), len(in_window) - len(failures), len(failures)
        note = (
            f"창 안의 관리자 재처리 작업 {requests}건 합계입니다. 과거 실행은 기간 없이 pastRuns({len(runs)}건)에 따로 표시합니다."
        )
        if window == "all":
            # Ledger runs have no timestamp, so only the "all" window can include them. Admin-job runs are
            # already in the ledger (the CLI saves its report), hence counted once.
            base = [r for r in runs if r.source != "job-runner"]
            news_source = "ledger-db" if any(r.source == "ledger-db" for r in base) else "document"
            extra = [r for r in runs if r.source == "job-runner"]
            every = [*base, *extra]
            requests = len(every)
            failed = sum(1 for r in every if (r.error_count or 0) > 0)
            succeeded = requests - failed
            calls = sum(r.usage.calls for r in every)
            input_tokens = sum(r.usage.input_tokens for r in every)
            output_tokens = sum(r.usage.output_tokens for r in every)
            latencies = [r.usage.elapsed_seconds * 1000 for r in every if r.usage.elapsed_seconds]
            note = (
                "원장 investmate.runs의 실행 보고서 전체입니다(오류가 1건 이상 남은 실행을 실패로 셈)."
                if news_source == "ledger-db"
                else "원장을 읽지 못해 docs/evidence/poc-backend.md §8·§9.2의 기록 값입니다(합계만 제공)."
            )
        costs = [r.usage.estimated_cost for r in runs]
        known = [c for c in costs if c is not None]
        cost = (
            FeatureCost(status="estimated", actual=None, estimated=sum(known), currency=None, reason="PoC가 보고한 estimated_cost 합계입니다.")
            if known
            else FeatureCost(status="unavailable", actual=None, estimated=None, currency=None, reason=NO_COST_REASON)
        )
        recent = [
            RecentError(at=j["finishedAt"], code=(j.get("error") or {}).get("code"), message=(j.get("error") or {}).get("message"))
            for j in reversed(failures[-5:])
        ]
        news = AiFeature(
            feature="news-analysis",
            label="뉴스 분석(PoC 파이프라인)",
            engine="InvestMate PoC · 모델 호출(유료)",
            model_backed=True,
            requests=requests,
            succeeded=succeeded,
            failed=failed,
            latency_ms=_latency(latencies),
            usage=FeatureUsage(model_calls=calls, input_tokens=input_tokens, output_tokens=output_tokens),
            cost=cost,
            source=news_source,
            recent_errors=recent,
            note=note,
        )
        briefing = self._rule_feature(
            "briefing",
            "출퇴근 브리핑",
            "BFF 규칙 기반 선정 · 모델 호출 없음",
            f"회차 생성 시도(스케줄러·수동 재처리)를 실측합니다. 사용자 조회는 BFF 기동 이후 {self.briefing_views}회.",
            since,
        )
        chatbot = self._rule_feature(
            "chatbot",
            "AI 챗봇",
            "BFF 규칙 기반 답변 · 모델 호출 없음",
            "현재 챗봇은 승인 근거를 규칙으로 조합하며 모델을 호출하지 않습니다. 질문 작업의 실행마다 한 번 세며, 되묻기·조건 안내·근거 부족 응답도 처리 완료로 셉니다. 검증 실패·저장 실패·일시 장애는 실패로 셉니다.",
            since,
        )
        return AiUsageResponse(
            as_of=utc_iso(now),
            window=window,
            features=[chatbot, news, briefing,
                      self._sentiment_feature("document-sentiment", "기업별 문서 판정", since),
                      self._sentiment_feature("briefing-outlook", "브리핑 회차 판정", since),
                      self._sentiment_feature("document-summary", "문서 요약", since),
                      self._sentiment_feature("semantic-verification", "문서 의미 검증", since)],
            past_runs=runs,
            cost=cost,
        )

    @staticmethod
    def _job_run(job: dict[str, Any]) -> PastRun | None:
        report = job.get("report")
        if not report:
            return None
        usage = report.get("usage") or {}
        return PastRun(
            run_id=report.get("runId"),
            label=f"관리자 작업 {job['id']}",
            policy_group="admin-job",
            source="job-runner",
            processed=report.get("processed"),
            approved=report.get("approved"),
            held=report.get("held"),
            rejected=report.get("rejected"),
            pending=report.get("pending"),
            error_count=report.get("errorCount"),
            usage=UsageOut(
                calls=int(usage.get("calls") or 0),
                replay_calls=int(usage.get("replayCalls") or 0),
                input_tokens=int(usage.get("inputTokens") or 0),
                output_tokens=int(usage.get("outputTokens") or 0),
                elapsed_seconds=float(usage.get("elapsedSeconds") or 0.0),
                estimated_cost=usage.get("estimatedCost"),
            ),
        )

    def summary(self, window: Window = "7d") -> dict[str, Any]:
        """Dashboard numbers for the rule-based features only (news analysis comes from the job runner)."""
        span = _WINDOWS[window]
        since = self._clock.now() - span if span else None
        out: dict[str, dict[str, int]] = {}
        for feature in ("chatbot", "briefing"):
            rows = self._events(feature, since)
            out[feature] = {"requests": len(rows), "failed": sum(1 for r in rows if not r["ok"])}
        return out
