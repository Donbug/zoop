import { useEffect, useState } from 'react';
import type { BriefingItem, BriefingResponse } from '@/types/briefing';
import type { BriefingImpacts, S3Assessment } from '@/types/briefing/impacts';
import { getBriefingItemImpacts } from '@/apis/briefing/impacts';
import { safeArticleUrl } from '@/components/graph/event-format';
import { briefingTime } from '@/util/briefingTime';
import { BODY, NOTE, FOCUS_RING } from './briefingStyles';
import ImpactCue from '@/components/common/ImpactCue';
import LoadingIndicator from '@/components/common/LoadingIndicator';
const labels = {
  positive: '긍정',
  negative: '부정',
  mixed: '긍정·부정 혼재',
  undetermined: '판단 보류',
};
const sides = {
  positive: '긍정 근거',
  negative: '부정 근거',
  neutral: '중립 근거',
  uncertain: '불확실한 근거',
};
const states: Record<Exclude<S3Assessment['status'], 'verified'>, string> = {
  'not-applicable': '해당 관계는 영향 평가 대상이 아닙니다.',
  'not-proposed': '저장된 영향 평가가 없습니다.',
  'no-evidence': '영향을 판단할 인용 근거가 부족합니다.',
  'technical-reject': '평가 결과를 검증할 수 없습니다.',
  'verifier-reject': '근거 확인을 통과하지 못해 판단을 보류했습니다.',
  withheld: '현재 공개 조건을 충족하지 않아 평가를 표시하지 않습니다.',
};

