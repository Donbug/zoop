// 대시보드(요구 81): 전체 상황 요약 + 각 관리 기능으로 바로 가기. 10초마다 갱신(탭이 안 보이면 멈춤).
import { ArrowRight, BarChart3, Database, EyeOff, GitBranch, LayoutDashboard, ListChecks, Newspaper, RefreshCw, ScrollText, Sparkles, ThumbsUp, Users, Workflow } from "lucide-react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { IconHint } from "@/components/ui/icon-hint";
import { useDashboard, useInsightsOverview } from "../api";
import { formatCount } from "../format";
import { formatPercent, MetricBasis, MetricValue } from "../insights-ui";
import { candidateStatusSpec, editionLabel, graphDbStatusSpec, jobKindLabel, jobStatusSpec, roundStatusSpec, Status } from "../labels";
import { AdminPageHeader, AdminSection, DataTable, KstTime, Metric, StatusLabel, Td, Th } from "../ui";

function SectionLink({ to, label }: { to: string; label: string }) {
  return (
    <Button variant="ghost" size="sm" asChild>
      <Link to={to}>
        {label}
        <ArrowRight aria-hidden="true" />
      </Link>
    </Button>
  );
}

/** 이용 통계·선호도·회원 요약(요구 74·75·78): 7일 기준 핵심 수치와 각 화면으로 가는 링크. */
function InsightsSection() {
  const overview = useInsightsOverview();
  const data = overview.data;
  const links = (
    <div className="flex items-center gap-1">
      <SectionLink to="/admin/stats" label="이용 통계" />
      <SectionLink to="/admin/feedback" label="선호도" />
      <SectionLink to="/admin/members" label="회원 관리" />
    </div>
  );
  return (
    <AdminSection title="이용·선호도(7일)" icon={BarChart3} id="dash-insights" actions={links}>
      {overview.isPending && <SkeletonRows count={1} label="이용 통계를 불러오고 있어요" />}
      {overview.isError && <ErrorState error={overview.error} title="이용 통계를 불러오지 못했어요" onRetry={() => void overview.refetch()} compact />}
      {data && (
        <dl className="grid grid-cols-6 gap-x-6 gap-y-4 py-2">
          {data.metrics.map((metric) => (
            <Metric
              key={metric.key}
              label={metric.label}
              value={<MetricValue metric={metric} />}
              detail={metric.kind === "ratio" ? <MetricBasis metric={metric} minSample={data.minSample} /> : undefined}
            />
          ))}
          <Metric
            icon={ThumbsUp}
            label="AI 좋아요 비율"
            value={
              data.feedback.rate == null ? (
                <StatusLabel icon={EyeOff} label="표본 부족" tone="warning" className="text-lg" />
              ) : (
                <span className="tabular-nums">{formatPercent(data.feedback.rate)}</span>
              )
            }
            detail={<span className="tabular-nums">좋아요 {formatCount(data.feedback.up)} · 싫어요 {formatCount(data.feedback.down)}</span>}
          />
          <Metric
            icon={Users}
            label="등록 회원"
            value={`${formatCount(data.members.registered)}명`}
            detail={<span className="tabular-nums">차단 {formatCount(data.members.blocked)}명</span>}
          />
        </dl>
      )}
    </AdminSection>
  );
}

