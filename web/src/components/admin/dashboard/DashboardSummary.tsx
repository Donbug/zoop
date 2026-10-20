import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { getAdminDashboard } from '@/apis/admin/dashboard';
import { ApiError } from '@/apis/auth/ApiService';
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

const count = (value: number) => value.toLocaleString('ko-KR');

const RETRY_BUTTON =
  'h-8 shrink-0 rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-paper px-3 text-xs font-semibold text-zoop-ink hover:bg-zoop-wash disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink';
const TH =
  'border-b-[0.667px] border-zoop-line px-2 py-2 text-left text-[11px] font-medium text-zoop-muted';
const TD = 'border-b-[0.667px] border-zoop-line px-2 py-2.5 text-xs';

function errorMessage(error: Error) {
  if (
    error instanceof ApiError &&
    (error.status === 403 || error.code === 'ACCESS_DENIED')
  )
    return '대시보드를 볼 권한이 없어요. 관리자 권한을 확인해 주세요.';
  if (error instanceof ApiError && error.code === 'SOURCE_UNAVAILABLE')
    return '운영 현황을 모으는 서버에 연결하지 못했어요.';
  return '잠시 후 다시 시도해 주세요.';
}

function Metric({
  label,
  value,
  detail,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <dt className="text-[11px] text-zoop-muted">{label}</dt>
      <dd className="text-xl font-[750] tracking-[-0.03em] tabular-nums">
        {value}
      </dd>
      {detail && (
        <dd className="text-[11px] leading-relaxed text-zoop-faint tabular-nums">
          {detail}
        </dd>
      )}
    </div>
  );
}

function Section({
  title,
  to,
  linkLabel,
  children,
}: {
  title: string;
  to: string;
  linkLabel: string;
  children: ReactNode;
}) {
  return (
    <section className="flex min-w-0 flex-col gap-2" aria-label={title}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-bold">{title}</h2>
        <Link
          to={to}
          className="text-[11px] text-zoop-muted hover:text-zoop-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink"
        >
          {linkLabel} →
        </Link>
      </div>
      {children}
    </section>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-[3px] border-[0.667px] border-dashed border-zoop-line bg-zoop-wash px-3 py-4 text-[11px] text-zoop-muted">
      {children}
    </p>
  );
}

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
        value={graph?.activeVersionId ?? '–'}
        detail={
          graph?.activeVersionId ? (
            <>
              {formatKst(graph.activatedAt)} 게시 · 검수{' '}
              {graph.reviewDecisions == null
                ? '확인 불가'
                : `${count(graph.reviewDecisions)}건 반영`}
              {graph.rules?.map((rule) => (
                <span key={rule.id} className="block">
                  자동 검수 규칙 {rule.id} {rule.enabled ? '켜짐' : '꺼짐'} ·
                  게시 사건 {count(rule.publishedEvents)}건
                </span>
              ))}
            </>
          ) : graph ? (
            '게시된 그래프 버전이 없어요'
          ) : (
            '그래프 현황을 읽지 못했어요'
          )
        }
      />
      <Metric
        label="GraphDB 반영"
        value={graphDbStatusLabel[graph?.graphDb?.status ?? 'unavailable']}
        detail={
          graph?.graphDb?.pendingJobs != null
            ? `대기 작업 ${count(graph.graphDb.pendingJobs)}건`
            : undefined
        }
      />
      <Metric
        label="작업"
        value={
          <span className="whitespace-nowrap">
            {jobs
              ? `실행 ${count(jobs.running)} · 대기 ${count(jobs.queued)}`
              : '–'}
          </span>
        }
        detail={
          jobs
            ? `24시간 실패 ${count(jobs.failed24h)}건`
            : '작업 원장을 읽지 못했어요'
        }
      />
      <Metric
        label="AI 요청(7일)"
        value={ai ? `${count(ai.requests)}건` : '–'}
        detail={
          ai
            ? `성공 ${count(ai.succeeded)} · 실패 ${count(ai.failed)}`
            : 'AI 요청 원장을 읽지 못했어요'
        }
      />
    </dl>
  );
}

