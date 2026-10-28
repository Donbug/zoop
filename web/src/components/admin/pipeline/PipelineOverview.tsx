import { getPipelineOverview } from '@/apis/admin/pipeline';
import { ErrorBox, Loading, Metric } from '@/components/admin/common/AdminUi';
import { BUTTON, count } from '@/components/admin/common/adminStyles';
import { useAdminRefresh } from '@/hooks/useAdminRefresh';
import { useAsyncData } from '@/hooks/useAsyncData';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import type { ProjectionStatus } from '@/types/admin/pipeline';
import { formatKst } from '@/util/format';

const projectionLabel: Record<ProjectionStatus, string> = {
  reflected: '반영됨',
  pending: '반영 대기',
  mismatch: '불일치',
  unavailable: '확인 불가',
};

// A-ADM-03 이슈 관제 개요 (FS058·FS059·FS063·FS067-01, getPipelineOverview)
// - 프로토타입 admin/pages/pipeline.tsx의 Overview·OverviewJobsLine을 옮겼다. 10초마다 조용히 다시 읽는다(#366).
// - GraphDB는 AI 쪽 저장소라 앱이 직접 읽지 않는다. 활성 버전에 기록된 상태만 보이고 반영 건수는 보이지 않는다.
// - 규칙 요약은 [규칙] 탭에 있으므로 여기서 다시 보이지 않는다.
export default function PipelineOverview({
  onOpenJobs,
}: {
  onOpenJobs: () => void;
}) {
  const revision = useAdminSessionStore((state) => state.revision);
  return <OverviewContent key={revision} onOpenJobs={onOpenJobs} />;
}

function OverviewContent({ onOpenJobs }: { onOpenJobs: () => void }) {
  const overview = useAsyncData(getPipelineOverview);
  useAdminRefresh(overview.reload, 10000);

  if (overview.status === 'loading')
    return <Loading>원장 상태를 불러오고 있어요</Loading>;
  if (overview.status === 'error')
    return (
      <ErrorBox
        title="원장 상태를 불러오지 못했어요"
        error={overview.error}
        onRetry={overview.reload}
      />
    );

  const o = overview.data;
  const { jobs } = o;
  return (
    <section aria-label="이슈 관제 개요" className="flex flex-col gap-3">
      {overview.refreshError && (
        <p role="status" className="text-[11px] text-zoop-muted">
          새로 고치지 못했어요. 이전 결과를 표시해요.
        </p>
      )}
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 border-y-[0.667px] border-zoop-line py-4 md:grid-cols-3 xl:grid-cols-5">
        <Metric
          label="후보 판정"
          value={`${count(o.candidates.active)}건`}
          detail={`통과 ${count(o.candidates.allow)} · 보류 ${count(o.candidates.hold)} · 폐기 ${count(o.candidates.reject)}`}
        />
        <Metric
          label="검수 대기(보류)"
          value={`${count(o.review.holdPendingReview)}건`}
          detail={`검수 결정 ${count(o.review.decisions)}건 · 규칙 게시 사건 ${count(o.review.ruleEvents)}건`}
        />
        <Metric
          label="사용자에게 보이는 버전"
          value={o.publication.activeVersionId ?? '–'}
          detail={
            o.publication.activeVersionId === null
              ? '활성 버전이 없어요'
              : o.publication.ledgerMatchesActive
                ? '가장 최근 수입한 버전이에요'
                : '더 새로 수입한 버전이 대기 중이에요'
          }
        />
        <Metric
          label="GraphDB 반영"
          value={projectionLabel[o.projection.status]}
          detail="활성 버전에 기록된 상태예요"
        />
        <Metric
          label="원장 확인"
          value={
            <span className="text-sm">{formatKst(o.ledger.checkedAt)}</span>
          }
          detail={`이슈 ${count(o.issues.approved)} · 관계 ${count(o.issues.relations)} · 기사 ${count(o.issues.articles)}`}
        />
      </dl>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-xs">
        <span className="font-semibold">분석 작업</span>
        <span className="tabular-nums">
          실행 중 {count(jobs.running)} · 대기 {count(jobs.queued)} · 24시간
          실패 {count(jobs.failed24h)}건
        </span>
        {jobs.lastFailure && (
          <span className="min-w-0 text-zoop-muted">
            최근 실패 {jobs.lastFailure.label ?? jobs.lastFailure.jobId} ·{' '}
            {formatKst(jobs.lastFailure.finishedAt)}
          </span>
        )}
        {jobs.ingest && (
          <span className="text-zoop-muted">
            미해결 수집 실패 {count(jobs.ingest.unresolvedFailures)}건
          </span>
        )}
        <button type="button" className={BUTTON} onClick={onOpenJobs}>
          작업 로그 보기
        </button>
      </div>
      <p className="text-[11px] text-zoop-faint">
        조회 {formatKst(o.asOf)} · 10초마다 자동 갱신
      </p>
    </section>
  );
}