export function AdminDashboardPage() {
  const dashboard = useDashboard();
  const data = dashboard.data;

  return (
    <>
      <AdminPageHeader
        title="대시보드"
        icon={LayoutDashboard}
        actions={
          data && (
            <p className="flex items-center gap-1 text-sm text-text-secondary">
              <RefreshCw className="size-4" aria-hidden="true" />
              <span>
                갱신 <KstTime value={data.generatedAt} seconds />
              </span>
              <IconHint icon={ScrollText} label="10초마다 자동 갱신">
                <p>이 탭이 보이지 않으면 갱신을 멈춰요.</p>
              </IconHint>
            </p>
          )
        }
      />
      {dashboard.isPending && <SkeletonRows count={4} label="대시보드를 불러오고 있어요" />}
      {dashboard.isError && <ErrorState error={dashboard.error} title="대시보드를 불러오지 못했어요" onRetry={() => void dashboard.refetch()} />}
      {data && (
        <>
          <dl className="grid grid-cols-5 gap-x-6 gap-y-4 border-y border-border-subtle py-4">
            <Metric
              icon={ListChecks}
              label="검수 대기"
              value={data.candidates ? `${formatCount(data.candidates.holdPendingReview)}건` : "–"}
              detail={
                data.candidates ? (
                  <span className="tabular-nums">
                    {candidateStatusSpec.ALLOW.label} {formatCount(data.candidates.allow)} · {candidateStatusSpec.HOLD.label} {formatCount(data.candidates.hold)} ·{" "}
                    {candidateStatusSpec.REJECT.label} {formatCount(data.candidates.reject)}
                  </span>
                ) : (
                  "원장에 연결하지 못했어요"
                )
              }
            />
            <Metric
              icon={GitBranch}
              label="사용자에게 보이는 그래프"
              value={data.graph.activeVersionId}
              detail={
                <span>
                  <KstTime value={data.graph.activatedAt} /> 게시 · 검수 {formatCount(data.graph.reviewDecisions)}건 반영
                  {data.graph.rules.map((rule) => (
                    <span key={rule.id} className="block">
                      자동 검수 규칙 {rule.id} {rule.enabled ? "켜짐" : "꺼짐"} · 게시 사건 {formatCount(rule.publishedEvents)}건
                    </span>
                  ))}
                </span>
              }
            />
            <Metric
              icon={Database}
              label="GraphDB 반영"
              value={<Status spec={data.graph.graphDb ? graphDbStatusSpec[data.graph.graphDb.status] : graphDbStatusSpec.unavailable} className="text-lg" />}
              detail={data.graph.graphDb?.pendingJobs != null ? `대기 작업 ${formatCount(data.graph.graphDb.pendingJobs)}건` : undefined}
            />
            <Metric
              icon={Workflow}
              label="작업"
              value={<span className="whitespace-nowrap">{`실행 ${formatCount(data.jobs.running)} · 대기 ${formatCount(data.jobs.queued)}`}</span>}
              detail={`24시간 실패 ${formatCount(data.jobs.failed24h)}건`}
            />
            <Metric
              icon={Sparkles}
              label="AI 요청(7일)"
              value={`${formatCount(data.ai.requests)}건`}
              detail={`성공 ${formatCount(data.ai.succeeded)} · 실패 ${formatCount(data.ai.failed)}`}
            />
          </dl>

          <div className="grid grid-cols-2 gap-8">
            <AdminSection title="최근 브리핑 회차" icon={Newspaper} id="dash-briefings" actions={<SectionLink to="/admin/briefings" label="브리핑 운영" />}>
              <DataTable caption="브리핑 회차 목록">
                <thead>
                  <tr>
                    <Th>회차</Th>
                    <Th>상태</Th>
                    <Th>데이터 기준 시점</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.briefings.latest.map((round) => (
                    <tr key={round.id}>
                      <Td className="whitespace-nowrap tabular-nums">
                        {round.date} {editionLabel[round.edition]}
                      </Td>
                      <Td>
                        <Status spec={roundStatusSpec[round.status]} />
                      </Td>
                      <Td>
                        <KstTime value={round.dataWindow.end} />
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
              {data.briefings.delayedOrFailed > 0 && (
                <p className="text-sm text-text-secondary">늦게 발행됐거나 실패한 회차가 {formatCount(data.briefings.delayedOrFailed)}건 있어요.</p>
              )}
            </AdminSection>

            <AdminSection title="최근 작업" icon={Workflow} id="dash-jobs" actions={<SectionLink to="/admin/pipeline#jobs" label="작업 관제" />}>
              {data.jobs.recent.length === 0 ? (
                <p className="py-4 text-base text-text-secondary">아직 실행한 작업이 없어요.</p>
              ) : (
                <DataTable caption="최근 작업 목록">
                  <thead>
                    <tr>
                      <Th>작업</Th>
                      <Th>상태</Th>
                      <Th>요청 시각</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.jobs.recent.map((job) => (
                      <tr key={job.id}>
                        <Td>{jobKindLabel[job.kind] ?? job.label}</Td>
                        <Td>
                          <Status spec={jobStatusSpec[job.status]} />
                        </Td>
                        <Td>
                          <KstTime value={job.requestedAt} />
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </DataTable>
              )}
            </AdminSection>
          </div>

          <div className="grid grid-cols-2 gap-8">
            <AdminSection title="AI 기능별 요청(7일)" icon={Sparkles} id="dash-ai" actions={<SectionLink to="/admin/ai" label="AI 운영" />}>
              <DataTable caption="AI 기능별 요청">
                <thead>
                  <tr>
                    <Th>기능</Th>
                    <Th className="text-right">요청</Th>
                    <Th className="text-right">실패</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.ai.features.map((feature) => (
                    <tr key={feature.feature}>
                      <Td>{feature.label}</Td>
                      <Td className="text-right">{formatCount(feature.requests)}</Td>
                      <Td className="text-right">{formatCount(feature.failed)}</Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            </AdminSection>
            <AdminSection title="이용 현황" icon={Users} id="dash-members" actions={<SectionLink to="/admin/audit" label="감사 로그" />}>
              <dl className="grid grid-cols-3 gap-6 py-2">
                <Metric label="등록 회원" value={formatCount(data.members.registered)} />
                <Metric label="회원 접속 세션" value={formatCount(data.members.activeMemberSessions)} detail={`비회원 ${formatCount(data.members.activeGuestSessions)}`} />
                <Metric label="감사 기록(24시간)" value={formatCount(data.audit.last24h)} />
              </dl>
            </AdminSection>
          </div>
          <InsightsSection />
        </>
      )}
    </>
  );
}
