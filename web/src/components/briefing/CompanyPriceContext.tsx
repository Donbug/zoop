import type {
  CompanyPriceContext as Context,
  PriceMarketReference as Market,
} from '@/types/briefing/priceContext';
import { briefingTime } from '@/util/briefingTime';
import { BODY, NOTE } from './briefingStyles';

/** D-BRF-01/02: derived observations augment the preserved business judgment and original prices. */
export default function CompanyPriceContext({
  context: c,
  evening,
}: {
  context: Context;
  evening: boolean;
}) {
  if (c.status === 'unavailable') return <p className={NOTE}>{c.reason}</p>;
  return (
    <section
      aria-label={`${c.companyName} 주가 흐름 분석`}
      className="rounded-lg border border-zoop-border p-3"
    >
      <h4 className="text-body font-semibold">실제 주가 흐름과 함께 읽기</h4>
      <p className={`${BODY} mt-2`}>{c.summary}</p>
      <p className={`${NOTE} mt-2`}>{c.flow}</p>
      <p className={`${NOTE} mt-2`}>
        토스증권 ·{' '}
        {c.day.kind === 'provider_daily_bar'
          ? '공급자 일봉'
          : '마감 전 완료 5분봉'}{' '}
        · {c.barCount}개 완료 봉
        {c.day.volume !== null &&
          ` · 거래량 ${Number(c.day.volume).toLocaleString('ko-KR')}`}
      </p>
      {evening && (
        <div className="mt-4">
          <h5 className="text-body font-semibold">아침 이후 실제 가격</h5>
          <p className={`${BODY} mt-2`}>{c.sinceMorning.observation}</p>
        </div>
      )}
      <div className="mt-4 space-y-3">
        <h5 className="text-body font-semibold">기사 발표 시각과 가격 관측</h5>
        {c.news.map((n) => (
          <div
            key={n.evidenceId}
            className="border-l-2 border-zoop-border pl-3"
          >
            <p className={NOTE}>
              기사 {briefingTime(n.publishedAt)} ·{' '}
              {n.timing === 'after_session'
                ? '이 관측 장 종료 이후 발표'
                : n.timing === 'before_session'
                  ? '이 관측 장 시작 전 발표'
                  : '장중 발표'}
            </p>
            <p className={`${BODY} mt-1`}>{n.observation}</p>
            {n.before && n.status === 'observed' && (
              <p className={`${NOTE} mt-1`}>
                가격 비교: {briefingTime(n.before.observedAt)} →{' '}
                {briefingTime(c.latest.observedAt)}
              </p>
            )}
          </div>
        ))}
      </div>
      <p className={`${BODY} mt-4`}>{c.interpretation}</p>
      <p className={`${NOTE} mt-2`}>{c.limitation}</p>
    </section>
  );
}

/** D-BRF-01/02: dated references, never synthetic previous-day returns or foreign-company benchmarks. */
export function PriceMarketReference({ reference: r }: { reference: Market }) {
  return (
    <section aria-label="전망에 함께 쓰는 시장 참고 지표">
      <ul className="mt-2 space-y-2">
        {r.indicators.map((i) => (
          <li key={i.id}>
            <p className={BODY}>{i.text}</p>
            <a
              className={`${NOTE} underline`}
              href={i.source.url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {i.source.name} ↗
            </a>
          </li>
        ))}
      </ul>
      {r.status === 'unavailable' && (
        <p className={NOTE}>회차 기준 시장 참고 지표를 확보하지 못했습니다.</p>
      )}
      <p className={`${NOTE} mt-2`}>{r.note}</p>
    </section>
  );
}
