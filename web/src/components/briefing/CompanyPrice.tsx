import type { CompanyOutlook } from '@/types/briefing/companyOutlook';
import { briefingTime } from '@/util/briefingTime';
import { FOCUS_RING, NOTE } from './briefingStyles';

function value(price: string, currency: string) {
  return `${Number(price).toLocaleString('ko-KR', { maximumFractionDigits: 2 })}${currency === 'KRW' ? '원' : ' USD'}`;
}

/** Frozen per-edition observations; no request to a live quote endpoint during rendering. */
export default function CompanyPrice({
  company,
  cutoff,
}: {
  company: Pick<CompanyOutlook, 'companyId' | 'companyName' | 'price'>;
  cutoff: string;
}) {
  const price = company.price;
  if (
    price?.status === 'unavailable' &&
    price.companyId === company.companyId &&
    Date.parse(price.cutoff) === Date.parse(cutoff) &&
    ['provider_request_failed', 'provider_history_unverified'].includes(
      price.reason ?? '',
    )
  )
    return (
      <p className={`${NOTE} mt-3`}>
        {price.reason === 'provider_request_failed'
          ? '시세 공급자 요청에 실패해 기업 시세를 확인하지 못했습니다.'
          : '공급자 이력을 검증하지 못해 기업 시세를 확인하지 못했습니다.'}
      </p>
    );
  if (
    !price ||
    price.status !== 'available' ||
    !price.latest ||
    price.companyId !== company.companyId ||
    Date.parse(price.cutoff) !== Date.parse(cutoff) ||
    !Number.isFinite(Date.parse(price.latest.observedAt)) ||
    Date.parse(price.latest.observedAt) > Date.parse(cutoff)
  ) {
    return (
      <p className={`${NOTE} mt-3`}>
        회차 마감까지 확인된 기업 시세가 없습니다.
      </p>
    );
  }
  const { latest, baseline } = price;
  return (
    <div
      className="mt-3 rounded-panel border border-zoop-border bg-zoop-card p-3"
      aria-label={`${company.companyName} 회차 기준 시세`}
    >
      <p className="text-caption text-zoop-muted">
        {latest.kind === 'daily_close'
          ? '최근 정규장 종가'
          : '마감까지 완료된 5분봉 종가'}
      </p>
      <p className="mt-1 text-title-sm font-bold tabular-nums">
        {value(latest.value, price.currency)}
        {price.comparisonStatus === 'available' &&
          price.changeRate !== null && (
            <span className="ml-2 text-body font-medium">
              {Number(price.changeRate) > 0 ? '+' : ''}
              {price.changeRate}%
              <span className="ml-1 font-normal text-zoop-muted">
                (
                {price.baselineKind === 'morning_cutoff'
                  ? '아침 기준 대비'
                  : '전일 종가 대비'}
                )
              </span>
            </span>
          )}
      </p>
      <p className={NOTE}>관측 {briefingTime(latest.observedAt)}</p>
      {price.comparisonStatus === 'no_new_session' ? (
        <p className={`${NOTE} mt-1`}>
          아침 이후 새 정규장 관측 없음 · 가격 비교 보류
        </p>
      ) : baseline && price.baselineKind === 'morning_cutoff' ? (
        <p className={`${NOTE} mt-1`}>
          아침 {value(baseline.value, price.currency)} →{' '}
          {value(latest.value, price.currency)}
        </p>
      ) : null}
      <details className="mt-1">
        <summary
          className={`min-h-11 cursor-pointer content-center text-caption text-zoop-muted ${FOCUS_RING}`}
        >
          시세 시각·출처 확인
        </summary>
        <p className={NOTE}>
          관측 {briefingTime(latest.observedAt)} · 회차 마감{' '}
          {briefingTime(price.cutoff)}
        </p>
        {baseline && (
          <p className={NOTE}>
            비교 기준 {briefingTime(baseline.observedAt)} ·{' '}
            {baseline.kind === 'daily_close' ? '일별 종가' : '완료된 5분봉'}
          </p>
        )}
        <p className={NOTE}>{price.note}</p>
        <p className={NOTE}>
          실제 가격 변동은 사업 전망의 적중이나 이슈의 인과관계를 입증하지
          않습니다.
        </p>
        {price.sources.map((source) => (
          <p key={source.interval} className={NOTE}>
            <a
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
              className={`underline ${FOCUS_RING}`}
            >
              Yahoo Finance {source.interval} 원본 ↗
            </a>{' '}
            · 조회 {briefingTime(source.collectedAt)}
          </p>
        ))}
      </details>
    </div>
  );
}
