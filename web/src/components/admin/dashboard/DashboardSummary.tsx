import { useState } from 'react';
import { getAdminDashboard } from '@/apis/admin/dashboard';
import {
  Empty,
  ErrorBox,
  Loading,
  Metric,
  PageHeader,
  Section,
  Table,
} from '@/components/admin/common/AdminUi';
import { BUTTON, TD, TH, count } from '@/components/admin/common/adminStyles';
import {
  editionLabel,
  graphDbStatusLabel,
  jobKindLabel,
  jobStatusLabel,
  roundStatusLabel,
} from '@/constants/adminLabels';
import { useAsyncData } from '@/hooks/useAsyncData';
import type { Dashboard } from '@/types/admin/dashboard';
import { formatKst } from '@/util/format';
import InsightsOverviewSection from './InsightsOverviewSection';

function Overview({ data }: { data: Dashboard }) {
  const { candidates, graph, jobs, ai } = data;
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-5 border-y-[0.667px] border-zoop-line py-5 md:grid-cols-5">
      <Metric
        label="검수 대기"
        value={candidates ? `${count(candidates.holdPendingReview)}건` : '–'}
        detail={
          candidates
            ? `통과 ${count(candidates.allow)} · 보류 ${count(candidates.hold)} · 폐기 ${count(candidates.reject)}`
            : '원장에 연결하지 못했어요'
        }
      />
      <Metric
        label="사용자에게 보이는 그래프"
        value={graph.activeVersionId ?? '–'}
        detail={
          graph.activeVersionId ? (
            <>
              {formatKst(graph.activatedAt)} 게시 · 검수{' '}
              {count(graph.reviewDecisions)}건 반영
              {graph.rules.map((rule) => (
                <span key={rule.id} className="block">
                  자동 검수 규칙 {rule.id} {rule.enabled ? '켜짐' : '꺼짐'} ·
                  게시 사건 {count(rule.publishedEvents)}건
                </span>
              ))}
            </>
          ) : (
            '게시된 그래프 버전이 없어요'
          )
        }
      />
      <Metric
        label="GraphDB 반영"
        value={graphDbStatusLabel[graph.graphDb?.status ?? 'unavailable']}
        detail={
          graph.graphDb?.pendingJobs != null
            ? `대기 작업 ${count(graph.graphDb.pendingJobs)}건`
            : undefined
        }
      />
      <Metric
        label="작업"
        value={
          <span className="whitespace-nowrap">
            실행 {count(jobs.running)} · 대기 {count(jobs.queued)}
          </span>
        }
        detail={`24시간 실패 ${count(jobs.failed24h)}건`}
      />
      <Metric
        label="AI 요청(7일)"
        value={`${count(ai.requests)}건`}
        detail={`성공 ${count(ai.succeeded)} · 실패 ${count(ai.failed)}`}
      />
    </dl>
  );
}

