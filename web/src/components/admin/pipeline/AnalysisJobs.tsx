import { useCallback, useState } from 'react';
import { getAnalysisJob, listAnalysisJobs } from '@/apis/admin/jobs';
import {
  Empty,
  ErrorBox,
  Loading,
  MoreButton,
  Note,
  Section,
  Table,
} from '@/components/admin/common/AdminUi';
import {
  BUTTON,
  TD,
  TH,
  count,
  countWith,
} from '@/components/admin/common/adminStyles';
import JobActionForm, {
  type JobAction,
} from '@/components/admin/pipeline/JobActionForm';
import AnalyzePlanCreateForm from '@/components/admin/pipeline/AnalyzePlanCreateForm';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import {
  ingestOutcomeLabel,
  jobKindLabel,
  jobStatusLabel,
} from '@/constants/adminLabels';
import { useAsyncData } from '@/hooks/useAsyncData';
import { useCursorPages } from '@/hooks/useCursorPages';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import type {
  AnalysisJob,
  IngestBaseline,
  JobList,
  PlanRun,
  RetryCode,
} from '@/types/admin/jobs';
import { formatKst } from '@/util/format';

const jobName = (job: AnalysisJob) => jobKindLabel[job.kind] ?? job.label;
const isActive = (job: AnalysisJob) =>
  job.status === 'queued' || job.status === 'running';
const isClosed = (job: AnalysisJob) =>
  job.status === 'failed' || job.status === 'cancelled';

const planPhaseLabel: Record<PlanRun['phase'], string> = {
  awaiting_admission: 'AI 접수 대기',
  admitting: 'AI 접수 확인 중',
  extracting: 'S2 추출 중',
  relating: 'S3 관계 분석 중',
  cancelling: '취소 처리 중',
  ready: 'AI 처리 인계 준비 완료',
  failed: '분석계획 처리 실패',
  cancelled: '분석계획 처리 취소됨',
};

const planRetryRefusal: Partial<Record<RetryCode, string>> = {
  worker_unavailable:
    '분석계획 실행기가 연결되지 않았거나 비활성화되어 있어요.',
  plan_not_reusable:
    '이 계획의 고정된 AI 작업을 재사용할 수 없어요. 별도로 준비한 새 계획이 필요해요.',
  outcome_unknown:
    '이전 실행 결과가 불확실해요. 권한 있는 절차로 결과를 확인하기 전에는 새 시도를 만들 수 없어요.',
};

/** 걸린 시간: 1분 넘으면 '3분 5초', 아니면 '42초' */
function formatDuration(seconds: number | null) {
  if (seconds === null) return '–';
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  return minutes > 0 ? `${minutes}분 ${total % 60}초` : `${total}초`;
}

/** 실행 보고의 오류 항목(단계·종류·메시지)을 한 줄로 */
function errorLine(entry: Record<string, unknown>) {
  return [entry.stage, entry.type, entry.message]
    .filter((part) => part !== undefined && part !== null && part !== '')
    .map(String)
    .join(' · ');
}

/** 다음 기사 처리가 시작할 기준 시점: 정상 종료한 가장 최근 기사 처리의 시작 시각. 실패·취소는 옮기지 않는다. */
function IngestBaselineLine({ baseline }: { baseline: IngestBaseline }) {
  if (!baseline.at && !baseline.unresolvedFailures) return null;
  return (
    <div className="flex flex-col gap-1">
      <dl className="flex flex-wrap items-center gap-x-6 gap-y-1 text-xs">
        <div className="flex flex-wrap items-center gap-x-2">
          <dt className="text-[11px] text-zoop-muted">기사 처리 기준 시점</dt>
          <dd className="font-inter tabular-nums">
            {formatKst(baseline.at)}
            {baseline.outcome &&
              ` · ${ingestOutcomeLabel[baseline.outcome] ?? baseline.outcome}`}
          </dd>
        </div>
        {!!baseline.unresolvedFailures && (
          <div className="flex items-center gap-x-2">
            <dt className="text-[11px] text-zoop-muted">다시 처리할 실패</dt>
            <dd className="tabular-nums">
              {countWith(baseline.unresolvedFailures, '건')}
            </dd>
          </div>
        )}
      </dl>
      <Note>
        정상 종료한 가장 최근 기사 처리의 시작 시각이에요. 실패·취소는 옮기지
        않아요.
      </Note>
    </div>
  );
}

