import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { BriefingResponse } from '@/types/briefing';
import { validIssueFollowUps } from '@/util/issueFollowUps';
import {
  followUpKey,
  validIssueFollowUpReview,
} from '@/util/issueFollowUpReview';
import type { FollowUpReviewEntry } from '@/types/briefing/issueFollowUpReview';
import { safeArticleUrl } from '@/components/graph/event-format';
import { BODY, NOTE, SECTION, FOCUS_RING } from './briefingStyles';

export default function PriorIssueFollowUps({
  result,
}: {
  result: BriefingResponse;
}) {
  const [open, setOpen] = useState(false);
  const value = validIssueFollowUps(result);
  const review = validIssueFollowUpReview(result);
  const reviews = new Map(
    review?.entries.map((e) => [followUpKey(e.ref), e]) ?? [],
  );
  if (!result.issueFollowUps) return null;
  if (!value)
    return (
      <p role="alert" className={NOTE}>
        이전 확인사항의 회차·근거 연결을 확인하지 못했습니다. 현재 핵심 이슈는
        계속 볼 수 있습니다.
      </p>
    );
  if (!value.entries.length) return null;
  const groups = new Map<string, typeof value.entries>();
  for (const entry of value.entries) {
    const key = JSON.stringify([entry.issueId, entry.companyId]);
    groups.set(key, [...(groups.get(key) ?? []), entry]);
  }
  return (
    <section className={SECTION} aria-label="이전 이슈 확인사항">
      <details onToggle={(e) => setOpen(e.currentTarget.open)}>
        <summary
          className={`min-h-11 cursor-pointer content-center font-semibold ${FOCUS_RING}`}
        >
          이전 이슈에서 이어 볼 확인사항 · {value.entries.length}건
        </summary>
        {open && (
          <div className="mt-3 space-y-4">
            <p className={NOTE}>
              {review
                ? `조건 충족 확인 ${review.entries.filter((e) => e.status === 'fulfilled').length}건 · 자료 부족 ${review.entries.filter((e) => e.status === 'insufficient_evidence').length}건. 자료 부족은 조건이 실패했다는 뜻이 아닙니다.`
                : '이번 핵심 목록에서 빠진 이슈의 확인 조건입니다. 결과는 아직 확인하지 않았으며, 이전 판단을 현재 판단으로 갱신한 것은 아닙니다.'}
            </p>
            {result.issueFollowUpReview && !review && (
              <p role="alert" className={NOTE}>
                후속 검토의 회차·근거 연결을 확인하지 못해 원래 확인사항만
                표시합니다.
              </p>
            )}
            {[...groups].map(([key, entries]) => (
              <section
                key={key}
                className="rounded-xl border border-zoop-line p-4"
                aria-label={`${entries[0].title} · ${entries[0].companyName}`}
              >
                <h4 className="font-semibold">{entries[0].title}</h4>
                <p className={`${NOTE} mt-1`}>
                  {entries[0].companyName}
                  {review ? '' : ' · 결과 미확인'}
                </p>
                <ul className="mt-3 space-y-4">
                  {entries.map((entry) => (
                    <li key={entry.condition.text}>
                      <p className={BODY}>{entry.condition.text}</p>
                      <p className={`${NOTE} mt-1`}>
                        {entry.origin.date}{' '}
                        {entry.origin.edition === 'morning' ? '출근' : '퇴근'}에
                        제시한 조건
                        {' · '}
                        <Link
                          className={`underline ${FOCUS_RING}`}
                          to={`/briefing?date=${encodeURIComponent(entry.origin.date)}&edition=${entry.origin.edition}&reading=compact`}
                        >
                          이전 브리핑
                        </Link>
                      </p>
                      {reviews.get(followUpKey(entry)) && (
                        <FollowUpOutcome
                          entry={reviews.get(followUpKey(entry))!}
                        />
                      )}
                      <details className="mt-1">
                        <summary
                          className={`min-h-11 cursor-pointer content-center text-xs ${FOCUS_RING}`}
                        >
                          당시 근거 {entry.sources.length}건
                        </summary>
                        {entry.sources.map((source) => {
                          const url = safeArticleUrl(source.url);
                          return (
                            <div
                              className="mt-2 border-l-2 border-zoop-line pl-3"
                              key={source.evidenceId}
                            >
                              <blockquote className={BODY}>
                                {source.quote}
                              </blockquote>
                              {url ? (
                                <a
                                  href={url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className={`${NOTE} underline ${FOCUS_RING}`}
                                >
                                  {source.title} ↗
                                </a>
                              ) : (
                                <span className={NOTE}>{source.title}</span>
                              )}
                            </div>
                          );
                        })}
                      </details>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
            <p className={NOTE}>
              연결 범위: {value.reviewedRounds.length}개 이전 회차의 검증된
              기록.
              {review
                ? ' 저장 자료를 이 회차 마감 시점까지 대조한 검토입니다. 나중에 수집한 과거 자료이며, 원래 발행본과 판단은 유지합니다.'
                : ' 확인 완료·기한 경과를 자동 판정하지 않습니다.'}
            </p>
          </div>
        )}
      </details>
    </section>
  );
}

function FollowUpOutcome({ entry }: { entry: FollowUpReviewEntry }) {
  return (
    <div className="my-3 rounded-lg bg-zoop-wash p-3">
      <p className="text-sm font-semibold">
        {entry.status === 'fulfilled'
          ? '✓ 조건 충족 확인'
          : '○ 자료 부족 · 판단 보류'}
      </p>
      <p className={`${BODY} mt-2`}>{entry.summary}</p>
      {!!entry.facts.length && (
        <div className="mt-3">
          <p className="text-sm font-semibold">확인된 내용</p>
          <ul className={`${BODY} mt-1 list-disc space-y-1 pl-5`}>
            {entry.facts.map((f, n) => (
              <li key={n}>{f.text}</li>
            ))}
          </ul>
        </div>
      )}
      {entry.requirements.some((r) => r.observation === 'unverified') && (
        <div className="mt-3">
          <p className="text-sm font-semibold">충족 판단에 더 필요한 자료</p>
          <ul className={`${BODY} mt-1 list-disc space-y-1 pl-5`}>
            {entry.requirements
              .filter((r) => r.observation === 'unverified')
              .map((r, n) => (
                <li key={n}>{r.text}</li>
              ))}
          </ul>
        </div>
      )}
      {!!entry.sources.length && (
        <details className="mt-2">
          <summary
            className={`min-h-11 cursor-pointer content-center text-xs ${FOCUS_RING}`}
          >
            대조한 근거 {entry.sources.length}건
          </summary>
          {entry.sources.map((s) => {
            const url = safeArticleUrl(s.url);
            const facts = entry.facts.filter((f) => f.sourceIds.includes(s.id));
            return (
              <div key={s.id} className="mt-3 border-l-2 border-zoop-line pl-3">
                <p className={NOTE}>
                  {s.period === 'after_condition'
                    ? '조건 제시 이후 공개'
                    : '이전부터 알려진 배경'}
                  {s.relation === 'related_event' ? ' · 다른 사건 참고' : ''}
                  {' · '}
                  {new Date(s.publishedAt).toLocaleString('ko-KR', {
                    timeZone: 'Asia/Seoul',
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    hour12: false,
                  })}{' '}
                  KST
                </p>
                {facts.map((f, n) => (
                  <p className={`${BODY} mt-1`} key={n}>
                    {f.text}
                  </p>
                ))}
                <blockquote className={`${NOTE} mt-1`}>{s.quote}</blockquote>
                {url ? (
                  <a
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={`${NOTE} underline ${FOCUS_RING}`}
                  >
                    {s.title} ↗
                  </a>
                ) : (
                  <span className={NOTE}>{s.title}</span>
                )}
              </div>
            );
          })}
        </details>
      )}
    </div>
  );
}
