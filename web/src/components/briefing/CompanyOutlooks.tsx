import type { BriefingResponse } from '@/types/briefing';
import type {
  CompanyOutlook,
  CompanyStatement,
} from '@/types/briefing/companyOutlook';
import {
  BODY,
  FOCUS_RING,
  NOTE,
  SECTION,
  SECTION_TITLE,
} from './briefingStyles';
import { briefingTime } from '@/util/briefingTime';

const assessments = {
  positive: '사업상 긍정 요인',
  negative: '사업상 부담 요인',
  mixed: '긍정·부담 요인 혼재',
  watch: '추가 확인 필요',
};

function Statement({
  value,
  company,
}: {
  value: CompanyStatement;
  company: CompanyOutlook;
}) {
  const refs = company.sources.filter((s) =>
    value.evidenceIds.includes(s.evidenceId),
  );
  return (
    <div className="mt-2">
      <p className={BODY}>{value.text}</p>
      <details className="mt-1">
        <summary
          className={`min-h-11 cursor-pointer content-center text-xs text-zoop-muted ${FOCUS_RING}`}
        >
          근거 인용 {refs.length}개 · 원문{' '}
          {new Set(refs.map((s) => s.documentId)).size}건
        </summary>
        <ul className="space-y-3 border-l-2 border-panel-line pl-3">
          {refs.map((source) => (
            <li key={source.evidenceId}>
              <a
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                className={`text-sm underline ${FOCUS_RING}`}
              >
                {source.title} · 원문 ↗
              </a>
              <p className={NOTE}>
                발행 {briefingTime(source.publishedAt)} · 회차 마감 이전 자료
              </p>
              <blockquote className={`${NOTE} mt-1 whitespace-pre-wrap`}>
                {source.quote}
              </blockquote>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

/** D-BRF-01·02: selected-company outlooks lead; broad market context remains separate. */
export default function CompanyOutlooks({
  result,
  compact,
}: {
  result: Pick<
    BriefingResponse,
    'id' | 'edition' | 'dataAsOf' | 'items' | 'companyOutlooks'
  >;
  compact: boolean;
}) {
  const layer = result.companyOutlooks;
  if (!layer) return null;
  const expected = new Set(
    result.items.flatMap((item) => item.companies.map((c) => c.id)),
  );
  const matches =
    layer.schemaVersion === 'zoop-company-outlooks-v1' &&
    layer.roundId === result.id &&
    layer.edition === result.edition &&
    result.dataAsOf !== null &&
    Date.parse(layer.cutoff) === Date.parse(result.dataAsOf) &&
    (layer.status !== 'PASS' ||
      (new Set(layer.companies.map((c) => c.companyId)).size ===
        expected.size &&
        layer.companies.length === expected.size &&
        layer.companies.every((c) => expected.has(c.companyId))));
  return (
    <section className={SECTION} aria-label="핵심 이슈 기업별 전망">
      <p className={NOTE}>
        핵심 이슈에 연결된 기업 · 주가 신호와 구분한 사업 전망
      </p>
      <h3 className={`${SECTION_TITLE} mt-2`}>
        {result.edition === 'morning'
          ? '오늘의 기업별 전망'
          : '기업별 아침 판단 비교와 다음 전망'}
      </h3>
      {!matches || layer.status !== 'PASS' ? (
        <p className={NOTE}>
          {!matches
            ? '이 회차와 일치하는 기업 전망을 표시할 수 없습니다.'
            : layer.reason}
        </p>
      ) : (
        <div className="space-y-5">
          {layer.companies.map((company) => (
            <article
              key={company.companyId}
              className="rounded-panel border border-panel-line bg-panel-soft p-4"
            >
              <h4 className="text-lg font-bold">{company.companyName}</h4>
              <p className={`${NOTE} mt-1`}>
                {assessments[company.assessment]}
              </p>
              <Statement value={company.outlook} company={company} />
              <div className="mt-3">
                <h5 className="text-sm font-semibold">전망이 성립하려면</h5>
                {company.conditions.map((s, i) => (
                  <Statement key={i} value={s} company={company} />
                ))}
              </div>
              <details open={!compact} className="mt-3">
                <summary
                  className={`min-h-11 cursor-pointer content-center text-sm font-semibold ${FOCUS_RING}`}
                >
                  확인된 사실·사업 영향·반대 요인
                </summary>
                <h5 className="mt-2 text-sm font-semibold">확인된 사실</h5>
                {company.facts.map((s, i) => (
                  <Statement key={i} value={s} company={company} />
                ))}
                <h5 className="mt-3 text-sm font-semibold">
                  기업에 미치는 의미
                </h5>
                <Statement value={company.impact} company={company} />
                <h5 className="mt-3 text-sm font-semibold">
                  반대 요인·아직 모르는 부분
                </h5>
                {company.risks.map((s, i) => (
                  <Statement key={i} value={s} company={company} />
                ))}
              </details>
              <div className="mt-3 border-t border-panel-line pt-3">
                <h5 className="text-sm font-semibold">
                  {result.edition === 'morning'
                    ? '이전 기업 전망에서 달라진 점'
                    : '아침 판단과 실제 사업 정보 비교'}
                </h5>
                <Statement value={company.comparison} company={company} />
                <p className={NOTE}>
                  기업 주가 관측값이 없어 가격 흐름·예측 적중 여부는 평가하지
                  않았습니다.
                </p>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
