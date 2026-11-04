import { prioritySourceTime } from '@/util/briefingSourceTime';
import type {
  PersonalPriority,
  BriefingBusinessAnalysis,
} from '@/util/briefingPersonalPriority';
import { briefingTime } from '@/util/briefingTime';
import ImpactCue from '@/components/common/ImpactCue';
import { BODY, EMPTY, FOCUS_RING, NOTE } from './briefingStyles';

const labels = {
  new_issue: '새 소식',
  related_reference: '기존 이슈 관련 소식',
  previous_issue: '계속 확인할 이슈',
};
const directions = {
  positive: '긍정',
  negative: '부정',
  mixed: '긍정·부정 혼재',
  watch: '판단 유보',
};
const confidenceLabels = {
  limited: '제한적',
  moderate: '보통',
  high: '높음',
};
export function BusinessImpact({
  analysis,
  evening,
}: {
  analysis: BriefingBusinessAnalysis;
  evening: boolean;
}) {
  return (
    <section
      className="space-y-4"
      aria-label={`${analysis.companyName} AI 영향·전망`}
    >
      <h4 className="flex flex-wrap items-center gap-2 text-body font-bold">
        {analysis.companyName} ·{' '}
        {analysis.judgmentBasis ? '사업상 영향' : '내 종목 영향'}
        <ImpactCue tone={analysis.direction} badge>
          {directions[analysis.direction]}
        </ImpactCue>
      </h4>
      <p className={BODY}>{analysis.businessImpact}</p>
      {analysis.judgmentBasis && (
        <section
          className="rounded-lg bg-zoop-card p-4"
          aria-label="사업 판단의 근거와 한계"
        >
          <p className={NOTE}>
            판단 확신 {confidenceLabels[analysis.judgmentBasis.confidence]} ·{' '}
            {analysis.judgmentBasis.effectSizeStatus === 'unquantified'
              ? analysis.judgmentBasis.promptVersion ===
                'common-impact-relative-v1'
                ? '향후 추가 사업 효과 규모 미확인'
                : '효과 규모 미확인'
              : '효과 규모의 수치 근거 있음'}
          </p>
          <p className={`${BODY} mt-2`}>
            {analysis.judgmentBasis.directionReason}
          </p>
        </section>
      )}
      {analysis.recordReview && (
        <details className="rounded-lg border border-zoop-border p-4">
          <summary
            className={`cursor-pointer text-body font-bold ${FOCUS_RING}`}
          >
            판단 유보 이유 · 확인된 내용과 부족한 자료
          </summary>
          <p className={`${NOTE} mt-2`}>
            기존 생성 결과를 바꾸지 않고 저장 자료를 대조한 설명입니다.
          </p>
          <dl className="mt-3 space-y-3">
            <div>
              <dt className="text-body font-bold">확인된 내용</dt>
              <dd className={BODY}>{analysis.recordReview.knownFactor}</dd>
            </div>
            <div>
              <dt className="text-body font-bold">아직 모르는 부분</dt>
              <dd className={BODY}>{analysis.recordReview.missingData}</dd>
            </div>
            <div>
              <dt className="text-body font-bold">추가로 확인할 자료</dt>
              <dd className={BODY}>{analysis.recordReview.nextData}</dd>
            </div>
          </dl>
        </details>
      )}
      <div className="rounded-lg border border-zoop-border bg-zoop-card p-4">
        <h5 className="text-body font-bold">
          {evening ? '다음 거래일 전망' : '오늘의 전망'}
        </h5>
        <p className={`${BODY} mt-2`}>{analysis.outlook}</p>
      </div>
      {analysis.comparison && (
        <details className="rounded-lg border border-zoop-border p-4">
          <summary
            className={`cursor-pointer text-body font-bold ${FOCUS_RING}`}
          >
            기존 브리핑과 비교
          </summary>
          <p className={`${NOTE} mt-2`}>
            같은 회차를 새 기준으로 재분석했습니다. 새 뉴스로 인한 판단 변화와
            구분합니다.
          </p>
          {analysis.comparison.baseline ? (
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              <section>
                <h5 className="text-body font-bold">
                  기존 종합 판단 ·{' '}
                  {directions[analysis.comparison.baseline.direction]}
                </h5>
                <p className={`${BODY} mt-2`}>
                  {analysis.comparison.baseline.businessImpact}
                </p>
                <p className={`${BODY} mt-2`}>
                  {analysis.comparison.baseline.outlook}
                </p>
              </section>
              <section>
                <h5 className="text-body font-bold">
                  새 사업 영향 판단 · {directions[analysis.direction]}
                </h5>
                <p className={`${BODY} mt-2`}>{analysis.businessImpact}</p>
                <p className={`${BODY} mt-2`}>{analysis.outlook}</p>
              </section>
            </div>
          ) : (
            <p className={`${BODY} mt-3`}>
              기존 회차의 선정 목록에 없던 이슈입니다. 같은 이슈·기업의 비교
              대상이 없습니다.
            </p>
          )}
        </details>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        {analysis.positive &&
          !analysis.recordReview?.nonFactorFields?.includes('positive') && (
            <div className="rounded-lg border border-zoop-positive/20 bg-zoop-positive/5 p-4">
              <ImpactCue tone="positive">긍정 가능성</ImpactCue>
              <p className={`${BODY} mt-2`}>{analysis.positive}</p>
            </div>
          )}
        {analysis.negative &&
          !analysis.recordReview?.nonFactorFields?.includes('negative') && (
            <div className="rounded-lg border border-zoop-alert/20 bg-zoop-alert/5 p-4">
              <ImpactCue tone="negative">위험·불확실성</ImpactCue>
              <p className={`${BODY} mt-2`}>{analysis.negative}</p>
            </div>
          )}
      </div>
      <section>
        <h5 className="text-body font-bold">
          {evening ? '아침 판단 점검' : '이전 판단에서 달라진 점'}
        </h5>
        <p className={`${BODY} mt-2`}>{analysis.previousChange.text}</p>
      </section>
      {analysis.priceObservation && (
        <section>
          <h5 className="text-body font-bold">관측된 주가 흐름</h5>
          <p className={`${BODY} mt-2`}>{analysis.priceObservation}</p>
        </section>
      )}
      <section>
        <h5 className="text-body font-bold">다음 확인사항</h5>
        <p className={`${BODY} mt-2`}>{analysis.nextCheck}</p>
      </section>
      <details>
        <summary className={`cursor-pointer text-caption ${FOCUS_RING}`}>
          확인 사실·핵심 판단
        </summary>
        <p className={`${BODY} mt-2`}>{analysis.confirmedFact}</p>
        <p className={`${BODY} mt-2`}>{analysis.keyPoint}</p>
        {analysis.recordReview?.nonFactorFields?.map((field) => (
          <p key={field} className={`${NOTE} mt-2`}>
            기존 {field === 'positive' ? '긍정' : '위험'} 항목 문안 ·{' '}
            {analysis[field]}
          </p>
        ))}
      </details>
    </section>
  );
}

/** D-BRF-01/02: personal relevance is relative; repeats retain their original label. */
export default function PersonalPriorityIssues({
  value,
  evening = false,
}: {
  value: PersonalPriority;
  evening?: boolean;
}) {
  if (!value.items.length)
    return (
      <p className={EMPTY}>
        {value.status === 'no_companies'
          ? '보유·관심 종목을 등록하면 관련 이슈를 제공합니다.'
          : '선택 종목의 확인 가능한 자료를 확보하고 있습니다. 근거가 없는 이슈는 만들지 않습니다.'}
      </p>
    );
  return (
    <>
      <p className={`${NOTE} mb-3`}>
        선택 종목과 관련된 후보 안에서 우선순위를 정했습니다. 새 소식이 부족하면
        관련 소식이나 이전 이슈를 이어서 확인합니다.
      </p>
      <ol className="space-y-3">
        {value.items.map((item, index) => (
          <li key={item.issueId}>
            <details className="overflow-hidden rounded-xl border border-zoop-border bg-zoop-surface">
              <summary
                className={`cursor-pointer list-none p-5 sm:p-6 ${FOCUS_RING}`}
              >
                <span className="flex flex-wrap justify-between gap-2 text-caption text-zoop-muted">
                  <span>핵심 이슈 {index + 1} · 개인 종목 기준</span>
                  <span className="rounded-full bg-zoop-card px-3 py-1">
                    {labels[item.kind]}
                  </span>
                </span>
                <strong className="mt-3 block text-title-sm font-bold leading-snug">
                  {item.title}
                </strong>
                {item.topicTag && (
                  <span className="mt-2 inline-block rounded-full bg-zoop-card px-2 py-1 text-caption text-zoop-muted">
                    {item.topicTag}
                  </span>
                )}
                <span className="mt-3 block text-body leading-relaxed">
                  <b>
                    {item.aiAnalyses?.length
                      ? '내 종목 관점 · '
                      : '선정 이유 · '}
                  </b>
                  {item.aiAnalyses?.length
                    ? item.aiAnalyses.map((a) => a.forMyStocks).join(' ')
                    : item.reason}
                </span>
                <span className="mt-3 flex flex-wrap justify-between gap-2 text-caption text-zoop-muted">
                  <span>
                    {item.connections.map((c) => c.name).join(' · ')} · 근거{' '}
                    {item.sources.length}건
                  </span>
                  <span>자세히 보기 +</span>
                </span>
              </summary>
              <div className="space-y-5 border-t border-zoop-border p-5 sm:p-6">
                {item.analysisOmittedReason && !item.aiAnalyses?.length && (
                  <p className={NOTE}>
                    이전 분석에 별개 사건이 섞여 있어, 여기서는 원문으로 확인된
                    판결 사실만 제공합니다.
                  </p>
                )}
                {item.kind === 'previous_issue' && (
                  <p className={NOTE}>
                    {briefingTime(item.originCutoff)} 회차에서 다룬 이슈입니다.
                    이후 결과가 새로 확인됐다는 의미는 아닙니다.
                  </p>
                )}
                {item.kind === 'related_reference' && (
                  <p className={NOTE}>
                    기존 사건을 다룬 관련 보도입니다. 새로운 사건으로 집계하지
                    않습니다.
                  </p>
                )}
                {item.aiAnalyses?.map((analysis) => (
                  <BusinessImpact
                    key={analysis.companyId}
                    analysis={analysis}
                    evening={evening}
                  />
                ))}
                <section>
                  <h4 className="text-body font-bold">내 종목과의 연결</h4>
                  {item.connections.map((c) => (
                    <p className={`${BODY} mt-2`} key={c.companyId}>
                      <b>{c.name} · </b>
                      {c.reason}
                    </p>
                  ))}
                </section>
                <section>
                  <h4 className="text-body font-bold">확인된 보도와 근거</h4>
                  {item.sources.map((s) => (
                    <div className="mt-3 space-y-2" key={s.evidenceId}>
                      <blockquote
                        className={`${BODY} whitespace-pre-line border-l-2 border-zoop-border pl-3`}
                      >
                        {s.quote}
                      </blockquote>
                      <a
                        className={`text-caption underline ${FOCUS_RING}`}
                        href={s.url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {prioritySourceTime(s)} · 원문 보기 ↗
                      </a>
                    </div>
                  ))}
                </section>
                {item.price && (
                  <section className="rounded-lg border border-zoop-border p-3">
                    <h4 className="text-body font-bold">
                      {item.price.companyName} · 저장된 가격 관측
                    </h4>
                    <p className={`${BODY} mt-2`}>
                      {item.price.baseline} → {item.price.latest}{' '}
                      {item.price.currency} ({item.price.changeRate}%)
                    </p>
                    <p className={`${NOTE} mt-1`}>
                      {briefingTime(item.price.observedAt)} 기준 · 기업 공통
                      관측이며 개별 뉴스의 원인·효과를 입증하지 않습니다.
                    </p>
                  </section>
                )}
                {item.aiAnalyses?.length ? null : item.priorAnalysis.length ? (
                  item.priorAnalysis.map((analysis) => (
                    <section className="space-y-3" key={analysis.companyName}>
                      <h4 className="text-body font-bold">
                        {analysis.companyName} · 기존 검증 분석
                      </h4>
                      <p className={NOTE}>
                        {briefingTime(item.originCutoff)} 회차의 분석을 보존한
                        내용입니다.
                      </p>
                      <p className={BODY}>{analysis.takeaway}</p>
                      <div className="grid gap-3 sm:grid-cols-2">
                        {analysis.positive && (
                          <div className="rounded-lg border border-zoop-positive/20 bg-zoop-positive/5 p-4">
                            <ImpactCue tone="positive">긍정 가능성</ImpactCue>
                            <p className={`${BODY} mt-2`}>
                              {analysis.positive}
                            </p>
                          </div>
                        )}
                        {analysis.negative && (
                          <div className="rounded-lg border border-zoop-alert/20 bg-zoop-alert/5 p-4">
                            <ImpactCue tone="negative">위험·불확실성</ImpactCue>
                            <p className={`${BODY} mt-2`}>
                              {analysis.negative}
                            </p>
                          </div>
                        )}
                      </div>
                      {!!analysis.conditions.length && (
                        <div>
                          <h5 className="text-body font-bold">기존 확인사항</h5>
                          <ul className="mt-2 list-disc space-y-2 pl-5">
                            {analysis.conditions.map((text, i) => (
                              <li key={i} className={BODY}>
                                {text}
                              </li>
                            ))}
                          </ul>
                          <p className={`${NOTE} mt-2`}>
                            현재 회차에서 이행 여부를 새로 검증한 결과는
                            아닙니다.
                          </p>
                        </div>
                      )}
                    </section>
                  ))
                ) : (
                  <p className={NOTE}>
                    확인된 관련 소식입니다. 기업의 긍정·부정 영향에 대한 새로운
                    심층 분석은 아직 없습니다.
                  </p>
                )}
              </div>
            </details>
          </li>
        ))}
      </ol>
    </>
  );
}
