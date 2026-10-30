import { useCallback, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import {
  getFeedbackSummary,
  listDislikedResults,
  listMaskedTranscripts,
} from '@/apis/admin/insights';
import {
  Empty,
  ErrorBox,
  Loading,
  MoreButton,
  Note,
  Section,
  Segmented,
  Table,
} from '@/components/admin/common/AdminUi';
import {
  BUTTON,
  FOCUS_RING,
  LINK,
  TD,
  TH,
  count,
  formatPercent,
} from '@/components/admin/common/adminStyles';
import { windowOptions } from '@/components/admin/stats/statsWindow';
import { useAsyncData } from '@/hooks/useAsyncData';
import { useCursorPages } from '@/hooks/useCursorPages';
import type { FeedbackPeriod, TranscriptFilter } from '@/types/admin/insights';
import { formatKst } from '@/util/format';
import { transcriptPath } from './transcriptPath';

const INPUT = `h-10 rounded-full border border-transparent bg-zoop-soft px-4 text-xs text-zoop-ink focus:border-zoop-ink ${FOCUS_RING}`;
const FIELD_LABEL = 'flex flex-col gap-1 text-[11px] text-zoop-muted';

/** 지금 적용된 기간을 한 줄로: 직접 고른 날짜가 있으면 그것, 아니면 미리 정한 기간 */
function periodText({ window, start, end }: FeedbackPeriod) {
  if (start || end) return `${start ?? '처음'} ~ ${end ?? '오늘'}`;
  if (window === 'all') return '전체 보관 기간';
  return `최근 ${windowOptions.find((option) => option.value === window)?.label}`;
}

function Votes({
  up,
  down,
  rate,
}: {
  up: number;
  down: number;
  rate?: number | null;
}) {
  return (
    <span className="whitespace-nowrap tabular-nums">
      {count(up)} / {count(down)}
      {rate != null && (
        <span className="ml-1 text-zoop-muted">({formatPercent(rate)})</span>
      )}
    </span>
  );
}

/** 시작·종료일 직접 지정(KST). 적용하면 미리 정한 기간 대신 쓰인다. */
export function DateRangeForm({
  start,
  end,
  onApply,
}: {
  start: string | null;
  end: string | null;
  onApply: (start: string | null, end: string | null) => void;
}) {
  const [from, setFrom] = useState(start ?? '');
  const [to, setTo] = useState(end ?? '');
  const invalid = from !== '' && to !== '' && from > to;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!invalid) onApply(from || null, to || null);
  }

  return (
    <form
      onSubmit={submit}
      aria-label="평가 기간 직접 지정"
      className="flex flex-wrap items-end gap-2"
    >
      <label className={FIELD_LABEL}>
        시작일(KST)
        <input
          type="date"
          value={from}
          max={to || undefined}
          onChange={(event) => setFrom(event.target.value)}
          className={`${INPUT} w-40 font-num`}
        />
      </label>
      <label className={FIELD_LABEL}>
        종료일(KST)
        <input
          type="date"
          value={to}
          min={from || undefined}
          onChange={(event) => setTo(event.target.value)}
          className={`${INPUT} w-40 font-num`}
        />
      </label>
      <button
        type="submit"
        disabled={invalid}
        className={`${BUTTON} h-9 border-zoop-ink`}
      >
        기간 적용
      </button>
      {(start || end) && (
        <button
          type="button"
          className={`${BUTTON} h-9`}
          onClick={() => {
            setFrom('');
            setTo('');
            onApply(null, null);
          }}
        >
          날짜 지정 해제
        </button>
      )}
      {invalid && (
        <p role="alert" className="basis-full text-[11px] text-zoop-alert">
          시작일이 종료일보다 늦어요.
        </p>
      )}
    </form>
  );
}