function Briefings({ data }: { data: Dashboard }) {
  const { latest, delayedOrFailed } = data.briefings;
  return (
    <Section
      title="최근 브리핑 회차"
      link={[{ to: '/admin/briefings', label: '브리핑 운영' }]}
    >
      {latest.length === 0 ? (
        <Empty>아직 브리핑 회차가 없어요.</Empty>
      ) : (
        <Table caption="브리핑 회차 목록">
          <thead>
            <tr>
              <th className={TH}>회차</th>
              <th className={TH}>상태</th>
              <th className={TH}>데이터 기준 시점</th>
            </tr>
          </thead>
          <tbody>
            {latest.map((round) => (
              <tr key={round.id}>
                <td className={`${TD} whitespace-nowrap tabular-nums`}>
                  {round.date} {editionLabel[round.edition]}
                </td>
                <td className={`${TD} font-semibold`}>
                  {roundStatusLabel[round.status]}
                </td>
                <td className={`${TD} font-inter tabular-nums`}>
                  {formatKst(round.dataWindow.end)}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {delayedOrFailed > 0 && (
        <p className="text-[11px] text-zoop-alert">
          늦게 발행됐거나 실패한 회차가 {count(delayedOrFailed)}건 있어요.
        </p>
      )}
    </Section>
  );
}

function Jobs({ data }: { data: Dashboard }) {
  const { recent } = data.jobs;
  return (
    <Section
      title="최근 작업"
      link={[{ to: '/admin/pipeline', label: '작업 관제' }]}
    >
      {recent.length === 0 ? (
        <Empty>아직 실행한 작업이 없어요.</Empty>
      ) : (
        <Table caption="최근 작업 목록">
          <thead>
            <tr>
              <th className={TH}>작업</th>
              <th className={TH}>상태</th>
              <th className={TH}>요청 시각</th>
            </tr>
          </thead>
          <tbody>
            {recent.map((job) => (
              <tr key={job.id}>
                <td className={TD}>{jobKindLabel[job.kind] ?? job.label}</td>
                <td className={`${TD} font-semibold`}>
                  {jobStatusLabel[job.status]}
                </td>
                <td className={`${TD} font-inter tabular-nums`}>
                  {formatKst(job.requestedAt)}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Section>
  );
}

function AiFeatures({ data }: { data: Dashboard }) {
  const { features } = data.ai;
  return (
    <Section
      title="AI 기능별 요청(7일)"
      link={[{ to: '/admin/ai', label: 'AI 운영' }]}
    >
      {features.length === 0 ? (
        <Empty>최근 7일 동안 AI 요청이 없어요.</Empty>
      ) : (
        <Table caption="AI 기능별 요청">
          <thead>
            <tr>
              <th className={TH}>기능</th>
              <th className={`${TH} text-right`}>요청</th>
              <th className={`${TH} text-right`}>실패</th>
            </tr>
          </thead>
          <tbody>
            {features.map((feature) => (
              <tr key={feature.feature}>
                <td className={TD}>{feature.label}</td>
                <td className={`${TD} text-right tabular-nums`}>
                  {count(feature.requests)}
                </td>
                <td className={`${TD} text-right tabular-nums`}>
                  {count(feature.failed)}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Section>
  );
}

function Usage({ data }: { data: Dashboard }) {
  const { members, audit } = data;
  return (
    <Section
      title="이용 현황"
      link={[{ to: '/admin/audit', label: '감사 로그' }]}
    >
      <dl className="grid grid-cols-3 gap-6 py-2">
        <Metric label="등록 회원" value={count(members.registered)} />
        <Metric
          label="회원 접속 세션"
          value={count(members.activeMemberSessions)}
          detail={`비회원 ${count(members.activeGuestSessions)}`}
        />
        <Metric label="감사 기록(24시간)" value={count(audit.last24h)} />
      </dl>
    </Section>
  );
}

// A-ADM-01 운영 대시보드 (FS072)
// - 전체 운영 상황 요약과 각 관리 화면으로 가는 링크(브리핑 운영·작업 관제·AI 운영·감사 로그)
// - 상태: 조회 중 · 자료 없음(영역별) · 조회 실패(다시 시도) · 권한 없음. 관리자 세션 만료(401)는 AdminProtectedRoute가 로그인으로 보낸다.
export default function DashboardSummary() {
  const dashboard = useAsyncData(getAdminDashboard);
  const data = dashboard.data;
  // 새로 고침하면 이용·선호도 영역도 다시 읽는다.
  const [refresh, setRefresh] = useState(0);

  return (
    <div className="flex flex-col gap-6 py-8 text-zoop-ink">
      <PageHeader
        title="대시보드"
        actions={
          <>
            {data && (
              <p className="font-inter text-[11px] text-zoop-muted tabular-nums">
                갱신 {formatKst(data.generatedAt)}
              </p>
            )}
            <button
              type="button"
              onClick={() => {
                dashboard.reload();
                setRefresh((value) => value + 1);
              }}
              disabled={dashboard.status === 'loading'}
              className={BUTTON}
            >
              새로 고침
            </button>
          </>
        }
      />

      {dashboard.status === 'loading' && (
        <Loading>대시보드를 불러오고 있어요</Loading>
      )}

      {dashboard.status === 'error' && (
        <ErrorBox
          title="대시보드를 불러오지 못했어요"
          error={dashboard.error}
          onRetry={dashboard.reload}
        />
      )}

      {data && (
        <>
          {data.ledger.status === 'unavailable' && (
            <p
              role="status"
              className="rounded-[3px] border-[0.667px] border-dashed border-zoop-line bg-zoop-wash px-3 py-2 text-[11px] text-zoop-muted"
            >
              원장에 연결하지 못해 검수 현황을 표시하지 못했어요.
              {data.ledger.error && ` (${data.ledger.error.message})`}
            </p>
          )}
          <Overview data={data} />
          <div className="grid gap-8 md:grid-cols-2">
            <Briefings data={data} />
            <Jobs data={data} />
          </div>
          <div className="grid gap-8 md:grid-cols-2">
            <AiFeatures data={data} />
            <Usage data={data} />
          </div>
          <InsightsOverviewSection key={refresh} />
        </>
      )}
    </div>
  );
}