/** 실행 중·대기 중인 작업과 실행 잠금. 잠금은 관리자 작업이 실행 중일 때만 걸린다. */
function ActiveLine({
  data,
  disabled,
  onSelect,
}: {
  data: JobList;
  disabled: boolean;
  onSelect: (id: string) => void;
}) {
  const active = data.active;
  if (!active && !data.lock.locked) return null;
  const lockedId = data.lock.jobId;
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-3 rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-wash px-4 py-3"
    >
      <p className="min-w-0 flex-1 text-xs">
        {active
          ? `진행 중인 작업: ${jobName(active)} · ${jobStatusLabel[active.status]}`
          : '실행 중인 작업이 있어요.'}
        {data.lock.locked && data.lock.reason && (
          <span className="block text-[11px] text-zoop-muted">
            {data.lock.reason}
          </span>
        )}
      </p>
      {(active?.id ?? lockedId) && (
        <button
          type="button"
          disabled={disabled}
          onClick={() => onSelect((active?.id ?? lockedId) as string)}
          className={BUTTON}
        >
          진행 중인 작업 보기
        </button>
      )}
    </div>
  );
}

// A-ADM-03 작업 탭 (FS058·FS067-01·FS067-03, listAnalysisJobs·getAnalysisJob·retryAnalysisJob·cancelAnalysisJob)
// - 프로토타입 admin/pipeline/jobs.tsx를 옮겼다. 고른 작업은 주소(?job=)에 남는다.
// - 분석계획은 별도 analyze_plan 작업이며, 기존 기사 처리 기준 시점을 옮기지 않는다.
// - 호출 상한·실행 명령·로그 줄은 정식 계약에서 빠진 로컬 PoC 필드라 보여 주지 않는다.
export default function AnalysisJobs() {
  const revision = useAdminSessionStore((state) => state.revision);
  return <AnalysisJobsSession key={revision} />;
}

