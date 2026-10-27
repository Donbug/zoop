import { useAdminRefresh } from '@/hooks/useAdminRefresh';
import { useCallback, useState } from 'react';
import {
  getAdminBriefingRound,
  listAdminBriefingRounds,
} from '@/apis/admin/briefings';
import {
  Empty,
  ErrorBox,
  Loading,
  MoreButton,
  Note,
  PageHeader,
  Section,
  Table,
} from '@/components/admin/common/AdminUi';
import {
  BUTTON,
  FOCUS_RING,
  TD,
  TH,
  count,
} from '@/components/admin/common/adminStyles';
import {
  editionLabel,
  roundStatusLabel,
  stageStatusLabel,
} from '@/constants/adminLabels';
import { useAsyncData } from '@/hooks/useAsyncData';
import { useCursorPages } from '@/hooks/useCursorPages';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import type { RoundDetail as RoundDetailData } from '@/types/admin/briefings';
import { formatKst } from '@/util/format';
import RoundActionForm, { type RoundAction } from './RoundActionForm';

const STAGES = [
  ['generate', '생성'],
  ['verify', '검증'],
  ['publish', '발행'],
] as const;

const DD = 'text-xs';
const DT = 'text-[11px] text-zoop-muted';

function RoundDetailView({
  round,
  onAction,
}: {
  round: RoundDetailData;
  onAction: (action: RoundAction) => void;
}) {
  const items = round.published?.items ?? [];
  return (
    <>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
        <dt className={DT}>상태</dt>
        <dd className={`${DD} font-semibold`}>
          {roundStatusLabel[round.status]}
          {round.delayed && round.status !== 'missing' && (
            <span className="ml-2 font-normal text-zoop-alert">지연</span>
          )}
        </dd>
        <dt className={DT}>단계</dt>
        <dd className={DD}>
          <ul aria-label="단계별 상태" className="flex flex-wrap gap-3">
            {STAGES.map(([key, label]) => (
              <li key={key}>
                {label} {stageStatusLabel[round.stages[key].status]}
              </li>
            ))}
          </ul>
        </dd>
        <dt className={DT}>데이터 범위</dt>
        <dd className={`${DD} font-inter tabular-nums`}>
          {round.dataWindow.openStart
            ? '처음부터'
            : formatKst(round.dataWindow.start)}{' '}
          ~ {formatKst(round.dataWindow.end)}
        </dd>
        <dt className={DT}>발행</dt>
        <dd className={`${DD} font-inter tabular-nums`}>
          {round.publishedAt ? formatKst(round.publishedAt) : '–'}
          {round.graphVersion && (
            <span className="ml-2 text-zoop-muted">
              그래프 {round.graphVersion}
            </span>
          )}
        </dd>
        <dt className={DT}>시도</dt>
        <dd className={`${DD} tabular-nums`}>{count(round.attempts)}회</dd>
      </dl>
      {round.failureReason && (
        <p className="rounded-2xl bg-zoop-soft px-4 py-3 text-xs text-zoop-alert">
          실패 사유: {round.failureReason}
        </p>
      )}
      {round.suspension && (
        <p className="rounded-2xl bg-zoop-soft px-4 py-3 text-xs">
          제공 중단: {round.suspension.reason}{' '}
          <span className="text-[11px] text-zoop-muted">
            ({formatKst(round.suspension.at)} · {round.suspension.adminEmail})
          </span>
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 border-y-[0.667px] border-zoop-line py-3">
        <button
          type="button"
          disabled={!round.reprocessable}
          onClick={() => onAction('reprocess')}
          className={BUTTON}
        >
          재처리
        </button>
        <button
          type="button"
          disabled={!round.published}
          onClick={() => onAction('correct')}
          className={BUTTON}
        >
          정정 등록
        </button>
        {round.status === 'suspended' ? (
          <button
            type="button"
            onClick={() => onAction('resume')}
            className={BUTTON}
          >
            제공 재개
          </button>
        ) : (
          <button
            type="button"
            disabled={!round.published}
            onClick={() => onAction('suspend')}
            className={BUTTON}
          >
            제공 중단
          </button>
        )}
        {!round.reprocessable && round.blockedReason && (
          <p className="w-full text-[11px] text-zoop-muted">
            재처리할 수 없어요: {round.blockedReason}
          </p>
        )}
      </div>

      <Section title="발행 원문과 정정">
        {!round.published ? (
          <Empty>발행된 원문이 없어요.</Empty>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            <section
              aria-label="발행 원문"
              className="flex min-w-0 flex-col gap-2"
            >
              <h3 className="text-xs font-bold">발행 원문</h3>
              {items.length === 0 ? (
                <Empty>담긴 핵심 이슈가 없어요.</Empty>
              ) : (
                <ol className="flex flex-col">
                  {items.map((item) => (
                    <li
                      key={item.eventId}
                      className="flex flex-col gap-1 border-b-[0.667px] border-zoop-line py-2"
                    >
                      <p className="text-xs font-semibold">
                        <span className="text-zoop-muted tabular-nums">
                          {item.rank}.{' '}
                        </span>
                        {item.title}
                      </p>
                      <p className="text-[11px] text-zoop-muted">
                        {item.reason}
                      </p>
                    </li>
                  ))}
                </ol>
              )}
            </section>
            <section aria-label="정정" className="flex min-w-0 flex-col gap-2">
              <h3 className="text-xs font-bold">
                정정 {count(round.corrections.length)}
              </h3>
              {round.corrections.length === 0 ? (
                <Empty>등록된 정정이 없어요.</Empty>
              ) : (
                <ol className="flex flex-col">
                  {round.corrections.map((correction) => (
                    <li
                      key={correction.id}
                      className="flex flex-col gap-1 border-b-[0.667px] border-zoop-line py-2"
                    >
                      {correction.original && (
                        <p className="text-[11px] text-zoop-faint line-through">
                          원문: {correction.original}
                        </p>
                      )}
                      <p className="text-xs">정정: {correction.corrected}</p>
                      <p className="text-[11px] text-zoop-muted">
                        사유 {correction.reason} ·{' '}
                        {formatKst(correction.createdAt)} ·{' '}
                        {correction.adminEmail}
                      </p>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </div>
        )}
      </Section>

      <Section title="처리 기록">
        {round.attemptsLog.length === 0 ? (
          <Empty>아직 처리 기록이 없어요.</Empty>
        ) : (
          <Table caption="회차 처리 기록">
            <thead>
              <tr>
                <th className={TH}>#</th>
                <th className={TH}>시작</th>
                <th className={TH}>상태</th>
                <th className={TH}>요청</th>
                <th className={TH}>실패 사유</th>
              </tr>
            </thead>
            <tbody>
              {round.attemptsLog.map((attempt) => (
                <tr key={attempt.n}>
                  <td className={`${TD} tabular-nums`}>{attempt.n}</td>
                  <td
                    className={`${TD} whitespace-nowrap font-inter tabular-nums`}
                  >
                    {formatKst(attempt.startedAt)}
                  </td>
                  <td className={TD}>
                    {roundStatusLabel[
                      attempt.status as keyof typeof roundStatusLabel
                    ] ?? attempt.status}
                  </td>
                  <td className={`${TD} text-zoop-muted`}>
                    {attempt.trigger === 'scheduler'
                      ? '예약'
                      : (attempt.adminEmail ?? '관리자')}
                  </td>
                  <td className={`${TD} text-zoop-muted`}>
                    {attempt.failureReason ?? '–'}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Section>
    </>
  );
}

function RoundPanel({
  roundId,
  onClose,
  onChanged,
}: {
  roundId: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const load = useCallback(() => getAdminBriefingRound(roundId), [roundId]);
  const detail = useAsyncData(load);
  const [action, setAction] = useState<RoundAction | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const round = detail.data;
  useAdminRefresh(
    detail.reload,
    !action && round && ['generating', 'verifying'].includes(round.status)
      ? 5000
      : false,
  );

  return (
    <article aria-label="회차 상세" className="flex min-w-0 flex-col gap-4">
      {detail.refreshError && (
        <p role="status" className="text-[11px] text-zoop-muted">
          새로 고치지 못했어요. 이전 결과를 표시해요.
        </p>
      )}
      <div className="flex items-start gap-2">
        <h2 className="flex-1 text-sm font-bold tabular-nums">
          {round
            ? `${round.date} ${editionLabel[round.edition]} 브리핑`
            : '회차 상세'}
        </h2>
        <button
          type="button"
          onClick={onClose}
          className={`text-[11px] text-zoop-muted hover:text-zoop-ink ${FOCUS_RING}`}
        >
          닫기
        </button>
      </div>
      {done && (
        <p role="status" className="text-[11px] font-semibold">
          {done}
        </p>
      )}
      {detail.status === 'loading' && (
        <Loading>회차 상세를 불러오고 있어요</Loading>
      )}
      {detail.status === 'error' && (
        <ErrorBox
          title="회차 상세를 불러오지 못했어요"
          error={detail.error}
          onRetry={detail.reload}
        />
      )}
      {round && action && (
        <RoundActionForm
          key={action}
          round={round}
          action={action}
          onCancel={() => setAction(null)}
          onDone={(message) => {
            setAction(null);
            setDone(message);
            detail.reload();
            onChanged();
          }}
        />
      )}
      {round && (
        <RoundDetailView
          round={round}
          onAction={(next) => {
            setDone(null);
            setAction(next);
          }}
        />
      )}
    </article>
  );
}

// A-ADM-04 브리핑 운영 (FS070-01·02, FS071-01·02)
// - 회차별 데이터 기준 시점·생성/검증/발행 상태·실패 사유. 조회는 재처리나 발행을 하지 않는다.
// - 선택한 회차는 주소(?round=)에 남는다. 관리 작업은 사유를 받고, 끝나면 목록과 상세를 다시 읽는다.
export default function BriefingOperations() {
  const { params, updateQuery } = useRouteQuery();
  const selectedId = params.get('round');
  const rounds = useCursorPages(listAdminBriefingRounds);
  useAdminRefresh(
    rounds.reload,
    rounds.items.some((round) =>
      ['generating', 'verifying'].includes(round.status),
    )
      ? 5000
      : false,
  );
  const schedule = rounds.pages[0]?.schedule;

  return (
    <div className="flex flex-col gap-5 py-8 text-zoop-ink">
      <PageHeader
        title="브리핑 운영"
        actions={
          schedule && (
            <Note>
              예정 출근 {schedule.morning} · 퇴근 {schedule.evening} (
              {schedule.timezone === 'Asia/Seoul' ? 'KST' : schedule.timezone})
            </Note>
          )
        }
      />
      {rounds.refreshError && (
        <p role="status" className="text-[11px] text-zoop-muted">
          새로 고치지 못했어요. 이전 결과를 표시해요.
        </p>
      )}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(320px,440px)]">
        <div className="flex min-w-0 flex-col gap-3 self-start">
          {rounds.status === 'loading' && (
            <Loading>브리핑 회차를 불러오고 있어요</Loading>
          )}
          {rounds.status === 'error' && rounds.error && (
            <ErrorBox
              title="브리핑 회차를 불러오지 못했어요"
              error={rounds.error}
              onRetry={rounds.reload}
            />
          )}
          {rounds.status === 'success' && rounds.items.length === 0 && (
            <Empty>아직 브리핑 회차가 없어요.</Empty>
          )}
          {rounds.items.length > 0 && (
            <Table caption="브리핑 회차">
              <thead>
                <tr>
                  <th className={TH}>회차</th>
                  <th className={TH}>상태</th>
                  <th className={TH}>데이터 기준 시점</th>
                  <th className={TH}>실패 사유</th>
                  <th className={`${TH} text-right`}>정정</th>
                </tr>
              </thead>
              <tbody>
                {rounds.items.map((round) => {
                  const selected = round.id === selectedId;
                  return (
                    <tr
                      key={round.id}
                      aria-current={selected || undefined}
                      className="aria-[current]:bg-zoop-soft"
                    >
                      <td className={TD}>
                        <button
                          type="button"
                          aria-pressed={selected}
                          onClick={() =>
                            updateQuery({ round: round.id }, { replace: true })
                          }
                          className={`whitespace-nowrap rounded-full px-3 py-2 text-left font-semibold tabular-nums hover:bg-zoop-soft aria-pressed:bg-zoop-ink aria-pressed:text-zoop-paper ${FOCUS_RING}`}
                        >
                          {round.date} {editionLabel[round.edition]}
                        </button>
                      </td>
                      <td className={`${TD} whitespace-nowrap`}>
                        {roundStatusLabel[round.status]}
                        {round.delayed && round.status !== 'missing' && (
                          <span className="ml-1 text-zoop-alert">지연</span>
                        )}
                      </td>
                      <td
                        className={`${TD} whitespace-nowrap font-inter tabular-nums`}
                      >
                        {formatKst(round.dataWindow.end)}
                      </td>
                      <td className={`${TD} max-w-56 text-zoop-muted`}>
                        {round.failureReason ?? '–'}
                      </td>
                      <td className={`${TD} text-right tabular-nums`}>
                        {round.correctionCount > 0
                          ? count(round.correctionCount)
                          : '–'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          )}
          {rounds.hasMore && (
            <MoreButton
              loading={rounds.loadingMore}
              error={rounds.moreError}
              onClick={rounds.loadMore}
            />
          )}
        </div>
        <aside
          aria-label="선택한 회차"
          className="min-w-0 border-zoop-line lg:border-l-[0.667px] lg:pl-6"
        >
          {selectedId ? (
            <RoundPanel
              key={selectedId}
              roundId={selectedId}
              onClose={() => updateQuery({ round: null }, { replace: true })}
              onChanged={rounds.reload}
            />
          ) : (
            <div className="flex flex-col gap-1">
              <p className="text-sm font-bold">회차를 골라 주세요</p>
              <Note>발행 원문과 정정, 처리 기록을 보여 줘요.</Note>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
