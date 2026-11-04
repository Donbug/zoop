import { useCallback, useId, useState } from 'react';
import { getGraphRound, listGraphRounds } from '@/apis/admin/graphRounds';
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
  SELECT,
  TD,
  TH,
  count,
} from '@/components/admin/common/adminStyles';
import GraphRoundActionForm, {
  type GraphRoundAction,
} from '@/components/admin/pipeline/GraphRoundActionForm';
import { graphRoundStageLabel, retryCaution } from '@/constants/adminLabels';
import { useAdminRefresh } from '@/hooks/useAdminRefresh';
import { useAsyncData } from '@/hooks/useAsyncData';
import { useCursorPages } from '@/hooks/useCursorPages';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import {
  GRAPH_ROUND_STAGES,
  isOpenRound,
  type GraphRound,
  type GraphRoundEvent,
  type GraphRoundEventOutcome,
  type GraphRoundStage,
} from '@/types/admin/graphRounds';
import { formatKst } from '@/util/format';

const outcomeLabel: Record<GraphRoundEventOutcome, string> = {
  advanced: '진행',
  waiting: '대기',
  failed: '실패',
  retried: '재시도',
  skipped: '건너뜀',
};

/** system:scheduler는 정기 실행, admin:<id>는 관리자 수동 시작 */
function startedByLabel(startedBy: string) {
  if (startedBy === 'system:scheduler') return '정기';
  if (startedBy.startsWith('admin:')) return `관리자(${startedBy.slice(6)})`;
  return startedBy;
}

function detailLine(detail: Record<string, unknown> | null) {
  if (!detail) return '–';
  return Object.entries(detail)
    .map(
      ([key, value]) =>
        `${key}=${typeof value === 'string' ? value : JSON.stringify(value)}`,
    )
    .join(' · ');
}

// A-ADM-03 회차 탭 (#55, FS058·FS059·FS063·FS067-01, listGraphRounds·getGraphRound·retryGraphRound·startGraphRound)
// - 그래프 정기 회차 목록(최신 슬롯부터, 단계 필터)과 고른 회차의 상세·이벤트 타임라인. 고른 회차는 주소(?round=)에 남는다.
// - 수입 완료(imported)는 비활성 버전 등록이며 공개가 아니다. 공개는 그래프 버전 탭의 활성화다.
// - 재시도·수동 시작은 회차 행만 바꾼다. 실제 진행은 회차 실행기(writer)의 다음 바퀴가 하고, 실행기가 없으면 404다.
type GraphRoundsProps = {
  /** 탭이 보이는지. 숨겨진 동안에는 자동으로 다시 읽지 않는다. */
  active: boolean;
  onOpenJob: (jobId: string) => void;
  onOpenVersions: () => void;
};

export default function GraphRounds(props: GraphRoundsProps) {
  const revision = useAdminSessionStore((state) => state.revision);
  return <GraphRoundsSession key={revision} {...props} />;
}

