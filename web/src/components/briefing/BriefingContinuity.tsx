import { Link } from 'react-router-dom';
import type { BriefingContinuity as Continuity } from '@/types/briefing';
import { briefingTime } from '@/util/briefingTime';
import {
  BODY,
  EMPTY,
  FOCUS_RING,
  NOTE,
  SECTION,
  SECTION_TITLE,
} from './briefingStyles';

// D-BRF-01·02: reference news and old publications never become fresh headline facts.
export default function BriefingContinuity({
  value,
  compact,
}: {
  value: Continuity;
  compact: boolean;
}) {
  return (
    <section className={SECTION} aria-label="이번 회차 안내와 참고 브리핑">
      <h3 className={SECTION_TITLE}>
        {value.mode === 'reference'
          ? '핵심 이슈 대신 · 기업 참고 소식'
          : value.mode === 'recap'
            ? value.recap.status === 'available'
              ? '새 이슈 미선정 · 이전 이슈 복기'
              : '새 이슈 미선정 · 다음 확인 조건'
            : value.mode === 'validation_failed'
              ? '검증 미완료'
              : '수집·확인 범위 부족'}
      </h3>
      <p className={BODY}>
        {value.mode === 'recap' && value.recap.status === 'unavailable'
          ? '확인한 자료 범위에서 새 핵심·참고 이슈가 선정되지 않았습니다. 다음에 확인할 조건을 안내합니다.'
          : value.message}
      </p>
      <p role="note" className={`${EMPTY} mt-3`}>
        {value.coverage.message}
      </p>
      <div className="mt-4 flex flex-col gap-3">
        {value.references.map((item) => (
          <article
            key={item.issueId}
            className="rounded border border-zoop-border p-3"
          >
            <h4 className="text-body font-semibold">{item.title}</h4>
            <p className={NOTE}>
              {item.companies.map((company) => company.name).join(' · ')} ·{' '}
              {item.label}
            </p>
            {value.schemaVersion === 'importance-continuity-v2' &&
            item.sources[0] ? (
              <blockquote className={`${BODY} mt-2 whitespace-pre-wrap`}>
                {item.sources[0].quote}
              </blockquote>
            ) : (
              <p className={`${BODY} mt-2`}>
                전망·계획의 확정과 실제 이행 여부를 확인할 참고 자료입니다.
              </p>
            )}
            <details className="mt-2" open={compact ? undefined : true}>
              <summary
                className={`cursor-pointer text-caption underline ${FOCUS_RING}`}
              >
                원문 인용·출처 보기 · {item.sources.length}건
              </summary>
              {item.sources.map((source) => (
                <figure
                  key={source.evidenceId}
                  className="mt-3 border-l-2 border-zoop-border pl-3"
                >
                  <blockquote className={`${BODY} whitespace-pre-wrap`}>
                    {source.quote}
                  </blockquote>
                  <figcaption className={`${NOTE} mt-2`}>
                    보도 {briefingTime(source.dateContext.publishedAt)}
                    {' · '}
                    {source.url && /^https:\/\//.test(source.url) && (
                      <a
                        href={source.url}
                        target="_blank"
                        rel="noreferrer"
                        className={`underline ${FOCUS_RING}`}
                      >
                        원문 열기
                      </a>
                    )}
                  </figcaption>
                </figure>
              ))}
            </details>
          </article>
        ))}
      </div>
      <div className="mt-4">
        <h4 className="text-body font-semibold">이전 이슈 다시 보기</h4>
        <p className={NOTE}>{value.recap.message}</p>
        {value.recap.status === 'available' && (
          <>
            <p className={NOTE}>
              이전 기준 {briefingTime(value.recap.dataAsOf)} · 이번 회차의 새
              소식이 아닙니다.
            </p>
            <ul className="mt-2 list-disc pl-5">
              {value.recap.items.map((item) => (
                <li key={item.eventId} className={BODY}>
                  {item.title}
                  <details>
                    <summary
                      className={`cursor-pointer text-caption ${FOCUS_RING}`}
                    >
                      당시 요약 보기
                    </summary>
                    <p>
                      {'text' in item.summary
                        ? item.summary.text
                        : '당시 요약을 제공할 수 없습니다.'}
                    </p>
                  </details>
                </li>
              ))}
            </ul>
            <Link
              className={`mt-2 inline-block text-caption underline ${FOCUS_RING}`}
              to={`/briefing?date=${value.recap.date}&edition=${value.recap.edition}&reading=full`}
            >
              이전 브리핑 전문 보기
            </Link>
          </>
        )}
      </div>
      <div className="mt-4">
        <h4 className="text-body font-semibold">다음에 확인할 조건</h4>
        <ul className="mt-2 list-disc pl-5">
          {value.watchConditions.map((condition, index) => (
            <li key={`${condition.kind}:${index}`} className={BODY}>
              {condition.companyName && `${condition.companyName} · `}
              {condition.text}
              {condition.kind === 'previous_condition' && (
                <span className={NOTE}> (이전 회차의 확인 조건)</span>
              )}
            </li>
          ))}
        </ul>
        <p className={`${NOTE} mt-2`}>{value.forecast.message}</p>
      </div>
    </section>
  );
}
