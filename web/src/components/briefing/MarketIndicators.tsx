import type { BriefingResponse, MarketIndicator } from '@/types/briefing';
import { briefingTime } from '@/util/briefingTime';
import PanelDisclosure from '@/components/graph/PanelDisclosure';
import { safeArticleUrl } from '@/components/graph/event-format';
import {
  EMPTY,
  FOCUS_RING,
  NOTE,
  SECTION,
  SECTION_TITLE,
} from './briefingStyles';

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

// D-BRF-01·02: prototype features/briefing-market.tsx market information disclosure.
function MarketInfo({
  variables,
}: {
  variables: Extract<
    BriefingResponse['marketVariables'],
    { status: 'available' }
  >;
}) {
  const source = variables.indicators.find((item) => item.source)?.source;
  return (
    <PanelDisclosure
      label="시장 지표 안내"
      trigger={
        <span
          className="inline-flex min-h-11 min-w-11 items-center justify-center"
          aria-hidden="true"
        >
          ⓘ
        </span>
      }
    >
      <p className={NOTE}>
        이 회차를 만들 때 받은 값이고, 발행한 뒤에는 바뀌지 않아요.
      </p>
      {source && (
        <p className={NOTE}>
          출처 {source.name}
          {!source.official && ' · 비공식'}
          {source.delayNote && ` · ${source.delayNote}`}
        </p>
      )}
      <p className={NOTE}>
        값을 받은 시각 {briefingTime(variables.collectedAt ?? null)}
      </p>
      <ul>
        {variables.indicators.map((item) => {
          const href = safeArticleUrl(item.source?.url ?? null);
          return href ? (
            <li key={item.id}>
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`${labels[item.id]} 출처 열기 (새 창)`}
                className={`inline-flex min-h-11 items-center text-caption underline underline-offset-4 ${FOCUS_RING}`}
              >
                {labels[item.id]} 출처 ↗
              </a>
            </li>
          ) : null;
        })}
      </ul>
    </PanelDisclosure>
  );
}

/** 일별 값은 관측 날짜를 쓴다. 환율의 일별 고시값은 시장 종가와 구분한다. */
function observed(item: MarketIndicator) {
  const dailyReference = item.valueKind === 'reference' && !item.observedAt;
  const legacyBankReference =
    item.valueKind === 'close' &&
    item.id === 'usdkrw' &&
    item.source?.name.includes('하나은행');
  const at =
    (item.valueKind === 'close' || dailyReference) && item.observedDate
      ? item.observedDate
      : item.observedAt
        ? briefingTime(item.observedAt)
        : (item.observedDate ?? '시각 미상');
  const kind =
    dailyReference || legacyBankReference
      ? '일별 고시값'
      : item.valueKind === 'reference'
        ? '고시값'
        : item.valueKind === 'close'
          ? '종가'
          : '기준';
  return `${at} ${kind}`;
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
    <p className={`text-caption font-semibold tabular-nums ${tone}`}>
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
  compact = false,
  showBaseline = false,
}: {
  variables?: BriefingResponse['marketVariables'];
  compact?: boolean;
  showBaseline?: boolean;
}) {
  return (
    <section className={SECTION} aria-labelledby="market-indicators-title">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="market-indicators-title" className={SECTION_TITLE}>
          주요 시장 지표
        </h3>
        {variables?.status === 'available' && (
          <MarketInfo variables={variables} />
        )}
      </div>
      {variables?.status === 'unavailable' && (
        <p className={`${EMPTY} mb-3`}>{variables.reason}</p>
      )}
      <ul
        className={
          compact
            ? 'grid grid-cols-3 gap-2'
            : 'grid grid-cols-3 max-sm:grid-cols-1 max-sm:gap-4'
        }
      >
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
              className={
                compact
                  ? 'min-w-0 rounded-panel border border-panel-line p-2'
                  : 'min-h-[86px] min-w-0 border-r-[0.667px] border-zoop-line px-[18px] py-1 first:pl-0 last:border-r-0 last:pr-0 max-sm:border-r-0 max-sm:border-b-[0.667px] max-sm:px-0 max-sm:pb-4 max-sm:last:border-b-0'
              }
            >
              <p className="flex items-center gap-2">
                <strong className="text-caption">{label}</strong>
                {item && item.status !== 'ok' && (
                  <span className="text-caption font-semibold text-zoop-alert">
                    {statuses[item.status]}
                  </span>
                )}
              </p>
              {hasValue ? (
                <>
                  <p className={`${NOTE} mt-1`}>{observed(item)}</p>
                  {(!compact || showBaseline) && (
                    <p className={NOTE}>{baseline(item)}</p>
                  )}
                  <p
                    className={
                      compact
                        ? 'mt-2 text-lead font-bold tracking-tight tabular-nums'
                        : 'mt-3 mb-1 text-title font-[750] tracking-[-0.03em] tabular-nums'
                    }
                  >
                    {number(item.value!)}
                    {item.unit === 'KRW' ? '원' : ' pt'}
                  </p>
                  {compact ? (
                    <p
                      className={`mt-1 text-caption font-semibold tabular-nums ${item.changeRate !== null && item.changeRate < 0 ? 'text-zoop-down' : item.changeRate !== null && item.changeRate > 0 ? 'text-zoop-up' : 'text-zoop-muted'}`}
                    >
                      {item.changeRate === null
                        ? '등락률 미확인'
                        : `${item.changeRate > 0 ? '▲ ' : item.changeRate < 0 ? '▼ ' : ''}${signed(item.changeRate * 100)}%`}
                    </p>
                  ) : (
                    <Change item={item} />
                  )}
                  {item.reason && !compact && (
                    <p className={NOTE}>{item.reason}</p>
                  )}
                </>
              ) : (
                <p className={`${NOTE} mt-1`}>
                  {item?.reason ??
                    (variables
                      ? '이 회차에 저장된 지표가 없어요.'
                      : '지표 데이터 준비 중')}
                </p>
              )}
              {item && compact && (
                <details className="mt-2">
                  <summary
                    className={`min-h-11 cursor-pointer content-center text-caption text-zoop-muted ${FOCUS_RING}`}
                  >
                    출처·비교 기준
                  </summary>
                  <p className={NOTE}>{baseline(item)}</p>
                  {item.reason && <p className={NOTE}>{item.reason}</p>}
                  <Change item={item} />
                  {item.source && (
                    <p className={NOTE}>
                      {item.source.name}
                      {!item.source.official && ' · 비공식'}
                      {item.source.delayNote && ` · ${item.source.delayNote}`}
                    </p>
                  )}
                </details>
              )}
              {item?.source && !compact && (
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