function AnalysisJobsSession() {
  const { params, updateQuery } = useRouteQuery();
  const selectedId = params.get('job');
  const jobs = useCursorPages(listAnalysisJobs);
  const [notice, setNotice] = useState<string | null>(null);
  // 다시 실행·취소 요청이 진행 중인지. 진행 중에는 다른 작업을 고르거나 폼을 닫지 못하게 한다.
  const [pending, setPending] = useState(false);
  const first = jobs.pages[0];

  const select = (id: string | null) => {
    if (pending) return;
    setNotice(null);
    updateQuery({ job: id });
  };

  if (jobs.status === 'loading')
    return <Loading>작업 목록을 불러오고 있어요</Loading>;
  if (jobs.status === 'error' && jobs.error)
    return (
      <ErrorBox
        title="작업 목록을 불러오지 못했어요"
        error={jobs.error}
        onRetry={jobs.reload}
      />
    );

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(360px,460px)]">
      <Section title="작업">
        <AnalyzePlanCreateForm
          disabled={pending}
          onPendingChange={setPending}
          onCreated={(result) => {
            setNotice(
              result.deduplicated
                ? '이 분석계획은 이미 접수돼 있어요. 기존 작업을 보여 줘요.'
                : '분석계획을 대기열에 접수했어요. 아직 AI 처리 완료는 아니에요.',
            );
            updateQuery({ job: result.job.id });
            jobs.reload();
          }}
        />
        {first && (
          <>
            <ActiveLine data={first} disabled={pending} onSelect={select} />
            <IngestBaselineLine baseline={first.ingest} />
          </>
        )}
        {notice && (
          <p role="status" className="text-[11px] font-semibold">
            {notice}
          </p>
        )}
        {jobs.items.length === 0 ? (
          <Empty>아직 실행한 작업이 없어요.</Empty>
        ) : (
          <Table caption="작업 목록">
            <thead>
              <tr>
                <th className={TH}>작업</th>
                <th className={TH}>상태</th>
                <th className={TH}>요청 시각</th>
                <th className={`${TH} text-right`}>걸린 시간</th>
              </tr>
            </thead>
            <tbody>
              {jobs.items.map((job) => (
                <tr
                  key={job.id}
                  className={job.id === selectedId ? 'bg-zoop-wash' : undefined}
                >
                  <td className={`${TD} whitespace-nowrap`}>
                    <button
                      type="button"
                      disabled={pending}
                      aria-pressed={job.id === selectedId}
                      onClick={() => select(job.id)}
                      className="min-h-8 text-left font-semibold hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink disabled:opacity-60"
                    >
                      {jobName(job)}
                    </button>
                    {job.retryOf && (
                      <span className="ml-2 rounded-[3px] border-[0.667px] border-zoop-line px-1.5 py-0.5 text-[10px] text-zoop-muted">
                        재시도
                      </span>
                    )}
                  </td>
                  <td className={TD}>
                    <span className="font-semibold">
                      {jobStatusLabel[job.status]}
                    </span>
                    {job.cancelRequested && isActive(job) && (
                      <span className="block text-[11px] text-zoop-muted">
                        취소 요청됨
                      </span>
                    )}
                    {job.kind === 'analyze_plan' && (
                      <span className="block text-[11px] text-zoop-muted">
                        {planPhaseLabel[job.planRun.phase]} · 완료 단위{' '}
                        {count(job.planRun.readyUnits)} /{' '}
                        {count(job.planRun.totalUnits)}
                      </span>
                    )}
                    {job.ingest?.newArticles != null && (
                      <span className="block text-[11px] text-zoop-muted">
                        신규 기사 {count(job.ingest.newArticles)}건
                      </span>
                    )}
                  </td>
                  <td
                    className={`${TD} whitespace-nowrap font-inter tabular-nums`}
                  >
                    {formatKst(job.requestedAt)}
                  </td>
                  <td className={`${TD} text-right tabular-nums`}>
                    {formatDuration(job.durationSeconds)}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        {jobs.hasMore && (
          <MoreButton
            loading={jobs.loadingMore}
            error={jobs.moreError}
            onClick={jobs.loadMore}
          />
        )}
      </Section>

      <aside
        aria-label="작업 상세"
        className="min-w-0 border-t-[0.667px] border-zoop-line pt-6 lg:border-t-0 lg:border-l-[0.667px] lg:pt-0 lg:pl-6"
      >
        {selectedId ? (
          <JobDetail
            key={selectedId}
            id={selectedId}
            retryRule={first?.retryRule ?? null}
            pending={pending}
            onPendingChange={setPending}
            onSelect={select}
            onClose={() => select(null)}
            onRetried={(result) => {
              setNotice(
                result.deduplicated
                  ? '같은 다시 실행 요청이 이미 접수돼 있어요.'
                  : result.job.kind === 'analyze_plan'
                    ? '고정된 AI 작업 ID로 분석계획을 이어서 처리하도록 대기열에 넣었어요.'
                    : `${jobName(result.job)} 작업을 다시 실행하도록 대기열에 넣었어요.`,
              );
              updateQuery({ job: result.job.id });
              jobs.reload();
            }}
            onCancelled={(job) => {
              setNotice(
                job.status === 'cancelled'
                  ? `${jobName(job)} 작업을 취소했어요.`
                  : `${jobName(job)} 작업에 취소를 요청했어요.`,
              );
              jobs.reload();
            }}
          />
        ) : (
          <Empty>작업을 고르면 실행 보고와 오류를 보여 줘요.</Empty>
        )}
      </aside>
    </div>
  );
}

function JobDetail({
  id,
  retryRule,
  pending,
  onPendingChange,
  onSelect,
  onClose,
  onRetried,
  onCancelled,
}: {
  id: string;
  retryRule: string | null;
  pending: boolean;
  onPendingChange: (pending: boolean) => void;
  onSelect: (id: string) => void;
  onClose: () => void;
  onRetried: Parameters<typeof JobActionForm>[0]['onRetried'];
  onCancelled: Parameters<typeof JobActionForm>[0]['onCancelled'];
}) {
  const load = useCallback(() => getAnalysisJob(id), [id]);
  const detail = useAsyncData(load);
  const [action, setAction] = useState<JobAction | null>(null);

  if (detail.status === 'loading')
    return <Loading>작업 상세를 불러오고 있어요</Loading>;
  if (detail.status === 'error')
    return (
      <ErrorBox
        title="작업 상세를 불러오지 못했어요"
        error={detail.error}
        onRetry={detail.reload}
      />
    );

  const job = detail.data;
  const active = isActive(job);
  const closed = isClosed(job);
  const report = job.report;

  return (
    <article aria-labelledby="job-title" className="flex flex-col gap-4">
      <div className="flex items-start gap-2">
        <h2 id="job-title" className="min-w-0 flex-1 text-sm font-bold">
          {jobName(job)}
          <span className="mt-0.5 block font-inter text-[11px] font-normal break-all text-zoop-muted">
            {job.id}
          </span>
        </h2>
        <button
          type="button"
          aria-label="작업 상세 닫기"
          disabled={pending}
          onClick={onClose}
          className={BUTTON}
        >
          ×
        </button>
      </div>
      {job.kind === 'analyze_plan' && (
        <button
          type="button"
          disabled={pending || action !== null}
          onClick={detail.reload}
          className={BUTTON}
        >
          진행 상태 새로 고침
        </button>
      )}

      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-xs">
        <dt className="text-[11px] text-zoop-muted">상태</dt>
        <dd className="flex flex-wrap items-center gap-2 font-semibold">
          {jobStatusLabel[job.status]}
          {job.cancelRequested && active && (
            <span className="text-[11px] font-normal text-zoop-muted">
              취소 요청됨
            </span>
          )}
          {job.recovered && (
            <span className="rounded-[3px] border-[0.667px] border-zoop-line px-1.5 py-0.5 text-[10px] font-normal text-zoop-muted">
              재시작 복구
            </span>
          )}
        </dd>
        <dt className="text-[11px] text-zoop-muted">요청</dt>
        <dd className="font-inter tabular-nums">
          {formatKst(job.requestedAt)} · {job.requestedBy}
        </dd>
        <dt className="text-[11px] text-zoop-muted">시작·종료</dt>
        <dd className="font-inter tabular-nums">
          {job.startedAt ? formatKst(job.startedAt) : '시작 전'} ~{' '}
          {job.finishedAt
            ? formatKst(job.finishedAt)
            : active
              ? '진행 중'
              : '–'}
        </dd>
        <dt className="text-[11px] text-zoop-muted">걸린 시간</dt>
        <dd className="tabular-nums">{formatDuration(job.durationSeconds)}</dd>
        {job.retryOf && (
          <>
            <dt className="text-[11px] text-zoop-muted">재시도 원본</dt>
            <dd>
              <button
                type="button"
                disabled={pending}
                onClick={() => onSelect(job.retryOf as string)}
                className="font-inter break-all underline underline-offset-4 disabled:opacity-60"
              >
                {job.retryOf}
              </button>
            </dd>
          </>
        )}
        <dt className="text-[11px] text-zoop-muted">사유</dt>
        <dd className="break-words">{job.reason}</dd>
      </dl>

      {job.error && (
        <p role="alert" className="text-xs text-zoop-alert">
          {job.error.message}{' '}
          <span className="font-inter text-[11px] text-zoop-muted">
            ({job.error.code})
          </span>
        </p>
      )}

      {!action && (closed || active) && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            {closed && (
              <button
                type="button"
                disabled={pending || !job.retry.allowed}
                onClick={() => setAction('retry')}
                className={BUTTON}
              >
                {job.kind === 'analyze_plan' ? '이어서 처리' : '다시 실행'}
              </button>
            )}
            {closed && job.retry.blockedBy && (
              <button
                type="button"
                disabled={pending}
                onClick={() => onSelect(job.retry.blockedBy as string)}
                className={BUTTON}
              >
                {job.retry.blockedBy} 보기
              </button>
            )}
            {active && (
              <button
                type="button"
                disabled={pending || job.cancelRequested}
                onClick={() => setAction('cancel')}
                className={BUTTON}
              >
                {job.cancelRequested ? '취소 요청됨' : '작업 취소'}
              </button>
            )}
          </div>
          {closed && !job.retry.allowed && (
            <p role="status" className="text-[11px] text-zoop-muted">
              {job.kind === 'analyze_plan'
                ? `이어서 처리할 수 없어요. ${planRetryRefusal[job.retry.code] ?? job.retry.reason}`
                : `다시 실행할 수 없어요. ${job.retry.reason}`}
            </p>
          )}
          {closed && job.kind !== 'analyze_plan' && retryRule && (
            <Note>{retryRule}</Note>
          )}
        </div>
      )}

      {action && (
        <JobActionForm
          action={action}
          job={job}
          onPendingChange={onPendingChange}
          onCancel={() => setAction(null)}
          onRetried={(result) => {
            setAction(null);
            onRetried(result);
          }}
          onCancelled={(result) => {
            setAction(null);
            onCancelled(result);
          }}
        />
      )}

      {job.kind === 'analyze_plan' && (
        <Section title="분석계획 진행">
          <div role="status" aria-live="polite" className="text-xs">
            {planPhaseLabel[job.planRun.phase]}
            {job.cancelRequested &&
              active &&
              ' · 취소 요청을 처리 중이며 아직 종료되지 않았어요.'}
          </div>
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-xs">
            <dt>planId</dt>
            <dd className="break-all">{job.planRun.planId}</dd>
            <dt>planDigest</dt>
            <dd className="break-all">{job.planRun.planDigest}</dd>
            <dt>접수 ID</dt>
            <dd className="break-all">{job.planRun.admissionId ?? '–'}</dd>
            <dt>매니페스트</dt>
            <dd className="break-all">{job.planRun.manifestDigest ?? '–'}</dd>
            <dt>출처·회차</dt>
            <dd className="break-all">
              {job.planRun.sourceId ?? '–'} · {job.planRun.roundId ?? '–'}
            </dd>
            <dt>완료 단위 / 전체 단위</dt>
            <dd>
              {count(job.planRun.readyUnits)} / {count(job.planRun.totalUnits)}
            </dd>
            <dt>진행 단위 순번</dt>
            <dd>{count(job.planRun.activeUnit)}</dd>
            <dt>공개 변경</dt>
            <dd>없음</dd>
          </dl>
          <Note>
            완료 단위는 S2·S3 결과 전달이 모두 확인된 쌍이에요. 기사·후보 수가
            아니에요. 준비 완료는 AI 처리 인계이며, 검수 승인·그래프 반영·공개
            완료가 아니에요. 기사 처리 기준 시점은 바뀌지 않아요.
          </Note>
          {job.status === 'cancelled' && !job.startedAt && (
            <Note>대기 중 취소되어 이 작업은 AI 실행을 시작하지 않았어요.</Note>
          )}
        </Section>
      )}
      {job.ingest && (
        <Section title="기사 처리 결과">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-xs">
            <dt className="text-[11px] text-zoop-muted">결과</dt>
            <dd>
              {job.ingest.outcome
                ? (ingestOutcomeLabel[job.ingest.outcome] ?? job.ingest.outcome)
                : '처리 중'}
            </dd>
            <dt className="text-[11px] text-zoop-muted">신규 기사</dt>
            <dd className="tabular-nums">
              {job.ingest.newArticles != null ? (
                <>
                  {count(job.ingest.newArticles)}건
                  {!!job.ingest.duplicateArticles && (
                    <span className="text-zoop-muted">
                      {' '}
                      · 이미 처리한 기사 {count(job.ingest.duplicateArticles)}건
                      제외
                    </span>
                  )}
                </>
              ) : (
                <span className="text-zoop-muted">
                  {job.ingest.outcome ? '확인하지 못했어요' : '–'}
                </span>
              )}
            </dd>
            <dt className="text-[11px] text-zoop-muted">기준 시점</dt>
            <dd className="font-inter tabular-nums">
              {formatKst(job.ingest.baselineBefore)} →{' '}
              {formatKst(job.ingest.baselineAfter)}
              {job.ingest.outcome &&
                (job.ingest.baselineAdvanced ? ' · 옮겼어요' : ' · 그대로예요')}
            </dd>
          </dl>
        </Section>
      )}

      {report && (
        <Section title="실행 보고">
          <dl className="grid grid-cols-4 gap-x-4 gap-y-3 text-xs">
            {(
              [
                ['처리', report.processed],
                ['승인', report.approved],
                ['보류', report.held],
                ['거부', report.rejected],
                ['대기', report.pending],
                ['건너뜀', report.skipped],
                ['오류', report.errorCount],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="flex flex-col">
                <dt className="text-[11px] text-zoop-muted">{label}</dt>
                <dd className="font-semibold tabular-nums">{count(value)}</dd>
              </div>
            ))}
          </dl>
          {report.errors.length > 0 && (
            <ul className="flex list-disc flex-col gap-1 pl-5 text-[11px]">
              {report.errors.map((entry, index) => (
                <li key={index}>{errorLine(entry) || '내용 없는 오류'}</li>
              ))}
            </ul>
          )}
          {report.collectionErrorCount > 0 && (
            <div className="flex flex-col gap-1">
              <p className="text-[11px] font-semibold text-zoop-muted">
                기사를 가져오는 요청 실패 {count(report.collectionErrorCount)}건
              </p>
              <ul className="flex list-disc flex-col gap-1 pl-5 text-[11px]">
                {report.collectionErrors.map((entry, index) => (
                  <li key={index}>{errorLine(entry) || '내용 없는 오류'}</li>
                ))}
              </ul>
            </div>
          )}
        </Section>
      )}

      {report && (
        <Section title="모델 사용량">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-xs sm:grid-cols-4">
            <div className="flex flex-col">
              <dt className="text-[11px] text-zoop-muted">모델 호출</dt>
              <dd className="font-semibold tabular-nums">
                {countWith(report.usage.calls, '회')}
              </dd>
            </div>
            <div className="flex flex-col">
              <dt className="text-[11px] text-zoop-muted">재생 호출</dt>
              <dd className="font-semibold tabular-nums">
                {countWith(report.usage.replayCalls, '회')}
              </dd>
            </div>
            <div className="flex flex-col">
              <dt className="text-[11px] text-zoop-muted">입력 토큰</dt>
              <dd className="font-semibold tabular-nums">
                {count(report.usage.inputTokens)}
              </dd>
            </div>
            <div className="flex flex-col">
              <dt className="text-[11px] text-zoop-muted">출력 토큰</dt>
              <dd className="font-semibold tabular-nums">
                {count(report.usage.outputTokens)}
              </dd>
            </div>
          </dl>
          <Note>
            예상 비용{' '}
            {report.usage.estimatedCost === null
              ? '미제공'
              : `$${report.usage.estimatedCost.toFixed(4)}`}
            {report.executionMode && ` · 실행 방식 ${report.executionMode}`}
          </Note>
        </Section>
      )}

      {job.flush && (
        <p className="text-xs">
          완료한 GraphDB 반영 작업 {count(job.flush.completedProjectionJobs)}건
        </p>
      )}
    </article>
  );
}