/** Mounted only after the parent issue is expanded; a route/version change discards late replies. */
export default function BriefingS3Impacts({
  round,
  item,
}: {
  round: BriefingResponse;
  item: BriefingItem;
}) {
  const key = JSON.stringify([
    round.id,
    item.eventId,
    round.graphVersion,
    round.dataAsOf,
  ]);
  const [stored, setValue] = useState<BriefingImpacts | null>(null);
  const value =
    stored &&
    stored.roundId === round.id &&
    stored.eventId === item.eventId &&
    stored.graphVersion === round.graphVersion &&
    Date.parse(stored.dataAsOf) === Date.parse(round.dataAsOf ?? '')
      ? stored
      : null;
  const [failed, setFailed] = useState<string | null>(null);
  const error = failed === key;
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    getBriefingItemImpacts(round, item)
      .then((v) => {
        if (active) setValue(v);
      })
      .catch(() => {
        if (active) setFailed(key);
      });
    return () => {
      active = false;
    };
  }, [round, item, attempt, key]);
  const retry = () => {
    setFailed(null);
    setValue(null);
    setAttempt((n) => n + 1);
  };
  return (
    <section
      aria-label="이슈별 S3 기업 영향"
      className="space-y-3 border-t border-zoop-border pt-4"
    >
      <h4 className="text-body font-bold">이 이슈의 기업별 영향</h4>
      {value?.reviewContext && (
        <span className="inline-flex rounded border border-zoop-border px-2 py-1 text-caption text-zoop-muted">
          발행 후 추가 평가
        </span>
      )}
      {error ? (
        <p role="status" className={NOTE}>
          기업별 영향을 불러오지 못했습니다.{' '}
          <button className={`underline ${FOCUS_RING}`} onClick={retry}>
            기업별 영향 다시 시도
          </button>
        </p>
      ) : !value ? (
        <LoadingIndicator
          label="기업별 영향을 불러오고 있습니다."
          className={`${NOTE} flex min-h-10 w-full`}
        />
      ) : value.companies.length === 0 ? (
        <p className={NOTE}>이 이슈에는 저장된 기업 영향 평가가 없습니다.</p>
      ) : (
        <>
          <p className={NOTE}>
            사업상 영향에 대한 근거 평가입니다. 주가 방향이나 뉴스로 인한 가격
            변동을 뜻하지 않습니다.
          </p>
          {value.companies.map((c) => (
            <section
              aria-label={`${c.companyName} S3 영향`}
              key={c.companyId}
              className="space-y-3 rounded border border-zoop-border p-3"
            >
              <h5 className="text-body font-semibold">{c.companyName}</h5>
              {c.assessments.length === 0 && (
                <p className={NOTE}>이 기업에 연결된 영향 평가가 없습니다.</p>
              )}
              {c.assessments.length > 1 && (
                <p className={NOTE}>
                  저장된 평가 {c.assessments.length}건을 각각 표시합니다. 하나의
                  방향으로 합치지 않습니다.
                </p>
              )}
              {c.assessments.map((a, i) => (
                <div className="space-y-2" key={a.id}>
                  {a.provenance.executionMode === 'replay' && (
                    <p className={NOTE}>
                      합성 재생 시험 결과 · 실제 자료의 AI 평가와 구분합니다.
                    </p>
                  )}
                  {a.provenance.sourceKind === 'synthetic' &&
                    a.provenance.executionMode === 'live' && (
                      <p className={NOTE}>
                        합성 자료를 사용한 AI 평가 · 실제 뉴스 평가와
                        구분합니다.
                      </p>
                    )}
                  {a.evidencePlan?.research?.timeCheck && (
                    <aside
                      aria-label="원문 발행 시각 점검"
                      className="space-y-2 rounded border border-zoop-border bg-zoop-card p-3"
                    >
                      <p className="text-caption font-semibold">
                        원문 발행 시각 확인 필요
                      </p>
                      <p className={BODY}>
                        {a.evidencePlan.research.timeCheck.summary}
                      </p>
                      <p className={NOTE}>
                        {a.evidencePlan.research.timeCheck.limitation}
                      </p>
                      <p className={NOTE}>
                        기존 뉴스·가격 시점 설명은 저장 당시 기준입니다. 공개
                        이후 반응으로 해석하기 전에 시각 확인이 필요합니다.
                      </p>
                      <p className={NOTE}>
                        저장된 출처{' '}
                        {briefingTime(
                          a.evidencePlan.research.timeCheck.storedPublishedAt,
                        )}{' '}
                        · 배포사 원문{' '}
                        {briefingTime(
                          a.evidencePlan.research.timeCheck
                            .distributionPublishedAt,
                        )}
                      </p>
                      <a
                        className={`text-caption underline ${FOCUS_RING}`}
                        href={safeArticleUrl(
                          a.evidencePlan.research.timeCheck.distributionUrl,
                        )!}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        배포사 시각 확인 ↗
                      </a>
                    </aside>
                  )}
                  {a.supplementalReview && (
                    <section
                      aria-label={`${c.companyName} 최신 재검증`}
                      className="space-y-3 rounded border border-zoop-border bg-zoop-card p-3"
                    >
                      <h6 className="text-body font-semibold">
                        <ImpactCue tone={a.supplementalReview.label} badge>
                          {labels[a.supplementalReview.label]} · 공식 근거 보강
                          후 재검증
                        </ImpactCue>
                      </h6>
                      <p className={NOTE}>
                        이전 {labels[a.supplementalReview.previousLabel]} →
                        재검증 {labels[a.supplementalReview.label]}
                        {' · '}
                        {briefingTime(a.supplementalReview.assessedAt)}
                      </p>
                      <p className={BODY}>{a.supplementalReview.summary}</p>
                      <p className="text-caption font-semibold">확인된 사실</p>
                      <ul className="list-disc space-y-2 pl-5">
                        {a.supplementalReview.confirmedFacts.map((f, index) => (
                          <li className={BODY} key={index}>
                            {f.text}
                          </li>
                        ))}
                      </ul>
                      <p className={NOTE}>{a.supplementalReview.limitations}</p>
                      <details>
                        <summary
                          className={`min-h-11 cursor-pointer content-center text-caption underline ${FOCUS_RING}`}
                        >
                          재검증에 사용한 인용·출처{' '}
                          {a.supplementalReview.evidence.length}건
                        </summary>
                        {a.supplementalReview.evidence.map((e) => (
                          <div
                            className="space-y-2 border-t border-zoop-border py-3"
                            key={e.id}
                          >
                            <p className="text-caption font-semibold">
                              <ImpactCue tone={e.effect}>
                                {sides[e.effect]}
                              </ImpactCue>
                            </p>
                            <blockquote
                              className={`${BODY} border-l-2 border-zoop-border pl-3`}
                            >
                              {e.quote}
                            </blockquote>
                            {safeArticleUrl(e.url) && (
                              <a
                                href={safeArticleUrl(e.url)!}
                                target="_blank"
                                rel="noopener noreferrer"
                                className={`text-caption underline ${FOCUS_RING}`}
                              >
                                {e.title} ↗
                              </a>
                            )}
                            <p className={NOTE}>
                              {briefingTime(e.publishedAt)}
                            </p>
                          </div>
                        ))}
                      </details>
                    </section>
                  )}
                  {(a.facts?.length ?? 0) > 0 && (
                    <section
                      aria-label={`${c.companyName} 확인된 사실`}
                      className="space-y-2"
                    >
                      <h6 className="text-caption font-semibold">
                        원문에서 확인된 내용
                      </h6>
                      <p className={BODY}>{item.title}</p>
                      {a.facts!.map((f) => (
                        <details key={f.id}>
                          <summary
                            className={`min-h-11 cursor-pointer content-center text-caption underline ${FOCUS_RING}`}
                          >
                            사실 근거 · {f.title}
                          </summary>
                          <blockquote
                            className={`${BODY} border-l-2 border-zoop-border pl-3`}
                          >
                            {f.quote}
                          </blockquote>
                          {safeArticleUrl(f.url) && (
                            <a
                              className={`text-caption underline ${FOCUS_RING}`}
                              href={safeArticleUrl(f.url)!}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              원문 보기 ↗
                            </a>
                          )}
                          <p className={NOTE}>{briefingTime(f.publishedAt)}</p>
                        </details>
                      ))}
                    </section>
                  )}
                  {a.status !== 'verified' ? (
                    <p className={NOTE}>{states[a.status]}</p>
                  ) : (
                    <>
                      <p className="text-body font-semibold">
                        <ImpactCue tone={a.label!} badge>
                          {a.supplementalReview ? '이전 검증 기록 · ' : ''}
                          {c.assessments.length > 1 ? `평가 ${i + 1} · ` : ''}
                          {labels[a.label!]} · 인용 근거 검증
                        </ImpactCue>
                      </p>
                      {a.label === 'undetermined' && (
                        <p className={NOTE}>
                          평가는 수행했지만 방향을 판단할 근거가 충분하지
                          않습니다.
                        </p>
                      )}
                      <details open={!a.facts?.length}>
                        <summary
                          className={`min-h-11 cursor-pointer content-center text-caption underline ${FOCUS_RING}`}
                        >
                          긍부정 검증 인용 {a.evidence.length}건
                        </summary>
                        {a.evidence.map((e) => (
                          <div key={e.id}>
                            <p className="text-caption font-semibold">
                              <ImpactCue tone={e.effect}>
                                {sides[e.effect]}
                              </ImpactCue>
                            </p>
                            <blockquote
                              className={`${BODY} border-l-2 border-zoop-border pl-3`}
                            >
                              {e.quote}
                            </blockquote>
                            {safeArticleUrl(e.url) && (
                              <a
                                className={`text-caption underline ${FOCUS_RING}`}
                                href={safeArticleUrl(e.url)!}
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                {e.title || '원문 보기'} ↗
                              </a>
                            )}
                            <p className={NOTE}>
                              {e.publishedAt
                                ? briefingTime(e.publishedAt)
                                : '발행 시각 정밀도 미확인'}
                            </p>
                          </div>
                        ))}
                      </details>
                    </>
                  )}
                  {a.evidencePlan && (
                    <details className="space-y-3">
                      <summary
                        className={`min-h-11 cursor-pointer content-center text-caption font-semibold underline ${FOCUS_RING}`}
                      >
                        보강한 근거·추가로 확인할 자료
                      </summary>
                      <p className={BODY}>{a.evidencePlan.reason}</p>
                      <p className={NOTE}>
                        {a.supplementalReview
                          ? '아래는 근거 보강 당시의 준비 기록입니다. 최신 독립 재검증 결과는 위에서 확인할 수 있습니다.'
                          : '기존 원문을 추가 정리한 자료입니다. AI 재평가 전이며, 위 긍부정 판정은 그대로 유지합니다.'}
                      </p>
                      {a.evidencePlan.research &&
                        a.evidencePlan.research.sources.length > 0 && (
                          <section
                            className="space-y-3 rounded border border-zoop-border bg-zoop-card p-3"
                            aria-label="새로 확인한 공식 자료"
                          >
                            <h6 className="text-caption font-semibold">
                              새로 연결한 공식 자료
                            </h6>
                            <p className={NOTE}>
                              {briefingTime(a.evidencePlan.research.linkedAt)}{' '}
                              {a.supplementalReview
                                ? '추가 확인 · 위 재검증에 사용한 공식 자료입니다. 당시 저장'
                                : '추가 확인 · AI 독립 검증 전입니다. 당시 저장'}
                              버전과 동일한지는 확인되지 않았으며 발행 당시
                              근거·긍부정 판정을 바꾸지 않습니다.
                            </p>
                            {a.evidencePlan.research.sources.map((source) => (
                              <div
                                key={source.id}
                                className="space-y-2 border-t border-zoop-border pt-3"
                              >
                                <p className={BODY}>{source.summary}</p>
                                <p className={NOTE}>{source.limitations}</p>
                                <details>
                                  <summary
                                    className={`min-h-11 cursor-pointer content-center text-caption underline ${FOCUS_RING}`}
                                  >
                                    공식 출처 · {source.title}
                                  </summary>
                                  <blockquote
                                    className={`${BODY} border-l-2 border-zoop-border pl-3`}
                                  >
                                    {source.excerpt}
                                  </blockquote>
                                  <a
                                    className={`text-caption underline ${FOCUS_RING}`}
                                    href={safeArticleUrl(source.url)!}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                  >
                                    공식 원문 보기 ↗
                                  </a>
                                  <p className={NOTE}>
                                    {source.timeBasis ===
                                    'SEC_index_accepted_America_New_York'
                                      ? 'SEC 접수 시각'
                                      : '발행 시각'}{' '}
                                    · {briefingTime(source.publishedAt)}
                                    {source.transport === 'web_tool_extract' &&
                                      ' · 공개 웹 도구로 확인한 본문 추출'}
                                  </p>
                                </details>
                              </div>
                            ))}
                          </section>
                        )}
                      <h6 className="text-caption font-semibold">
                        기존 자료로 보강한 내용
                      </h6>
                      <ul className="space-y-3">
                        {a.evidencePlan.existingEvidence.map((fact) => (
                          <li key={fact.source.id} className="space-y-1">
                            <p className={NOTE}>
                              {
                                {
                                  direct: '이슈 직접 근거',
                                  issuer_explanation: '회사 측 설명',
                                  conditional_risk: '조건부 위험',
                                  background: '기업·업종 배경',
                                }[fact.scope]
                              }{' '}
                              · {fact.note}
                            </p>
                            <details>
                              <summary
                                className={`min-h-11 cursor-pointer content-center text-caption underline ${FOCUS_RING}`}
                              >
                                보강 원문 · {fact.source.title}
                              </summary>
                              <blockquote
                                className={`${BODY} border-l-2 border-zoop-border pl-3`}
                              >
                                {fact.source.quote}
                              </blockquote>
                              {safeArticleUrl(fact.source.url) && (
                                <a
                                  className={`text-caption underline ${FOCUS_RING}`}
                                  href={safeArticleUrl(fact.source.url)!}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                >
                                  원문 보기 ↗
                                </a>
                              )}
                              <p className={NOTE}>
                                {briefingTime(fact.source.publishedAt)}
                              </p>
                            </details>
                          </li>
                        ))}
                      </ul>
                      <h6 className="text-caption font-semibold">
                        추가 확인과 향후 추적
                      </h6>
                      <ul className="space-y-3">
                        {a.evidencePlan.collectionNeeds.map((need) => (
                          <li key={need.what}>
                            <p className={BODY}>
                              {need.kind === 'future_followup'
                                ? '향후 추적'
                                : '당시 자료 추가 확인'}{' '}
                              · {need.what}
                            </p>
                            <p className={NOTE}>
                              {need.why} 확인처: {need.preferredSource}
                            </p>
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              ))}
            </section>
          ))}
        </>
      )}
      {value?.reviewContext && (
        <details className={NOTE}>
          <summary
            className={`min-h-11 cursor-pointer content-center underline ${FOCUS_RING}`}
          >
            평가 정보
          </summary>
          <p>
            평가 시각 {briefingTime(value.reviewContext.assessedAt)} · 발행 후
            추가로 평가한 결과입니다.
          </p>
        </details>
      )}
    </section>
  );
}

/** Full reading preserves the old layout and offers the same optional S3 data lazily. */
export function BriefingS3Disclosure({
  round,
  item,
}: {
  round: BriefingResponse;
  item: BriefingItem;
}) {
  const [open, setOpen] = useState(false);
  return (
    <details onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary
        className={`min-h-11 cursor-pointer content-center text-caption underline ${FOCUS_RING}`}
      >
        기업별 영향·근거 보기
      </summary>
      {open && (
        <BriefingS3Impacts
          key={`${round.id}:${item.eventId}:${round.graphVersion}`}
          round={round}
          item={item}
        />
      )}
    </details>
  );
}
