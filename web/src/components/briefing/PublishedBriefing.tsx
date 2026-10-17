import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError } from '@/apis/auth/ApiService';
import { getBriefing } from '@/apis/briefing/briefing';
import { getMyFeedback } from '@/apis/feedback/feedback';
import FeedbackButtons from '@/components/common/FeedbackButtons';
import { usePersonalBriefing } from '@/hooks/usePersonalBriefing';
import { selectMemberId, useAuthStore } from '@/stores/useAuthStore';
import type { FeedbackValue } from '@/types/feedback';
import type { BriefingEdition, BriefingResponse } from '@/types/briefing';
import { briefingTime } from '@/util/briefingTime';
import MarketIndicators from './MarketIndicators';
import BriefingIssueList from './BriefingIssueList';
import BriefingComparison from './BriefingComparison';
import PersonalBasisNotice from './PersonalBasisNotice';
import {
  BODY,
  CARD,
  EMPTY,
  NOTE,
  FOCUS_RING,
  PRIMARY_BUTTON,
  SECTION,
  SECTION_TITLE,
  STATUS_PILL,
} from './briefingStyles';

const statuses = {
  published: '발행',
  not_ready: '발행 전',
  generating: '생성 중',
  failed: '생성 실패',
  suspended: '발행 중단',
};

/** 시각에서 KST 시:분만 */
function clock(value: string | null) {
  const text = briefingTime(value);
  return text.match(/(\d{2}:\d{2}) KST$/)?.[1] ?? text;
}