function GraphRoundsSession({
  active,
  onOpenJob,
  onOpenVersions,
}: GraphRoundsProps) {
  const filterId = useId();
  const { params, updateQuery } = useRouteQuery();
  const selectedId = params.get('round');
  // 단계 필터는 고른 회차처럼 주소(?roundStage=)에 남긴다. 모르는 값은 전체로 본다.
  const requestedStage = params.get('roundStage');
  const stage =
    GRAPH_ROUND_STAGES.find((value) => value === requestedStage) ?? null;
  const setStage = (next: GraphRoundStage | null) =>
    updateQuery({ roundStage: next });
  const load = useCallback(
    (cursor?: string) => listGraphRounds(stage, cursor),
    [stage],
  );
  const rounds = useCursorPages(load);
  const [starting, setStarting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  // 명령이 진행 중인지. 진행 중에는 다른 회차를 고르거나 폼을 닫지 못하게 한다.
  const [pending, setPending] = useState(false);
  // 열린 회차가 있으면 10초마다, 끝난 회차만 있어도 회차 실행기가 30분마다 새 회차를 열므로 1분마다 다시 읽는다.
  // 탭이 숨겨져 있거나 명령이 진행 중이면 읽지 않는다.
  useAdminRefresh(
    rounds.reload,
    !active || pending
      ? false
      : rounds.items.some((round) => isOpenRound(round.stage))
        ? 10000
        : 60000,
  );

  const select = (id: string | null) => {
    if (pending) return;
    setNotice(null);
    updateQuery({ round: id });
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(360px,460px)]">
      <Section title="그래프 회차">
        {rounds.refreshError && (
          <p role="status" className="text-caption text-zoop-muted">
            새로 고치지 못했어요. 이전 결과를 표시해요.
          </p>
        )}
        <Note>
          30분 회차마다 AI 계획·분석·묶음을 거쳐 비활성 버전으로 수입해요. 수입
          완료는 공개가 아니며, 공개는 그래프 버전 탭에서 바꿔요.
        </Note>
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor={filterId} className="text-caption text-zoop-muted">
              단계
            </label>
            <select
              id={filterId}
              value={stage ?? ''}
              disabled={pending}
              onChange={(event) =>
                setStage((event.target.value || null) as GraphRoundStage | null)
              }
              className={`${SELECT} w-44`}
            >
              <option value="">전체</option>
              {GRAPH_ROUND_STAGES.map((value) => (
                <option key={value} value={value}>
                  {graphRoundStageLabel[value]}
                </option>
              ))}
            </select>
          </div>
          {!starting && (
            <button
              type="button"
              disabled={pending}
              onClick={() => {
                setNotice(null);
                setStarting(true);
              }}
              className={BUTTON}
            >
              회차 시작
            </button>
          )}
        </div>
        {starting && (
          <GraphRoundActionForm
            action={{ kind: 'start' }}
            onPendingChange={setPending}
            onCancel={() => setStarting(false)}
            onDone={(round) => {
              setStarting(false);
              setNotice(
                `${round.roundId} 회차를 만들었어요. 회차 실행기의 다음 바퀴가 진행해요.`,
              );
              // 새 회차(예정)가 목록에 보이도록 단계 필터를 푼다.
              updateQuery({ round: round.roundId, roundStage: null });
              rounds.reload();
            }}
          />
        )}
        {notice && (
          <p role="status" className="text-caption font-semibold">
            {notice}
          </p>
        )}
        {/* 다시 읽는 동안에도 필터·시작 폼·상세는 그대로 두고 목록 자리만 바꾼다. */}
        {rounds.status === 'loading' ? (
          <Loading>회차 목록을 불러오고 있어요</Loading>
        ) : rounds.status === 'error' && rounds.error ? (
          <ErrorBox
            title="회차 목록을 불러오지 못했어요"
            error={rounds.error}
            onRetry={rounds.reload}
          />
        ) : rounds.items.length === 0 ? (
          <Empty>
            {stage ? '이 단계의 회차가 없어요.' : '아직 그래프 회차가 없어요.'}
          </Empty>
        ) : (
          <Table caption="그래프 회차 목록">
            <thead>
              <tr>
                <th className={TH}>회차</th>
                <th className={TH}>단계</th>
                <th className={TH}>시작</th>
                <th className={`${TH} text-right`}>시도</th>
                <th className={TH}>갱신</th>
              </tr>
            </thead>
            <tbody>
              {rounds.items.map((round) => (
                <tr
                  key={round.roundId}
                  className={
                    round.roundId === selectedId ? 'bg-zoop-wash' : undefined
                  }
                >
                  <td className={`${TD} whitespace-nowrap`}>
                    <button
                      type="button"
                      disabled={pending}
                      aria-pressed={round.roundId === selectedId}
                      onClick={() => select(round.roundId)}
                      className="min-h-8 text-left font-num font-semibold hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink disabled:opacity-60"
                    >
                      {round.roundId}
                    </button>
                    <span className="block font-num text-caption text-zoop-muted tabular-nums">
                      {formatKst(round.slotAt)}
                    </span>
                  </td>
                  <td className={TD}>
                    <span className="font-semibold">
                      {graphRoundStageLabel[round.stage] ?? round.stage}
                    </span>
                    {round.failureCode && (
                      <span className="block font-num text-caption break-all text-zoop-muted">
                        {round.failureCode}
                      </span>
                    )}
                  </td>
                  <td className={`${TD} whitespace-nowrap`}>
                    {startedByLabel(round.startedBy)}
                  </td>
                  <td className={`${TD} text-right tabular-nums`}>
                    {count(round.attempts)}
                  </td>
                  <td
                    className={`${TD} whitespace-nowrap font-num tabular-nums`}
                  >
                    {formatKst(round.updatedAt)}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        {rounds.hasMore && !pending && (
          <MoreButton
            loading={rounds.loadingMore}
            error={rounds.moreError}
            onClick={rounds.loadMore}
          />
        )}
      </Section>

      <aside
        aria-label="회차 상세"
        className="min-w-0 border-t-[0.667px] border-zoop-line pt-6 lg:border-t-0 lg:border-l-[0.667px] lg:pt-0 lg:pl-6"
      >
        {selectedId ? (
          <GraphRoundDetailPanel
            key={selectedId}
            id={selectedId}
            active={active}
            pending={pending}
            onPendingChange={setPending}
            onClose={() => select(null)}
            onOpenJob={onOpenJob}
            onOpenVersions={onOpenVersions}
            onRetried={(round) => {
              setNotice(
                `${round.roundId} 회차를 ${graphRoundStageLabel[round.stage] ?? round.stage} 단계부터 다시 열었어요. 회차 실행기의 다음 바퀴가 진행해요.`,
              );
              rounds.reload();
            }}
          />
        ) : (
          <Empty>회차를 고르면 단계별 기록을 보여 줘요.</Empty>
        )}
      </aside>
    </div>
  );
}

function GraphRoundDetailPanel({
  id,
  active,
  pending,
  onPendingChange,
  onClose,
  onOpenJob,
  onOpenVersions,
  onRetried,
}: {
  id: string;
  active: boolean;
  pending: boolean;
  onPendingChange: (pending: boolean) => void;
  onClose: () => void;
  onOpenJob: (jobId: string) => void;
  onOpenVersions: () => void;
  onRetried: (round: GraphRound) => void;
}) {
  const load = useCallback(() => getGraphRound(id), [id]);
  const detail = useAsyncData(load);
  const [action, setAction] = useState<GraphRoundAction | null>(null);
  useAdminRefresh(
    detail.reload,
    // 끝난 회차도 다른 관리자의 재시도·사후 활성화 기록으로 바뀌므로, 탭이 보이면 열린 회차는 10초, 끝난 회차는 1분마다 읽는다.
    !active || action || !detail.data
      ? false
      : isOpenRound(detail.data.round.stage)
        ? 10000
        : 60000,
  );

  if (detail.status === 'loading')
    return <Loading>회차 상세를 불러오고 있어요</Loading>;
  if (detail.status === 'error')
    return (
      <ErrorBox
        title="회차 상세를 불러오지 못했어요"
        error={detail.error}
        onRetry={detail.reload}
      />
    );

  const { round, events } = detail.data;
  const caution = retryCaution(round.failureCode);

  return (
    <article aria-labelledby="round-title" className="flex flex-col gap-4">
      {detail.refreshError && (
        <p role="status" className="text-caption text-zoop-muted">
          새로 고치지 못했어요. 이전 결과를 표시해요.
        </p>
      )}
      <div className="flex items-start gap-2">
        <h2 id="round-title" className="min-w-0 flex-1 text-body font-bold">
          <span className="font-num">{round.roundId}</span>
          <span className="mt-0.5 block font-num text-caption font-normal text-zoop-muted">
            {formatKst(round.slotAt)}
          </span>
        </h2>
        <button
          type="button"
          aria-label="회차 상세 닫기"
          disabled={pending}
          onClick={onClose}
          className={BUTTON}
        >
          ×
        </button>
      </div>

      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-caption">
        <dt className="text-caption text-zoop-muted">단계</dt>
        <dd className="font-semibold">
          {graphRoundStageLabel[round.stage] ?? round.stage}
        </dd>
        {round.failureCode && (
          <>
            <dt className="text-caption text-zoop-muted">실패 사유</dt>
            <dd className="font-num break-all">{round.failureCode}</dd>
          </>
        )}
        <dt className="text-caption text-zoop-muted">시작</dt>
        <dd>
          {startedByLabel(round.startedBy)} · {formatKst(round.createdAt)}
        </dd>
        <dt className="text-caption text-zoop-muted">이 단계 시도</dt>
        <dd className="tabular-nums">
          {count(round.attempts)}회
          {round.nextAttemptAt &&
            ` · 다음 시도 ${formatKst(round.nextAttemptAt)}`}
        </dd>
        {round.lease && (
          <>
            <dt className="text-caption text-zoop-muted">처리 중</dt>
            <dd className="break-all">
              {round.lease.owner} · {formatKst(round.lease.until)}까지
            </dd>
          </>
        )}
        <dt className="text-caption text-zoop-muted">분석계획</dt>
        <dd className="font-num break-all">{round.plan?.planId ?? '–'}</dd>
        <dt className="text-caption text-zoop-muted">분석 작업</dt>
        <dd>
          {round.analysisJobId ? (
            <button
              type="button"
              disabled={pending}
              onClick={() => onOpenJob(round.analysisJobId as string)}
              className="font-num break-all underline underline-offset-4 disabled:opacity-60"
            >
              {round.analysisJobId}
            </button>
          ) : (
            '–'
          )}
        </dd>
        <dt className="text-caption text-zoop-muted">묶음(handoff)</dt>
        <dd className="font-num break-all">
          {round.handoff?.handoffId ?? '–'}
        </dd>
        <dt className="text-caption text-zoop-muted">수입한 버전</dt>
        <dd>
          {round.graphVersionId ? (
            <button
              type="button"
              disabled={pending}
              onClick={onOpenVersions}
              className="font-num break-all underline underline-offset-4 disabled:opacity-60"
            >
              {round.graphVersionId}
            </button>
          ) : (
            '–'
          )}
        </dd>
        {round.activatedVersionId && (
          <>
            <dt className="text-caption text-zoop-muted">공개한 버전</dt>
            <dd className="font-num break-all">
              {round.activatedVersionId}
              {round.activationNote && ` · ${round.activationNote}`}
            </dd>
          </>
        )}
        <dt className="text-caption text-zoop-muted">갱신</dt>
        <dd className="font-num tabular-nums">{formatKst(round.updatedAt)}</dd>
      </dl>

      {round.stage === 'failed' && !action && (
        <div className="flex flex-col gap-2">
          <div>
            <button
              type="button"
              disabled={pending}
              onClick={() => setAction({ kind: 'retry', round })}
              className={BUTTON}
            >
              재시도
            </button>
          </div>
          {caution && (
            <p role="note" className="text-caption text-zoop-muted">
              {caution}
            </p>
          )}
        </div>
      )}
      {action && (
        <GraphRoundActionForm
          action={action}
          onPendingChange={onPendingChange}
          onCancel={() => setAction(null)}
          onDone={(retried) => {
            setAction(null);
            detail.reload();
            onRetried(retried);
          }}
        />
      )}

      <Section title="단계별 기록">
        {events.length === 0 ? (
          <Empty>아직 기록이 없어요.</Empty>
        ) : (
          <Table caption="회차 이벤트">
            <thead>
              <tr>
                <th className={TH}>시각</th>
                <th className={TH}>단계</th>
                <th className={TH}>결과</th>
                <th className={TH}>코드·내용</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event: GraphRoundEvent) => (
                <tr key={event.id}>
                  <td
                    className={`${TD} whitespace-nowrap font-num tabular-nums`}
                  >
                    {formatKst(event.at)}
                  </td>
                  <td className={`${TD} whitespace-nowrap`}>
                    {graphRoundStageLabel[event.stage] ?? event.stage}
                  </td>
                  <td className={`${TD} whitespace-nowrap`}>
                    {outcomeLabel[event.outcome] ?? event.outcome}
                  </td>
                  <td className={`${TD} font-num text-caption break-all`}>
                    {event.code ?? '–'}
                    {event.detail && (
                      <span className="block text-zoop-muted">
                        {detailLine(event.detail)}
                      </span>
                    )}
                    {event.requestId && (
                      <span className="block text-zoop-faint">
                        요청 {event.requestId}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Section>
    </article>
  );
}