function Briefings({ data }: { data: Dashboard }) {
  const briefing = data.briefings;
  return (
    <Section
      title="최근 브리핑 회차"
      to="/admin/briefings"
      linkLabel="브리핑 운영"
    >
      {!briefing ? (
        <Empty>브리핑 원장을 읽지 못했어요.</Empty>
      ) : briefing.latest.length === 0 ? (
        <Empty>아직 브리핑 회차가 없어요.</Empty>
      ) : (
        <table className="w-full border-collapse">
          <caption className="sr-only">브리핑 회차 목록</caption>
          <thead>
            <tr>
              <th className={TH}>회차</th>
              <th className={TH}>상태</th>
              <th className={TH}>데이터 기준 시점</th>
            </tr>
          </thead>
          <tbody>
            {briefing.latest.map((round) => (
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
        </table>
      )}
      {briefing && briefing.delayedOrFailed > 0 && (
        <p className="text-[11px] text-zoop-alert">
          늦게 발행됐거나 실패한 회차가 {count(briefing.delayedOrFailed)}건
          있어요.
        </p>
      )}
    </Section>
  );
}

function Jobs({ data }: { data: Dashboard }) {
  const jobs = data.jobs;
  return (
    <Section title="최근 작업" to="/admin/pipeline" linkLabel="작업 관제">
      {!jobs ? (
        <Empty>작업 원장을 읽지 못했어요.</Empty>
      ) : jobs.recent.length === 0 ? (
        <Empty>아직 실행한 작업이 없어요.</Empty>
      ) : (
        <table className="w-full border-collapse">
          <caption className="sr-only">최근 작업 목록</caption>
          <thead>
            <tr>
              <th className={TH}>작업</th>
              <th className={TH}>상태</th>
              <th className={TH}>요청 시각</th>
            </tr>
          </thead>
          <tbody>
            {jobs.recent.map((job) => (
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
        </table>
      )}
    </Section>
  );
}

function AiFeatures({ data }: { data: Dashboard }) {
  const ai = data.ai;
  return (
    <Section title="AI 기능별 요청(7일)" to="/admin/ai" linkLabel="AI 운영">
      {!ai ? (
        <Empty>AI 요청 원장을 읽지 못했어요.</Empty>
      ) : ai.features.length === 0 ? (
        <Empty>최근 7일 동안 AI 요청이 없어요.</Empty>
      ) : (
        <table className="w-full border-collapse">
          <caption className="sr-only">AI 기능별 요청</caption>
          <thead>
            <tr>
              <th className={TH}>기능</th>
              <th className={`${TH} text-right`}>요청</th>
              <th className={`${TH} text-right`}>실패</th>
            </tr>
          </thead>
          <tbody>
            {ai.features.map((feature) => (
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
        </table>
      )}
    </Section>
  );
}

function Usage({ data }: { data: Dashboard }) {
  const { members, audit } = data;
  return (
    <Section title="이용 현황" to="/admin/audit" linkLabel="감사 로그">
      <dl className="grid grid-cols-3 gap-6 py-2">
        <Metric
          label="등록 회원"
          value={members ? count(members.registered) : '–'}
        />
        <Metric
          label="회원 접속 세션"
          value={members ? count(members.activeMemberSessions) : '–'}
          detail={
            members
              ? `비회원 ${count(members.activeGuestSessions)}`
              : '회원 원장을 읽지 못했어요'
          }
        />
        <Metric
          label="감사 기록(24시간)"
          value={audit ? count(audit.last24h) : '–'}
        />
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

  return (
    <div className="flex flex-col gap-6 py-8 text-zoop-ink">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-[750] tracking-[-0.035em]">대시보드</h1>
        <div className="flex items-center gap-3">
          {data && (
            <p className="font-inter text-[11px] text-zoop-muted tabular-nums">
              갱신 {formatKst(data.generatedAt)}
            </p>
          )}
          <button
            type="button"
            onClick={dashboard.reload}
            disabled={dashboard.status === 'loading'}
            className={RETRY_BUTTON}
          >
            새로 고침
          </button>
        </div>
      </header>

      {dashboard.status === 'loading' && (
        <p role="status" className="text-xs text-zoop-muted">
          대시보드를 불러오고 있어요
        </p>
      )}

      {dashboard.status === 'error' && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-wash px-4 py-3"
        >
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold">
              대시보드를 불러오지 못했어요
            </p>
            <p className="mt-0.5 text-[11px] text-zoop-muted">
              {errorMessage(dashboard.error)}
            </p>
          </div>
          <button
            type="button"
            onClick={dashboard.reload}
            className={RETRY_BUTTON}
          >
            다시 시도
          </button>
        </div>
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
        </>
      )}
    </div>
  );
}
