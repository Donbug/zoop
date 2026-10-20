import { useId } from 'react';
import { Link } from 'react-router-dom';
import type {
  PreviousBriefingComparison,
  PreviousBriefingComparisonItem,
  SinceMorning,
  SinceMorningItem,
} from '@/types/briefing';
import { briefingTime } from '@/util/briefingTime';
import { formatKst } from '@/util/format';
import {
  EMPTY,
  FOCUS_RING,
  NOTE,
  SECTION,
  SECTION_TITLE,
} from './briefingStyles';

// 변화는 색이 아니라 글자 표지로 구분한다.
const changeLabel: Record<SinceMorningItem['change'], string> = {
  new: '신규',
  continuing: '이어짐',
  dropped: '빠짐',
};

/** 보도 시각: 같은 날이면 시:분, 다른 날이면 날짜(+시각), 날짜만 있으면 날짜만 */
function reported(iso: string | null, roundDate: string) {
  if (!iso) return '보도 시각 미상';
  const date = iso.slice(0, 10);
  if (iso.length <= 10) return `보도 ${date}`;
  const text = formatKst(iso);
  const day = text.slice(0, 10);
  const time = text.match(/(\d{2}:\d{2}) KST$/)?.[1];
  return day === roundDate && time ? `보도 ${time}` : `보도 ${text}`;
}

/** 둘째 줄: 근거 수 변화. 같은 제목이 여럿이면 관련 기업을 앞에 붙여 구분한다. */
function detail(item: PreviousBriefingComparisonItem, sharesTitle: boolean) {
  const count = (value: number | null) =>
    value === null ? '확인되지 않음' : `${value}건`;
  let evidence = `근거 ${count(item.evidenceCount)}`;
  if (item.change === 'dropped')
    evidence = `이번 회차 핵심 이슈에는 없어요 · 근거 ${count(item.previousEvidenceCount)}`;
  else if (
    item.change === 'continuing' &&
    item.previousEvidenceCount !== item.evidenceCount
  )
    evidence = `근거 ${count(item.previousEvidenceCount)} → ${count(item.evidenceCount)}`;
  if (!sharesTitle || item.companyNames.length === 0) return evidence;
  const names = item.companyNames;
  const companies = `관련 기업 ${names.slice(0, 3).join(', ')}${
    names.length > 3 ? ` 외 ${names.length - 3}곳` : ''
  }`;
  return `${companies} · ${evidence}`;
}

type Props = { roundDate?: string } & (
  | { basis?: 'morning'; since?: SinceMorning | null; previous?: never }
  | {
      basis: 'previous';
      previous?: PreviousBriefingComparison | null;
      since?: never;
    }
);

