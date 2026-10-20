import { Link } from 'react-router-dom';
import type { SinceMorning, SinceMorningItem } from '@/types/briefing';
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
function detail(item: SinceMorningItem, sharesTitle: boolean) {
  const count = (value: number | null) =>
    value === null ? '확인되지 않음' : `${value}건`;
  let evidence = `근거 ${count(item.evidenceCount)}`;
  if (item.change === 'dropped')
    evidence = `이번 회차 핵심 이슈에는 없어요 · 근거 ${count(item.morningEvidenceCount)}`;
  else if (
    item.change === 'continuing' &&
    item.morningEvidenceCount !== item.evidenceCount
  )
    evidence = `근거 ${count(item.morningEvidenceCount)} → ${count(item.evidenceCount)}`;
  if (!sharesTitle || item.companyNames.length === 0) return evidence;
  const names = item.companyNames;
  const companies = `관련 기업 ${names.slice(0, 3).join(', ')}${
    names.length > 3 ? ` 외 ${names.length - 3}곳` : ''
  }`;
  return `${companies} · ${evidence}`;
}

// D-BRF-02 아침 대비 변화 (FS029). 같은 날 발행된 출근 회차와 이슈 ID로 견준 결과를 시간순으로 보여 준다.
// - 신규: 아침 핵심 이슈에 없던 이슈 / 이어짐: 아침에도 있던 이슈 / 빠짐: 아침에만 있던 이슈
// - 출근 회차가 없거나 비교할 수 없으면 이유만 보여 준다. 회차를 받기 전에는 준비 중으로 둔다.
export default function BriefingComparison({
  since,
  roundDate,
}: {
  since?: SinceMorning | null;
  roundDate?: string;
}) {
  const heading = (
    <h3 id="briefing-comparison-title" className={SECTION_TITLE}>
      아침 대비 변화
      {since?.status === 'available' && (
        <span className="ml-1.5 font-normal text-zoop-muted tabular-nums">
          {since.items.length}건
        </span>
      )}
    </h3>
  );

  if (since === undefined)
    return (
      <section className={SECTION} aria-labelledby="briefing-comparison-title">
        {heading}
        <p className={EMPTY}>
          출근 브리핑과 비교할 수 있도록 신규·이어짐·빠짐 이슈를 준비하고
          있어요.
        </p>
      </section>
    );

  if (since === null || since.status === 'unavailable')
    return (
      <section className={SECTION} aria-labelledby="briefing-comparison-title">
        {heading}
        <p className={EMPTY}>
          {since?.reason ?? '같은 날 출근 브리핑과 비교한 정보가 없어요.'}
        </p>
      </section>
    );

  const titleCount = new Map<string, number>();
  since.items.forEach((item) =>
    titleCount.set(item.title, (titleCount.get(item.title) ?? 0) + 1),
  );

  return (
    <section className={SECTION} aria-labelledby="briefing-comparison-title">
      <div className="flex flex-wrap items-start justify-between gap-2">
        {heading}
        {roundDate && (
          <Link
            to={`/briefing?date=${roundDate}&edition=morning`}
            className={`text-[11px] text-zoop-muted underline underline-offset-4 hover:text-zoop-ink ${FOCUS_RING}`}
          >
            출근 브리핑 보기
          </Link>
        )}
      </div>
      {since.items.length === 0 ? (
        <p className={EMPTY}>출근 브리핑과 달라진 핵심 이슈가 없어요.</p>
      ) : (
        <ol aria-label="아침 대비 변화 목록">
          {since.items.map((item) => (
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
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