/** A-ADM-02b 요약: 기능별 좋아요 비율 · 일별 추이 (FS066-02) */
export function FeedbackSummaryPanel({ period }: { period: FeedbackPeriod }) {
  const { window, start, end } = period;
  const load = useCallback(
    () => getFeedbackSummary({ window, start, end }),
    [window, start, end],
  );
  const summary = useAsyncData(load);
  if (summary.status === 'loading')
    return <Loading>선호도를 불러오고 있어요</Loading>;
  if (summary.status === 'error')
    return (
      <ErrorBox
        title="선호도를 집계하지 못했어요"
        error={summary.error}
        onRetry={summary.reload}
      />
    );
  const data = summary.data;
  // 기능마다 날짜가 다를 수 있으니 모든 기능의 날짜를 모아 최신순으로 보여 준다.
  const dates = [
    ...new Set(
      data.features.flatMap((feature) => feature.days.map((day) => day.date)),
    ),
  ]
    .sort()
    .reverse();

  return (
    <>
      <div className="flex flex-col gap-1">
        <Note>
          기간 {periodText(data)}(평가를 마지막으로 바꾼 한국 시간 기준) · 집계
          시각 {formatKst(data.asOf)}
        </Note>
        <Note>
          {data.basis} (기준 표 {data.minSample}개)
        </Note>
      </div>
      <Section title="기능별 좋아요 비율">
        <Table caption="AI 기능별 좋아요·싫어요">
          <thead>
            <tr>
              <th className={TH}>기능</th>
              <th className={`${TH} text-right`}>좋아요</th>
              <th className={`${TH} text-right`}>싫어요</th>
              <th className={`${TH} text-right`}>표 합계</th>
              <th className={`${TH} text-right`}>좋아요 비율</th>
            </tr>
          </thead>
          <tbody>
            {data.features.map((feature) => (
              <tr key={feature.feature}>
                <td className={TD}>{feature.label}</td>
                <td className={`${TD} text-right tabular-nums`}>
                  {count(feature.up)}
                </td>
                <td className={`${TD} text-right tabular-nums`}>
                  {count(feature.down)}
                </td>
                <td className={`${TD} text-right tabular-nums`}>
                  {count(feature.total)}
                </td>
                <td className={`${TD} text-right`}>
                  {feature.total === 0 ? (
                    <span className="text-[11px] text-zoop-muted">
                      평가 없음
                    </span>
                  ) : feature.rate === null ? (
                    <span className="text-[11px] text-zoop-muted">
                      표본 부족({count(feature.total)}/{data.minSample})
                    </span>
                  ) : (
                    <span className="font-semibold tabular-nums">
                      {formatPercent(feature.rate)}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
        {data.unsupported.map((item) => (
          <Note key={item.feature}>
            ⓘ {item.label}: {item.reason}
          </Note>
        ))}
      </Section>
      <Section title="일별 추이">
        {dates.length === 0 ? (
          <Empty>이 기간에 바뀐 평가가 없어요.</Empty>
        ) : (
          <Table caption="일별 좋아요·싫어요">
            <thead>
              <tr>
                <th className={TH}>날짜(KST)</th>
                {data.features.map((feature) => (
                  <th key={feature.feature} className={`${TH} text-right`}>
                    {feature.label}
                    <span className="block text-[11px] font-normal">
                      좋아요 / 싫어요(비율)
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {dates.map((date) => (
                <tr key={date}>
                  <td className={`${TD} font-num tabular-nums`}>{date}</td>
                  {data.features.map((feature) => {
                    const day = feature.days.find((item) => item.date === date);
                    return (
                      <td key={feature.feature} className={`${TD} text-right`}>
                        <Votes
                          up={day?.up ?? 0}
                          down={day?.down ?? 0}
                          rate={day?.rate}
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Section>
    </>
  );
}

/** A-ADM-02b 싫어요 사유: 가명 사용자와 가린 사유. 챗봇 답변은 대화록으로 이어진다. */
export function DislikesPanel({
  period,
  purpose,
}: {
  period: FeedbackPeriod;
  purpose: string | null;
}) {
  const { window, start, end } = period;
  const load = useCallback(
    (cursor?: string) => listDislikedResults({ window, start, end }, cursor),
    [window, start, end],
  );
  const dislikes = useCursorPages(load);
  if (dislikes.status === 'loading')
    return <Loading>싫어요 사유를 불러오고 있어요</Loading>;
  if (dislikes.status === 'error' && dislikes.error)
    return (
      <ErrorBox
        title="싫어요 사유를 불러오지 못했어요"
        error={dislikes.error}
        onRetry={dislikes.reload}
      />
    );
  const rows = dislikes.items;
  if (rows.length === 0) return <Empty>이 기간에 싫어요가 없어요.</Empty>;

  return (
    <>
      <Note>
        싫어요 {count(dislikes.pages[0].total)}건 · 사유와 질문은 개인정보를
        가린 사본이에요.
      </Note>
      <Table caption="싫어요 사유">
        <thead>
          <tr>
            <th className={TH}>시각</th>
            <th className={TH}>기능</th>
            <th className={TH}>대상</th>
            <th className={TH}>사유</th>
            <th className={TH}>사용자</th>
            <th className={TH}>대화록</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.feature}-${row.targetId}-${row.voter}`}>
              <td className={`${TD} whitespace-nowrap font-num tabular-nums`}>
                {formatKst(row.at)}
              </td>
              <td className={`${TD} whitespace-nowrap`}>{row.featureLabel}</td>
              <td className={`${TD} max-w-72 text-zoop-muted`}>
                {row.targetLabel}
              </td>
              <td className={`${TD} max-w-96`}>
                {row.reason ?? (
                  <span className="text-zoop-faint">사유 없음</span>
                )}
              </td>
              <td className={`${TD} whitespace-nowrap font-num`}>
                {row.voter}
              </td>
              <td className={TD}>
                {row.sessionId ? (
                  <Link
                    to={transcriptPath(row.sessionId, purpose)}
                    className={LINK}
                  >
                    열람
                  </Link>
                ) : (
                  <span className="text-zoop-faint">–</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
      {dislikes.hasMore && (
        <MoreButton
          loading={dislikes.loadingMore}
          error={dislikes.moreError}
          onClick={dislikes.loadMore}
        />
      )}
    </>
  );
}

/** 열람 목적 입력. 승인된 목적 없이는 대화록을 요청하지 않는다(FS066-03). */
export function PurposeForm({
  purpose,
  onSubmit,
}: {
  purpose: string | null;
  onSubmit: (purpose: string) => void;
}) {
  const [value, setValue] = useState(purpose ?? '');
  const [missing, setMissing] = useState(false);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = value.trim();
    setMissing(!trimmed);
    if (trimmed) onSubmit(trimmed);
  }

  return (
    <form
      onSubmit={submit}
      noValidate
      aria-label="대화록 열람 목적"
      className="flex flex-wrap items-end gap-2"
    >
      <label className={`${FIELD_LABEL} min-w-60 flex-1`}>
        열람 목적
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="예: 싫어요 답변 품질 점검"
          aria-invalid={missing}
          className={INPUT}
        />
      </label>
      <button type="submit" className={`${BUTTON} h-9 border-zoop-ink`}>
        {purpose ? '목적 바꾸기' : '대화록 열기'}
      </button>
      {missing && (
        <p role="alert" className="basis-full text-[11px] text-zoop-alert">
          열람 목적을 입력해 주세요.
        </p>
      )}
    </form>
  );
}

/** A-ADM-02b AI 대화록 목록: 열람 권한·목적이 필요하고, 열람은 감사 기록에 남는다. */
export function TranscriptsPanel({
  only,
  purpose,
  onOnlyChange,
  onPurposeChange,
}: {
  only: TranscriptFilter;
  purpose: string | null;
  onOnlyChange: (only: TranscriptFilter) => void;
  onPurposeChange: (purpose: string) => void;
}) {
  return (
    <>
      <Note>
        대화록 열람은 별도 권한이 필요하고, 열람 목적과 함께 감사 로그에 남아요.
        개인정보는 가려서 보여 줘요.
      </Note>
      <PurposeForm
        key={purpose ?? ''}
        purpose={purpose}
        onSubmit={onPurposeChange}
      />
      <Segmented
        label="대화록 보기"
        value={only}
        options={[
          { value: 'all', label: '모든 대화' },
          { value: 'disliked', label: '싫어요가 있는 대화' },
        ]}
        onChange={onOnlyChange}
      />
      {purpose ? (
        <TranscriptList only={only} purpose={purpose} />
      ) : (
        <Empty>열람 목적을 입력하면 대화록 목록을 불러와요.</Empty>
      )}
    </>
  );
}

function TranscriptList({
  only,
  purpose,
}: {
  only: TranscriptFilter;
  purpose: string;
}) {
  const load = useCallback(
    (cursor?: string) => listMaskedTranscripts(only, purpose, cursor),
    [only, purpose],
  );
  const transcripts = useCursorPages(load);
  if (transcripts.status === 'loading')
    return <Loading>대화록을 불러오고 있어요</Loading>;
  if (transcripts.status === 'error' && transcripts.error)
    return (
      <ErrorBox
        title="대화록을 불러오지 못했어요"
        error={transcripts.error}
        onRetry={transcripts.reload}
      />
    );
  const rows = transcripts.items;
  if (rows.length === 0) return <Empty>조건에 맞는 대화가 없어요.</Empty>;

  return (
    <>
      <Note>대화 {count(transcripts.pages[0].total)}건</Note>
      <Table caption="AI 대화록">
        <thead>
          <tr>
            <th className={TH}>마지막 대화</th>
            <th className={TH}>사용자</th>
            <th className={TH}>첫 질문(가림)</th>
            <th className={`${TH} text-right`}>질문 수</th>
            <th className={`${TH} text-right`}>좋아요 / 싫어요</th>
            <th className={TH}>대화록</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td className={`${TD} whitespace-nowrap font-num tabular-nums`}>
                {formatKst(row.lastAt)}
              </td>
              <td className={`${TD} whitespace-nowrap font-num`}>
                {row.user}
                <span className="ml-2 font-sans text-zoop-muted">
                  {row.userKind === 'member' ? '회원' : '비회원'}
                </span>
              </td>
              <td className={`${TD} max-w-96`}>{row.preview}</td>
              <td className={`${TD} text-right tabular-nums`}>
                {count(row.messages)}
              </td>
              <td className={`${TD} text-right`}>
                <Votes up={row.up} down={row.down} />
              </td>
              <td className={TD}>
                <Link to={transcriptPath(row.id, purpose)} className={LINK}>
                  열람
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
      {transcripts.hasMore && (
        <MoreButton
          loading={transcripts.loadingMore}
          error={transcripts.moreError}
          onClick={transcripts.loadMore}
        />
      )}
    </>
  );
}