// D-BRF-01·02. 출근은 직전 퇴근, 퇴근은 같은 날 출근의 저장된 선정 목록을 비교한다.
// 신규/이어짐/빠짐은 비교 회차의 핵심 이슈 포함 여부이며 전망 적중이나 악재 해소가 아니다.
export default function BriefingComparison(props: Props) {
  const id = useId();
  const { roundDate } = props;
  const isPrevious = props.basis === 'previous';
  const comparison = isPrevious ? props.previous : props.since;
  const title = isPrevious ? '이전 퇴근 브리핑 대비' : '아침 대비 변화';
  const reference = isPrevious ? '이전 퇴근 브리핑' : '출근 브리핑';
  const available = comparison?.status === 'available' ? comparison : null;
  const items: PreviousBriefingComparisonItem[] = !available
    ? []
    : 'previousRoundId' in available
      ? available.items
      : available.items.map(
          ({ morningRank, morningEvidenceCount, ...item }) => ({
            ...item,
            previousRank: morningRank,
            previousEvidenceCount: morningEvidenceCount,
          }),
        );
  const heading = (
    <h3 id={id} className={SECTION_TITLE}>
      {title}
      {available && (
        <span className="ml-1.5 font-normal text-zoop-muted tabular-nums">
          {items.length}건
        </span>
      )}
    </h3>
  );

  if (comparison === undefined)
    return (
      <section className={SECTION} aria-labelledby={id}>
        {heading}
        <p className={EMPTY}>
          {reference}과 비교할 수 있도록 신규·이어짐·빠짐 이슈를 준비하고
          있어요.
        </p>
      </section>
    );

  if (!available)
    return (
      <section className={SECTION} aria-labelledby={id}>
        {heading}
        <p className={EMPTY}>
          {comparison?.status === 'unavailable'
            ? comparison.reason
            : isPrevious
              ? '이전 퇴근 브리핑과 비교한 정보가 없어요.'
              : '같은 날 출근 브리핑과 비교한 정보가 없어요.'}
        </p>
      </section>
    );

  const titleCount = new Map<string, number>();
  items.forEach((item) =>
    titleCount.set(item.title, (titleCount.get(item.title) ?? 0) + 1),
  );
  const previousDataAsOf =
    'previousDataAsOf' in available
      ? available.previousDataAsOf
      : available.morningDataAsOf;
  const previousPublishedAt =
    'previousPublishedAt' in available
      ? available.previousPublishedAt
      : available.morningPublishedAt;
  const referenceDate = isPrevious
    ? formatKst(previousDataAsOf).slice(0, 10)
    : roundDate;
  const referenceHref =
    referenceDate && /^\d{4}-\d{2}-\d{2}$/.test(referenceDate)
      ? `/briefing?date=${referenceDate}&edition=${isPrevious ? 'evening' : 'morning'}`
      : null;

  return (
    <section className={SECTION} aria-labelledby={id}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        {heading}
        {referenceHref && (
          <Link
            to={referenceHref}
            className={`text-[11px] text-zoop-muted underline underline-offset-4 hover:text-zoop-ink ${FOCUS_RING}`}
          >
            {reference} 보기
          </Link>
        )}
      </div>
      <p className={`${NOTE} mb-2`}>
        비교 회차 데이터 기준 {briefingTime(previousDataAsOf)} · 발행{' '}
        {briefingTime(previousPublishedAt)}
      </p>
      <p role="note" className={`${NOTE} mb-3`}>
        선정된 이슈 목록을 비교합니다. 신규·이어짐·빠짐은 중요 이슈 선정의
        변화이며, 빠짐이 악재나 사건의 해소를 뜻하지 않아요.
      </p>
      {'forecastEvaluation' in available && (
        <p className={`${NOTE} mb-3`}>
          전망 결과 평가: {available.forecastEvaluation.reason}
        </p>
      )}
      {items.length === 0 ? (
        <p className={EMPTY}>{reference}과 달라진 핵심 이슈가 없어요.</p>
      ) : (
        <ol aria-label={`${title} 목록`}>
          {items.map((item) => (
            <li
              key={`${item.change}-${item.eventId}`}
              className="flex gap-3 border-b-[0.667px] border-zoop-line py-3 last:border-b-0 max-sm:flex-col max-sm:gap-1"
            >
              <p className="w-28 shrink-0 font-inter text-[11px] text-zoop-muted tabular-nums">
                {reported(item.reportedAt, roundDate ?? '')}
              </p>
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <p className="flex flex-wrap items-start gap-x-2 gap-y-1">
                  <span
                    className={`shrink-0 rounded-full border-[0.667px] px-2 py-[2px] text-[10px] font-semibold ${
                      item.change === 'dropped'
                        ? 'border-zoop-line text-zoop-muted'
                        : 'border-zoop-ink text-zoop-ink'
                    }`}
                  >
                    {changeLabel[item.change]}
                  </span>
                  <span
                    className={`min-w-0 flex-1 text-[13px] font-semibold ${
                      item.change === 'dropped' ? 'text-zoop-muted' : ''
                    }`}
                  >
                    {item.title}
                  </span>
                </p>
                <p className={NOTE}>
                  {detail(item, (titleCount.get(item.title) ?? 0) > 1)}
                </p>
                {item.change === 'continuing' &&
                  item.previousRank !== null &&
                  item.rank !== null &&
                  item.previousRank !== item.rank && (
                    <p className={NOTE}>
                      선정 순위 {item.previousRank} → {item.rank}
                    </p>
                  )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