// D-BRF-01 출근 · D-BRF-02 퇴근 브리핑 한 회차 (FS028·029·030·031·033·035)
// - 퇴근 회차는 같은 날 출근 회차 대비 변화(sinceMorning)를 함께 보여 준다.
// - 페이지가 날짜·회차로 key를 주므로, 이전 회차 응답이 새 날짜 아래에 보이지 않는다.
// - 요청한 회차와 다른 응답(날짜·회차 불일치)은 쓰지 않는다.
// - 발행 원문은 그대로 두고 정정은 따로 덧붙인다. 실시간 시세로 바꾸지 않는다.
export default function PublishedBriefing({
  date,
  edition,
  personal = false,
}: {
  date: string;
  edition: BriefingEdition;
  /** 내 종목 기준 보기(FS036). 회원만 */
  personal?: boolean;
}) {
  const [result, setResult] = useState<BriefingResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    getBriefing(date, edition)
      .then((data) => {
        if (!active) return;
        if (data.edition !== edition || (date && data.date !== date))
          throw new Error('회차 불일치');
        setResult(data);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (!active) return;
        setResult(null);
        setError(
          cause instanceof ApiError && cause.status === 404
            ? '해당 회차가 아직 준비되지 않았어요.'
            : cause instanceof ApiError &&
                (cause.status === 401 || cause.status === 403)
              ? '이 회차를 조회할 권한이 없어요.'
              : '브리핑을 불러오지 못했어요. 다시 시도해 주세요.',
        );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [date, edition, retry]);
  const memberId = useAuthStore(selectMemberId);
  const checking = useAuthStore((s) => s.status === 'checking');
  const published = result?.status === 'published' ? result : null;
  const personalView = usePersonalBriefing(
    personal && memberId && published ? published : null,
  );
  const personalBriefing =
    personalView.state.status === 'ready' &&
    personalView.state.briefing?.id === published?.id
      ? personalView.state.briefing
      : null;
  // FS066-01: 이 회차와 핵심 이슈의 내 평가. 읽기 실패는 평가 없음과 구분하고, 확인 후 원하는 최종 상태로 저장한다.
  const [feedbackAttempt, setFeedbackAttempt] = useState(0);
  const [myFeedback, setMyFeedback] = useState<{
    key: string;
    error?: boolean;
    values: Record<string, FeedbackValue>;
  } | null>(null);
  const feedbackKey =
    // 결과 버전(graphVersion)이 없으면 평가를 버전에 연결할 수 없으므로 읽지도 않는다.
    published?.graphVersion && memberId
      ? `${memberId}:${published.id}:${published.graphVersion}:${retry}:${feedbackAttempt}`
      : null;
  useEffect(() => {
    if (!feedbackKey || !published) return;
    let active = true;
    const issueIds = published.items.map(
      (item) => `${published.id}/${item.eventId}`,
    );
    Promise.all([
      getMyFeedback('briefing_round', [published.id]),
      issueIds.length
        ? getMyFeedback('briefing_issue', issueIds)
        : Promise.resolve({ items: [], nextCursor: null }),
    ])
      .then(([round, issues]) => {
        if (
          [...round.items, ...issues.items].some(
            (item) => item.targetVersion !== published.graphVersion,
          )
        )
          throw new Error('다른 버전의 평가입니다.');
        return Object.fromEntries(
          [...round.items, ...issues.items].map((item) => [
            `${item.feature}:${item.targetId}`,
            item.value,
          ]),
        );
      })
      .then((values) => {
        if (active) setMyFeedback({ key: feedbackKey, values });
      })
      .catch(() => {
        if (active)
          setMyFeedback({ key: feedbackKey, values: {}, error: true });
      });
    return () => {
      active = false;
    };
  }, [feedbackKey, published]);
  const saved = (
    feature: string,
    targetId: string,
  ): FeedbackValue | undefined =>
    published?.graphVersion &&
    myFeedback?.key === feedbackKey &&
    !myFeedback.error
      ? (myFeedback?.values[`${feature}:${targetId}`] ?? 'none')
      : undefined;
  const reload = () => {
    setResult(null);
    setLoading(true);
    setError(null);
    setRetry((value) => value + 1);
  };
  // 제공 중단은 관리자가 푼 뒤에만 바뀌므로 다시 시도를 두지 않는다.
  const canRetry =
    !loading &&
    (error !== null ||
      (result !== null &&
        result.status !== 'suspended' &&
        (result.status !== 'published' ||
          result.metadata.failures.some((failure) => failure.retryable))));

  return (
    <article className={CARD} aria-busy={loading}>
      {loading && (
        <p role="status" className="text-xs text-zoop-muted">
          브리핑을 불러오고 있어요.
        </p>
      )}
      {error && (
        <p role="alert" className={EMPTY}>
          {error}
        </p>
      )}
      {result && (
        <>
          <header className="border-b-[0.667px] border-zoop-line pb-[18px]">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-bold tracking-[-0.025em]">
                {result.edition === 'morning' ? '출근' : '퇴근'} 브리핑
              </h2>
              <span className={STATUS_PILL}>{statuses[result.status]}</span>
            </div>
            <p className="mt-1.5 font-inter text-[10px] leading-normal text-zoop-faint">
              발행일 {result.date} · 예정 {clock(result.scheduledAt)} · 생성{' '}
              {briefingTime(result.generatedAt)} · 발행{' '}
              {briefingTime(result.publishedAt)} · 데이터 기준{' '}
              {briefingTime(result.dataAsOf)}
            </p>
          </header>
          {result.status === 'published' &&
            result.metadata.source === 'zoop-briefing-development-replay' && (
              <p
                role="note"
                aria-label="개발 재생 안내"
                className={`${EMPTY} mt-4`}
              >
                과거 수집 자료로 생성·검증한 개발 재생본입니다. 출근·퇴근은
                동일한 자료를 형식별로 작성했습니다.
              </p>
            )}
          {result.metadata.source ===
            'zoop-briefing-publication-clock-simulation' && (
            <p
              role="note"
              aria-label="회차별 과거 시뮬레이션 안내"
              className={`${EMPTY} mt-4`}
            >
              확인된 원발행 시각을 기준으로 회차별로 나눈 과거 시뮬레이션입니다.
              실제 수집은 나중에 이뤄졌으며, 당시 본문과 같은 버전인지는
              확인되지 않았습니다.
            </p>
          )}
          {result.notice && (
            <p className={`${EMPTY} mt-4`} role="status">
              {result.notice.message}
              {result.notice.reason && ` · ${result.notice.reason}`}
            </p>
          )}
          {result.status === 'published' && (
            <>
              {result.metadata.partial && (
                <div role="status" className={`${EMPTY} mt-4`}>
                  일부 정보를 불러오지 못했어요.
                  {result.metadata.failures.map((failure) => (
                    <p key={failure.section}>{failure.message}</p>
                  ))}
                </div>
              )}
              <section className={SECTION}>
                <h3 className={SECTION_TITLE}>시장 요약</h3>
                <p className={BODY}>
                  {'text' in result.marketSummary
                    ? result.marketSummary.text
                    : result.marketSummary.reason}
                </p>
              </section>
              <MarketIndicators variables={result.marketVariables} />
              {personal && (
                <PersonalBasisNotice
                  member={Boolean(memberId)}
                  checking={checking}
                  state={personalView.state}
                  dataAsOf={result.dataAsOf}
                  onRetry={personalView.reload}
                />
              )}
              {myFeedback?.key === feedbackKey && myFeedback?.error && (
                <p role="alert" className={EMPTY}>
                  내 평가를 불러오지 못해 평가 버튼을 잠시 사용할 수 없어요.{' '}
                  <button
                    type="button"
                    className={FOCUS_RING}
                    onClick={() => setFeedbackAttempt((value) => value + 1)}
                  >
                    내 평가 다시 확인
                  </button>
                </p>
              )}
              <BriefingIssueList
                items={(personalBriefing ?? result).items}
                graphHref={`/?round=${encodeURIComponent(result.id)}`}
                renderExtra={(item) => (
                  <div className="mt-1 flex flex-col gap-2">
                    <Link
                      to={`/?round=${encodeURIComponent(result.id)}&select=${encodeURIComponent(`node:${item.eventId}`)}`}
                      className={`self-start text-[11px] font-semibold underline underline-offset-4 ${FOCUS_RING}`}
                    >
                      이 회차 관계 그래프에서 보기
                    </Link>
                    {result.graphVersion && (
                      <FeedbackButtons
                        key={`${feedbackKey}:${item.eventId}`}
                        feature="briefing_issue"
                        targetId={`${result.id}/${item.eventId}`}
                        targetVersion={result.graphVersion}
                        subject={`핵심 이슈 ${item.rank}`}
                        saved={saved(
                          'briefing_issue',
                          `${result.id}/${item.eventId}`,
                        )}
                      />
                    )}
                  </div>
                )}
              />
              {result.edition === 'evening' && (
                <BriefingComparison
                  since={result.sinceMorning}
                  roundDate={result.date}
                />
              )}
              {result.corrections.length > 0 && (
                <section className={SECTION}>
                  <h3 className={SECTION_TITLE}>정정 이력</h3>
                  <ol className="flex flex-col gap-3">
                    {result.corrections.map((correction) => (
                      <li
                        key={correction.id}
                        className="flex flex-col gap-1 rounded-[3px] bg-zoop-wash p-3"
                      >
                        <p className={NOTE}>
                          정정 시각 {briefingTime(correction.createdAt)}
                        </p>
                        {correction.original && (
                          <p className="text-xs text-zoop-faint line-through">
                            발행 원문: {correction.original}
                          </p>
                        )}
                        <p className="text-xs">
                          정정 내용: {correction.corrected}
                        </p>
                        <p className={NOTE}>사유: {correction.reason}</p>
                      </li>
                    ))}
                  </ol>
                </section>
              )}
              <section className={SECTION} aria-label="이 브리핑 평가">
                <h3 className={SECTION_TITLE}>이 브리핑은 어땠나요?</h3>
                {result.graphVersion ? (
                  <FeedbackButtons
                    key={`${feedbackKey}:round`}
                    feature="briefing_round"
                    targetId={result.id}
                    targetVersion={result.graphVersion}
                    subject="이 브리핑 회차"
                    saved={saved('briefing_round', result.id)}
                  />
                ) : (
                  <p className={NOTE}>
                    이 회차는 결과 버전이 없어 평가를 남길 수 없어요.
                  </p>
                )}
              </section>
            </>
          )}
        </>
      )}
      {canRetry && (
        <button className={PRIMARY_BUTTON} type="button" onClick={reload}>
          다시 시도
        </button>
      )}
    </article>
  );
}
