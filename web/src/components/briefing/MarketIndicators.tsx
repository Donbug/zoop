import type { BriefingResponse, MarketIndicator } from '@/types/briefing';
import { briefingTime } from '@/util/briefingTime';
import { EMPTY, NOTE, SECTION, SECTION_TITLE } from './briefingStyles';

const labels = { kospi: 'KOSPI', kosdaq: 'KOSDAQ', usdkrw: '원/달러' } as const;
// 정상(ok)은 따로 적지 않는다. 값이 없거나 늦은 경우만 상태를 밝힌다.
const statuses = {
  delayed: '지연',
  unavailable: '사용 불가',
  failed: '조회 실패',
};
const number = (value: number) =>
  value.toLocaleString('ko-KR', { maximumFractionDigits: 2 });
const signed = (value: number) => `${value > 0 ? '+' : ''}${number(value)}`;

/** 관측 시점: 종가면 날짜, 아니면 시각 */
function observed(item: MarketIndicator) {
  const at = item.observedAt
    ? briefingTime(item.observedAt)
    : (item.observedDate ?? '시각 미상');
  return `${at} ${item.valueKind === 'close' ? '종가' : '기준'}`;
}

function baseline(item: MarketIndicator) {
  if (!item.baseline) return '비교 기준 확인되지 않음';
  return `${item.baseline.at ? briefingTime(item.baseline.at) : item.baseline.date} 대비`;
}

/** 변동: 상승 빨강 ▲, 하락 파랑 ▼(국내 시세 관례). 등락률은 분수(0.0123=1.23%)로 온다. */
function Change({ item }: { item: MarketIndicator }) {
  if (item.change === null) return <p className={NOTE}>변동 확인되지 않음</p>;
  const tone =
    item.change > 0
      ? 'text-zoop-up'
      : item.change < 0
        ? 'text-zoop-down'
        : 'text-zoop-muted';
  const arrow = item.change > 0 ? '▲ ' : item.change < 0 ? '▼ ' : '';
  return (
    <p className={`text-[11px] font-semibold tabular-nums ${tone}`}>
      {arrow}
      {signed(item.change)}
      {item.unit === 'KRW' ? '원' : ''} (
      {item.changeRate === null
        ? '등락률 없음'
        : `${signed(item.changeRate * 100)}%`}
      )
    </p>
  );
}

// D-BRF-01·02 주요 시장 지표 (FS031). 발행 당시 저장한 값만 보여 주고 실시간 시세로 바꾸지 않는다.
export default function MarketIndicators({
  variables,
}: {
  variables?: BriefingResponse['marketVariables'];
}) {
  return (
    <section className={SECTION} aria-labelledby="market-indicators-title">
      <h3 id="market-indicators-title" className={SECTION_TITLE}>
        주요 시장 지표
      </h3>
      {variables?.status === 'unavailable' && (
        <p className={`${EMPTY} mb-3`}>{variables.reason}</p>
      )}
      <ul className="grid grid-cols-3 max-sm:grid-cols-1 max-sm:gap-4">
        {Object.entries(labels).map(([id, label]) => {
          const item =
            variables?.status === 'available'
              ? variables.indicators.find((entry) => entry.id === id)
              : undefined;
          const hasValue =
            item &&
            (item.status === 'ok' || item.status === 'delayed') &&
            item.value !== null;
          return (
            <li
              key={id}
              className="min-h-[86px] min-w-0 border-r-[0.667px] border-zoop-line px-[18px] py-1 first:pl-0 last:border-r-0 last:pr-0 max-sm:border-r-0 max-sm:border-b-[0.667px] max-sm:px-0 max-sm:pb-4 max-sm:last:border-b-0"
            >
              <p className="flex items-center gap-2">
                <strong className="text-xs">{label}</strong>
                {item && item.status !== 'ok' && (
                  <span className="text-[10px] font-semibold text-[#b42318]">
                    {statuses[item.status]}
                  </span>
                )}
              </p>
              {hasValue ? (
                <>
                  <p className={`${NOTE} mt-1`}>{observed(item)}</p>
                  <p className={NOTE}>{baseline(item)}</p>
                  <p className="mt-3 mb-1 text-2xl font-[750] tracking-[-0.03em] tabular-nums">
                    {number(item.value!)}
                    {item.unit === 'KRW' ? '원' : ' pt'}
                  </p>
                  <Change item={item} />
                  {item.reason && <p className={NOTE}>{item.reason}</p>}
                </>
              ) : (
                <p className={`${NOTE} mt-1`}>
                  {item?.reason ??
                    (variables
                      ? '이 회차에 저장된 지표가 없어요.'
                      : '지표 데이터 준비 중')}
                </p>
              )}
              {item?.source && (
                <p className={`${NOTE} mt-1 text-zoop-faint`}>
                  출처 {item.source.name}
                  {!item.source.official && ' · 비공식'}
                  {item.source.delayNote && ` · ${item.source.delayNote}`}
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
