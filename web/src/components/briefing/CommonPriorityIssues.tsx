import { prioritySourceTime } from '@/util/briefingSourceTime';
import type { CommonPriority } from '@/util/briefingCommonPriority';
import { briefingTime } from '@/util/briefingTime';
import {
  BODY,
  EMPTY,
  FOCUS_RING,
  ISSUE_BODY,
  ISSUE_LIST,
  ISSUE_ROW,
  ISSUE_SUMMARY,
  NOTE,
} from './briefingStyles';
import { BusinessImpact } from './PersonalPriorityIssues';

const labels = {
  core: '주요 소식',
  relative_issue: '후보 내 우선 소식',
  related_reference: '관련 참고 소식',
  previous_issue: '이전 이슈 추적',
};

/** D-BRF-01/02: importance is relaxed; evidence, time and event identity are retained. */
export default function CommonPriorityIssues({
  value,
  evening = false,
}: {
  value: CommonPriority;
  evening?: boolean;
}) {
  return (
    <>
      <p className={`${NOTE} mb-3`}>
        중요도가 높은 소식부터 보여드립니다. 새 핵심 소식이 부족하면 확인 가능한
        참고 소식과 이전 이슈를 이어서 확인합니다.
      </p>
      {!value.items.length && (
        <p className={EMPTY}>
          현재 확인 가능한 자료가 부족합니다. 근거가 확보되는 대로 이슈를
          제공합니다.
        </p>
      )}
      {!!value.minimumShortfall && !!value.items.length && (
        <p className={NOTE}>
          확인 가능한 자료가 부족해 {value.items.length}개만 제공합니다.
        </p>
      )}
      <ol className={ISSUE_LIST}>
        {value.items.map((item, index) => (
          <li key={item.issueId} className={ISSUE_ROW}>
            <details>
              <summary className={`${ISSUE_SUMMARY} ${FOCUS_RING}`}>
                <span className="flex flex-wrap justify-between gap-2 text-caption text-zoop-muted">
                  <span>이슈 {index + 1} · 시장 전체 기준</span>
                  <span className="rounded-full bg-zoop-card px-3 py-1">
                    {labels[item.kind]}
                  </span>
                </span>
                <strong className="mt-3 block text-title-sm font-bold leading-snug">
                  {item.title}
                </strong>
                {item.topicTag && (
                  <span className="mt-2 inline-block rounded-full bg-zoop-card px-2 py-1 text-caption">
                    {item.topicTag}
                  </span>
                )}
                <span className="mt-3 block text-body leading-relaxed">
                  <b>선정 이유 · </b>
                  {item.reason}
                </span>
                <span className="mt-3 flex flex-wrap justify-between gap-2 text-caption text-zoop-muted">
                  <span>
                    {item.companies.map((c) => c.name).join(' · ')} · 근거{' '}
                    {item.sources.length}건
                  </span>
                  <span>자세히 보기 +</span>
                </span>
              </summary>
              <div className={ISSUE_BODY}>
                {item.aiAnalyses?.map((analysis) => (
                  <BusinessImpact
                    key={analysis.companyId}
                    analysis={analysis}
                    evening={evening}
                  />
                ))}
                {item.analysisWithheldReason && (
                  <p className={NOTE}>{item.analysisWithheldReason}</p>
                )}
                <section>
                  <h4 className="text-body font-bold">이번 회차에 보는 이유</h4>
                  <p className={`${BODY} mt-2`}>{item.whyNow}</p>
                  {item.kind === 'previous_issue' && (
                    <p className={`${NOTE} mt-2`}>
                      {briefingTime(item.originCutoff)} 회차에서 다룬
                      내용입니다. 후속 결과가 새로 확인됐다는 뜻은 아닙니다.
                    </p>
                  )}
                  <p className={`${NOTE} mt-2`}>
                    기존 중요도 평가 {item.importance}/3 · 근거 검증을 유지한
                    상대 우선순위입니다.
                  </p>
                </section>
                <section>
                  <h4 className="text-body font-bold">관련 기업과 연결 이유</h4>
                  {item.companies.map((c) => (
                    <p key={c.companyId} className={`${BODY} mt-2`}>
                      <b>{c.name} · </b>
                      {c.reason}
                    </p>
                  ))}
                </section>
                <section>
                  <h4 className="text-body font-bold">확인된 보도와 근거</h4>
                  {item.sources.map((s) => (
                    <div key={s.evidenceId} className="mt-3 space-y-2">
                      <blockquote
                        className={`${BODY} whitespace-pre-line border-l-2 border-zoop-border pl-3`}
                      >
                        {s.quote}
                      </blockquote>
                      <a
                        href={s.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={`text-caption underline ${FOCUS_RING}`}
                      >
                        {s.publisher ? `${s.publisher} · ` : ''}
                        {prioritySourceTime(s)} · 원문 보기 ↗
                      </a>
                    </div>
                  ))}
                </section>
                {!!item.prices.length && (
                  <section>
                    <h4 className="text-body font-bold">회차 기준 가격 관측</h4>
                    {item.prices.map((p) => (
                      <p key={p.companyName} className={`${BODY} mt-2`}>
                        {p.companyName} · {p.baseline} → {p.latest} {p.currency}{' '}
                        ({p.changeRate}%) · {briefingTime(p.observedAt)}
                      </p>
                    ))}
                    <p className={`${NOTE} mt-2`}>
                      저장된 관측이며 개별 뉴스의 가격 효과를 입증하지 않습니다.
                    </p>
                  </section>
                )}
              </div>
            </details>
          </li>
        ))}
      </ol>
    </>
  );
}
