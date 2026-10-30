import { validAiPriceOutlooks } from '@/util/aiPriceOutlook';
import type { AiPriceCompany } from '@/types/briefing/aiPriceOutlook';
import type { BriefingResponse } from '@/types/briefing';
import type { CompanyStatement } from '@/types/briefing/companyOutlook';
import type {
  EditionCompanyReview,
  EditionReview as Review,
} from '@/types/briefing/editionReview';
import {
  businessResult,
  marketCoverage,
  validEditionReview,
} from '@/util/editionReview';
import { briefingTime } from '@/util/briefingTime';
import {
  BODY,
  NOTE,
  SECTION,
  SECTION_TITLE,
  FOCUS_RING,
} from './briefingStyles';
import CompanyPrice from './CompanyPrice';
import CompanyPriceContext, {
  PriceMarketReference,
} from './CompanyPriceContext';
import { validPriceContext } from '@/util/briefingPriceContext';
import type { CompanyPriceContext as PriceContext } from '@/types/briefing/priceContext';
const stances = {
  priority_watch: '우선 관찰',
  watch: '관찰 유지',
  cautious_watch: '주의해서 관찰',
  deferred: '판단 유보',
};
const conditionLabels = {
  confirmed: '조건 관측',
  contradicted: '반대 근거 관측',
  not_observed: '미관측 · 평가 유보',
};

function Statement({
  value,
  review,
}: {
  value: CompanyStatement;
  review: Review;
}) {
  return (
    <div className="mt-2">
      <p className={BODY}>{value.text}</p>
      {value.evidenceIds.length > 0 && (
        <details className="mt-1">
          <summary
            className={`min-h-11 cursor-pointer content-center text-xs text-zoop-muted ${FOCUS_RING}`}
          >
            근거 {value.evidenceIds.length}건 · 원문 보기
          </summary>
          <ul className="space-y-3 border-l-2 border-panel-line pl-3">
            {value.evidenceIds.map((id) => {
              const s = review.sources[id];
              return (
                <li key={id}>
                  <a
                    className={`text-sm underline ${FOCUS_RING}`}
                    href={s.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {s.title} ↗
                  </a>
                  <p className={NOTE}>보도 {briefingTime(s.publishedAt)}</p>
                  <blockquote className={`${NOTE} mt-1`}>{s.quote}</blockquote>
                  {s.fullBody ? (
                    <details>
                      <summary
                        className={`min-h-11 cursor-pointer content-center text-xs ${FOCUS_RING}`}
                      >
                        전체 보존 원문
                      </summary>
                      <blockquote
                        className={`${NOTE} max-h-64 overflow-auto whitespace-pre-wrap`}
                      >
                        {s.fullBody}
                      </blockquote>
                    </details>
                  ) : (
                    <p className={NOTE}>
                      전체 본문은 포함되지 않았습니다. 원문 링크에서 확인해
                      주세요.
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </details>
      )}
    </div>
  );
}
function CompanyCard({
  company: c,
  review,
  compact,
  priceContext,
  ai,
}: {
  company: EditionCompanyReview;
  review: Review;
  compact: boolean;
  priceContext?: PriceContext;
  ai?: AiPriceCompany;
}) {
  const evening = review.edition === 'evening';
  return (
    <details
      open={!compact}
      aria-label={`${c.companyName} ${evening ? '하루 점검' : '오늘 관찰'}`}
      className="rounded-lg border border-zoop-line p-4"
    >
      <summary className={`cursor-pointer list-none ${FOCUS_RING}`}>
        <span className="flex flex-wrap gap-2">
          <strong className="text-base">{c.companyName}</strong>
          <span className="text-xs text-zoop-muted">{stances[c.stance]}</span>
          {ai && (
            <span className="text-xs text-zoop-accent">
              AI 전망 v5 · 검증 통과
            </span>
          )}
          <span className="ml-auto text-xs text-zoop-muted">자세히</span>
        </span>
        <span className="mt-2 block text-lg font-bold">{c.title.text}</span>
        <span className="mt-2 block text-sm text-zoop-muted">
          {ai
            ? c.takeaway.text
            : (priceContext?.outlook?.takeaway ?? c.takeaway.text)}
        </span>
        {evening && (
          <span className="mt-2 block text-xs">
            사업 조건: {businessResult(c)}
            {c.price.comparisonStatus === 'no_new_session'
              ? ' · 가격: 아침 이후 새 관측 없음'
              : ' · 가격은 별도 관측'}
          </span>
        )}
        {priceContext?.status === 'available' && (
          <span className="mt-2 block text-xs text-zoop-muted">
            {priceContext.sessionDate} · 토스{' '}
            {priceContext.latest.kind === 'daily_close' ? '종가' : '관측가'}{' '}
            {Number(priceContext.latest.value).toLocaleString('ko-KR')}{' '}
            {priceContext.currency}
            {priceContext.day.changeRatePercent !== null && (
              <>
                {' · '}
                {Number(priceContext.day.changeRatePercent) > 0 ? '+' : ''}
                {priceContext.day.changeRatePercent}%{' ('}
                {priceContext.day.baselineDate} 대비{')'}
              </>
            )}
          </span>
        )}
      </summary>
      <div className="mt-4 space-y-4 border-t border-zoop-line pt-3">
        {(ai?.previous.status === 'available' || (!ai && c.previous)) && (
          <div>
            <h4 className="text-sm font-semibold">
              {evening ? '아침의 실제 판단' : '전날의 실제 판단'}
            </h4>
            <p className={`${NOTE} mt-2`}>
              {ai
                ? (ai.previous.judgment?.outlook?.text ??
                  ai.previous.judgment?.judgment?.text)
                : c.previous?.judgment.text}
            </p>
          </div>
        )}
        <div>
          <h4 className="text-sm font-semibold">
            {c.role === 'selected' ? '새 정보' : '연결 자료의 확인 범위'}
          </h4>
          <Statement value={c.newInformation} review={review} />
        </div>
        <div>
          <h4 className="text-sm font-semibold">
            {ai
              ? 'AI 기업 전망 · 사업 판단과 실제 가격'
              : priceContext?.outlook
                ? '사업과 가격을 함께 본 기업 전망'
                : evening
                  ? '현재 사업 판단과 이유'
                  : '오늘의 관찰 입장과 이유'}
          </h4>
          <Statement
            value={ai?.outlook ?? priceContext?.outlook ?? c.judgment}
            review={review}
          />
          {priceContext?.outlook && (
            <p className={`${NOTE} mt-2`}>{priceContext.outlook.marketNote}</p>
          )}
        </div>
        {ai && (
          <div className="space-y-4">
            <div>
              <h4 className="text-sm font-semibold">사업상 의미</h4>
              <Statement value={ai.impact} review={review} />
            </div>
            <div>
              <h4 className="text-sm font-semibold">
                {evening
                  ? '아침 AI 판단과 비교'
                  : '직전 퇴근 AI 판단에서 달라진 점'}
              </h4>
              <Statement value={ai.comparison} review={review} />
            </div>
            <div>
              <h4 className="text-sm font-semibold">
                {evening ? '다음 거래일 확인 조건' : '오늘 확인할 조건'}
              </h4>
              {ai.conditions.map((s, i) => (
                <Statement key={i} value={s} review={review} />
              ))}
            </div>
            <div>
              <h4 className="text-sm font-semibold">판단을 약화시킬 요인</h4>
              {ai.risks.map((s, i) => (
                <Statement key={i} value={s} review={review} />
              ))}
            </div>
            <p className={NOTE}>
              실제 시세와 원문을 입력해 생성하고 별도 모델 호출로 검증했습니다.
              사업 조건의 실현과 가격 움직임은 별도이며 뉴스 인과·예측 적중을
              뜻하지 않습니다.
            </p>
          </div>
        )}
        {priceContext &&
          (priceContext.outlook ? (
            <details>
              <summary
                className={`min-h-11 cursor-pointer content-center text-xs text-zoop-muted ${FOCUS_RING}`}
              >
                가격 계산·기사 시각 자세히
              </summary>
              <CompanyPriceContext context={priceContext} evening={evening} />
            </details>
          ) : (
            <CompanyPriceContext context={priceContext} evening={evening} />
          ))}
        <details open={!ai}>
          {ai && (
            <summary
              className={`min-h-11 cursor-pointer content-center text-xs text-zoop-muted ${FOCUS_RING}`}
            >
              기존 편집 판단·조건·발행 시세 보존본
            </summary>
          )}
          <div className="space-y-4">
            {c.previous && (
              <div>
                <h4 className="text-sm font-semibold">
                  {evening ? '아침 확인 과제 점검' : '전날 확인 과제의 갱신'}
                </h4>
                <ul className="mt-2 space-y-3">
                  {c.checks.map((s, i) => (
                    <li key={`${s.condition}-${i}`}>
                      <p className="text-sm font-medium">{s.condition}</p>
                      <p className="mt-1 text-xs font-semibold">
                        {conditionLabels[s.status]}
                      </p>
                      <Statement value={s.observation} review={review} />
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div>
              <h4 className="text-sm font-semibold">
                {priceContext
                  ? '기존 발행본 시세·비교 기준'
                  : '실제 가격 관측 · 사업 조건 평가와 구분'}
              </h4>
              <CompanyPrice company={c} cutoff={review.cutoff} />
              {evening && c.price.comparisonStatus === 'available' && (
                <p className={`${NOTE} mt-2`}>
                  가격 변동은 실제 관측 결과입니다. 뉴스가 원인이라는 증거나
                  아침 판단의 적중을 뜻하지 않습니다.
                </p>
              )}
              {evening && !c.previous && (
                <p className={`${NOTE} mt-2`}>
                  아침에 이 기업의 판단이 없으므로 가격 비교를 전망 적중 평가로
                  사용하지 않습니다.
                </p>
              )}
            </div>
            <div>
              <h4 className="text-sm font-semibold">
                {evening ? '다음 거래일 확인 조건' : '오늘 확인할 조건'}
              </h4>
              {c.watch.map((s, i) => (
                <Statement key={i} value={s} review={review} />
              ))}
            </div>
            <div>
              <h4 className="text-sm font-semibold">판단을 높일 조건</h4>
              <Statement value={c.positive} review={review} />
            </div>
            <div>
              <h4 className="text-sm font-semibold">반대 시나리오</h4>
              <Statement value={c.negative} review={review} />
            </div>
          </div>
        </details>
      </div>
    </details>
  );
}

/** D-BRF-01/02: PM market review, morning-condition review, and next-session scenarios. */
export default function EditionReview({
  result,
  compact,
}: {
  result: BriefingResponse;
  compact: boolean;
}) {
  const r = validEditionReview(result);
  if (!r)
    return result.editionReview ? (
      <section className={SECTION}>
        <p className={NOTE}>
          출근·퇴근 분석의 회차·근거 연결을 확인하지 못했습니다. 아래 기존
          분석을 확인하세요.
        </p>
      </section>
    ) : null;
  const evening = r.edition === 'evening';
  const prices = validPriceContext(result);
  const ai = validAiPriceOutlooks(result);
  const coverage = marketCoverage(r);
  const current = r.companies.filter((c) =>
    evening ? !c.previous : c.role === 'selected',
  );
  const tracked = r.companies.filter((c) =>
    evening ? !!c.previous : c.role === 'tracked',
  );
  return (
    <section
      className={SECTION}
      aria-label={evening ? '퇴근 하루 평가 브리핑' : '출근 오늘 집중 브리핑'}
    >
      <h3 className={SECTION_TITLE}>
        {evening
          ? '오늘 장과 아침 판단을 점검합니다'
          : '오늘 어디에 집중할까요?'}
      </h3>
      {ai && (
        <p className={`${NOTE} mt-3`} role="status">
          {ai.status === 'PASS'
            ? 'AI 전망 v5 · 생성·독립 검증 통과 · 기업을 펼치면 실제 가격을 반영한 새 전망과 이전 AI 판단 비교를 볼 수 있습니다.'
            : 'AI 전망 v5는 근거 검증을 통과하지 못해 보류했습니다. 기존 검토본·시세·근거를 표시합니다.'}
        </p>
      )}
      {ai?.historyNote && <p className={`${NOTE} mt-2`}>{ai.historyNote}</p>}
      {result.aiPriceOutlooks && !ai && (
        <p className={`${NOTE} mt-3`} role="status">
          새 AI 전망의 회차·근거 연결을 확인하지 못했습니다. 기존 검토본을
          표시합니다.
        </p>
      )}
      <p className="mt-3 text-lg font-bold leading-snug">{r.headline}</p>
      <Statement value={r.summary} review={r} />
      {!evening && current.length > 0 && (
        <>
          <h3 className="mt-5 mb-3 text-sm font-bold">
            오늘 우선 볼 핵심 기업
          </h3>
          <div className="space-y-3">
            {current.map((c) => (
              <CompanyCard
                key={c.companyId}
                ai={
                  ai?.status === 'PASS'
                    ? ai.companies.find((x) => x.companyId === c.companyId)
                    : undefined
                }
                company={c}
                review={r}
                compact={compact}
                priceContext={prices?.companies.find(
                  (p) => p.companyId === c.companyId,
                )}
              />
            ))}
          </div>
        </>
      )}
      <div className="mt-5 rounded-lg border border-zoop-line p-3">
        <h3 className="text-sm font-bold">
          {evening ? '오늘 장 평가' : '시장 참고 기준'}
        </h3>
        <p className="mt-2 text-sm font-medium">{coverage.label}</p>
        {prices?.marketReference ? (
          <PriceMarketReference reference={prices.marketReference} />
        ) : (
          <ul className="mt-2 space-y-1">
            {coverage.indices.map((i) => (
              <li className={NOTE} key={i.id}>
                {i.label} · {i.observedDate} 종가{' '}
                {i.value?.toLocaleString('ko-KR')}pt
                {i.baseline && (
                  <>
                    {' '}
                    · {i.baseline.date} 대비{' '}
                    {i.changeRate === null
                      ? '변동 미확인'
                      : `${(i.changeRate * 100).toFixed(2)}%`}
                  </>
                )}
              </li>
            ))}
          </ul>
        )}

        <Statement value={r.marketInterpretation} review={r} />
        <p className={`${NOTE} mt-2`}>
          시장 전체 장중 흐름 · 업종 등락 · 수급 자료 없음
          {prices && ' · 기업별 거래 흐름은 기업 카드에서 확인'}
          {!coverage.dailyComparable && evening
            ? ' · 오늘 하루 강약 판정 유보'
            : ''}
        </p>
      </div>
      {!evening && (
        <div className="mt-5">
          <h3 className="text-sm font-bold">전날 판단에서 달라진 점</h3>
          <Statement value={r.comparison} review={r} />
        </div>
      )}
      {evening && (
        <div className="mt-5">
          <h3 className="text-sm font-bold">아침 기업 판단 점검</h3>
          <Statement value={r.comparison} review={r} />
          <p className={`${NOTE} mt-2`}>
            {r.previousReview
              ? `아침에 다룬 ${tracked.length}개 기업을 모두 이어서 점검합니다. 조건 미관측은 적중·실패로 평가하지 않습니다.`
              : '같은 날 출근 판단이 없어 아침과의 결과 비교를 할 수 없습니다.'}
          </p>
        </div>
      )}
      {evening && tracked.length > 0 && (
        <div className="mt-3 space-y-3">
          {tracked.map((c) => (
            <CompanyCard
              key={c.companyId}
              ai={
                ai?.status === 'PASS'
                  ? ai.companies.find((x) => x.companyId === c.companyId)
                  : undefined
              }
              company={c}
              review={r}
              compact={compact}
              priceContext={prices?.companies.find(
                (p) => p.companyId === c.companyId,
              )}
            />
          ))}
        </div>
      )}
      {evening && current.length > 0 && (
        <>
          <h3 className="mt-5 mb-3 text-sm font-bold">
            {evening
              ? '새 핵심 기업의 사업·가격 평가'
              : '오늘 우선 볼 핵심 기업'}
          </h3>
          <div className="space-y-3">
            {current.map((c) => (
              <CompanyCard
                key={c.companyId}
                ai={
                  ai?.status === 'PASS'
                    ? ai.companies.find((x) => x.companyId === c.companyId)
                    : undefined
                }
                company={c}
                review={r}
                compact={compact}
                priceContext={prices?.companies.find(
                  (p) => p.companyId === c.companyId,
                )}
              />
            ))}
          </div>
        </>
      )}
      {!evening && tracked.length > 0 && (
        <details className="mt-4">
          <summary
            className={`min-h-11 cursor-pointer content-center text-sm font-semibold ${FOCUS_RING}`}
          >
            이전 기업 확인 과제 {tracked.length}개 이어보기
          </summary>
          <div className="mt-2 space-y-3">
            {tracked.map((c) => (
              <CompanyCard
                key={c.companyId}
                ai={
                  ai?.status === 'PASS'
                    ? ai.companies.find((x) => x.companyId === c.companyId)
                    : undefined
                }
                company={c}
                review={r}
                compact={compact}
                priceContext={prices?.companies.find(
                  (p) => p.companyId === c.companyId,
                )}
              />
            ))}
          </div>
        </details>
      )}
      <div className="mt-5 border-t border-zoop-line pt-4">
        <h3 className="text-sm font-bold">
          {evening
            ? '다음 거래일 전망·확인 조건'
            : '오늘 확인할 사건·판단 변경 조건'}
        </h3>
        <Statement value={r.nextSession} review={r} />
        <p className={`${NOTE} mt-2`}>
          {evening
            ? '다음 거래일의 날짜·예정 일정은 아직 확인되지 않았습니다. 아래 전망은 조건부 관찰 시나리오입니다.'
            : '가격 수준·실적 기여 자료가 부족한 경우 매수 판단으로 확대하지 않습니다.'}
        </p>
      </div>
      <details className="mt-3">
        <summary
          className={`min-h-11 cursor-pointer content-center text-xs text-zoop-muted ${FOCUS_RING}`}
        >
          자료·작성 범위
        </summary>
        <p className={NOTE}>{r.scopeNote}</p>
        <p className={`${NOTE} mt-1`}>
          보존 원문과 가격을 대조해 직접 작성한 편집 검토본입니다. 이번 문안에
          새로운 모델 호출·독립 모델 검증은 사용하지 않았습니다.
        </p>
      </details>
    </section>
  );
}
