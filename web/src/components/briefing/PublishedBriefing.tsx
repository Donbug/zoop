import BriefingPreservedContext from './BriefingPreservedContext';
import { preservedPublication } from '@/util/preservedBriefing';
import { useEffect, useState } from 'react';
import { ApiError } from '@/apis/auth/ApiService';
import { getBriefing } from '@/apis/briefing/briefing';
import { getMyFeedback } from '@/apis/feedback/feedback';
import FeedbackButtons from '@/components/common/FeedbackButtons';
import BriefingPreviewFeedback from './BriefingPreviewFeedback';
import { validIssueIntelligence } from '@/util/issueIntelligence';
import LoadingIndicator from '@/components/common/LoadingIndicator';

import { selectMemberId, useAuthStore } from '@/stores/useAuthStore';
import type { FeedbackValue } from '@/types/feedback';
import type {
  BriefingEdition,
  BriefingItem,
  BriefingResponse,
} from '@/types/briefing';
import { briefingTime } from '@/util/briefingTime';
import BriefingTelemetry, { BriefingIssueMapLink } from './BriefingTelemetry';
import IssueCentricBriefing from './IssueCentricBriefing';
import { BriefingS3Disclosure } from './BriefingS3Impacts';
import BriefingReadingSection from './BriefingReadingSection';
import BriefingIssueList from './BriefingIssueList';
import BriefingRecap from './BriefingRecap';
import BriefingContinuity from './BriefingContinuity';
import BriefingComparison from './BriefingComparison';
import PersonalizedIssueSelection from './PersonalizedIssueSelection';
import ScheduledPersonalBriefing from './ScheduledPersonalBriefing';
import { BriefingCorrections, BriefingOutlook } from './BriefingPublishedNotes';
import { BRIEFING_DISCLAIMER, splitCorrections } from './briefingCorrections';
import { issueAnchor } from '@/util/briefingIssueView';
import { hasOnlyKnownLimitations } from './briefingLimitations';
import {
  CARD,
  EMPTY,
  NOTE,
  FOCUS_RING,
  PRIMARY_BUTTON,
  SECTION,
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
  compact = false,
}: {
  date: string;
  edition: BriefingEdition;
  /** 내 종목 기준 보기(FS036). 회원만 */
  personal?: boolean;
  compact?: boolean;
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
  const previewAnalysis =
    import.meta.env.VITE_BRIEFING_PREVIEW_FEEDBACK === 'true' && result
      ? validIssueIntelligence(result)
      : null;
  // FS066-01: 이 회차와 핵심 이슈의 내 평가. 읽기 실패는 평가 없음과 구분하고, 확인 후 원하는 최종 상태로 저장한다.
  const [feedbackAttempt, setFeedbackAttempt] = useState(0);
  const [myFeedback, setMyFeedback] = useState<{
    key: string;
    error?: boolean;
    values: Record<string, FeedbackValue>;
    reasons?: Record<string, string | null>;
  } | null>(null);
  const ratingVersion = published?.feedbackVersion ?? published?.graphVersion;
  const feedbackKey =
    // 발행 결과 식별 버전이 없으면 평가를 버전에 연결할 수 없으므로 읽지도 않는다.
    published && ratingVersion && memberId
      ? `${memberId}:${published.id}:${ratingVersion}:${retry}:${feedbackAttempt}`
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
            (item) => item.targetVersion !== ratingVersion,
          )
        )
          throw new Error('다른 버전의 평가입니다.');
        const items = [...round.items, ...issues.items];
        return {
          values: Object.fromEntries(
            items.map((item) => [
              `${item.feature}:${item.targetId}`,
              item.value,
            ]),
          ),
          reasons: Object.fromEntries(
            items.map((item) => [
              `${item.feature}:${item.targetId}`,
              item.reason,
            ]),
          ),
        };
      })
      .then((data) => {
        if (active) setMyFeedback({ key: feedbackKey, ...data });
      })
      .catch(() => {
        if (active)
          setMyFeedback({ key: feedbackKey, values: {}, error: true });
      });
    return () => {
      active = false;
    };
  }, [feedbackKey, published, ratingVersion]);
  const saved = (
    feature: string,
    targetId: string,
  ): FeedbackValue | undefined =>
    ratingVersion && myFeedback?.key === feedbackKey && !myFeedback.error
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

  const publicationInfo = result && (
    <>
      <p className="mt-1.5 font-num text-caption leading-normal text-zoop-faint">
        발행일 {result.date} · 예정 {clock(result.scheduledAt)} · 생성{' '}
        {briefingTime(result.generatedAt)} · 발행{' '}
        {briefingTime(result.publishedAt)} · 데이터 기준{' '}
        {briefingTime(result.dataAsOf)}
      </p>
      {result.status === 'published' &&
        result.metadata.source === 'zoop-briefing-development-replay' && (
          <p
            role="note"
            aria-label="개발 재생 안내"
            className={`${EMPTY} mt-4`}
          >
            과거 수집 자료로 생성·검증한 개발 재생본입니다. 출근·퇴근은 동일한
            자료를 형식별로 작성했습니다.
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
          실제 수집은 나중에 이뤄졌으며, 당시 본문과 같은 버전인지는 확인되지
          않았습니다.
        </p>
      )}
    </>
  );
  const knownLimits =
    result && hasOnlyKnownLimitations(result.metadata.failures);
  const partialInfo = result?.metadata.partial && (
    <div role={knownLimits ? 'note' : 'status'} className={`${EMPTY} mt-4`}>
      {knownLimits
        ? '이 회차 자료의 확인 범위'
        : '일부 정보를 불러오지 못했어요.'}
      {result.metadata.failures.map((failure) => (
        <p key={failure.section}>{failure.message}</p>
      ))}
    </div>
  );

  const issueExtra = (item: BriefingItem) =>
    result && (
      <div className="mt-1 flex flex-col gap-2">
        {!compact && <BriefingS3Disclosure round={result} item={item} />}
        {!result.issueIntelligence && (
          <BriefingIssueMapLink
            roundId={result.id}
            eventId={item.eventId}
            compact={compact}
            to={`/?round=${encodeURIComponent(result.id)}&select=${encodeURIComponent(`node:${item.eventId}`)}`}
            className={`self-start text-caption font-semibold underline underline-offset-4 ${FOCUS_RING}`}
          >
            이 회차 관계 그래프에서 보기
          </BriefingIssueMapLink>
        )}
        {previewAnalysis ? (
          <BriefingPreviewFeedback
            key={`${previewAnalysis.resultVersion}:${item.eventId}`}
            roundId={result.id}
            resultVersion={previewAnalysis.resultVersion}
            feature="briefing_issue"
            targetId={`${result.id}/${item.eventId}`}
            subject={`핵심 이슈 ${item.rank}`}
          />
        ) : (
          ratingVersion && (
            <FeedbackButtons
              key={`${feedbackKey}:${item.eventId}`}
              feature="briefing_issue"
              targetId={`${result.id}/${item.eventId}`}
              targetVersion={ratingVersion}
              subject={`핵심 이슈 ${item.rank}`}
              saved={saved('briefing_issue', `${result.id}/${item.eventId}`)}
              savedReason={
                myFeedback?.reasons?.[
                  `briefing_issue:${result.id}/${item.eventId}`
                ]
              }
            />
          )
        )}
      </div>
    );

  const feedbackReadError = myFeedback?.key === feedbackKey &&
    myFeedback?.error && (
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
    );
  const roundFeedback = result && (
    <section className={SECTION} aria-label="이 브리핑 평가">
      {previewAnalysis ? (
        <BriefingPreviewFeedback
          key={`${previewAnalysis.resultVersion}:round`}
          roundId={result.id}
          resultVersion={previewAnalysis.resultVersion}
          feature="briefing_round"
          targetId={result.id}
          subject="이 브리핑 회차"
        />
      ) : ratingVersion ? (
        <FeedbackButtons
          key={`${feedbackKey}:round`}
          feature="briefing_round"
          targetId={result.id}
          targetVersion={ratingVersion}
          subject="이 브리핑 회차"
          saved={saved('briefing_round', result.id)}
          savedReason={myFeedback?.reasons?.[`briefing_round:${result.id}`]}
        />
      ) : (
        <p className={NOTE}>
          이 회차는 결과 버전이 없어 평가를 남길 수 없어요.
        </p>
      )}
    </section>
  );

  // 화면은 순위 상위 3건만 그린다. 나머지 이슈의 정정은 회차 정정으로 남긴다.
  const shownItems = result
    ? [...result.items].sort((a, b) => a.rank - b.rank).slice(0, 3)
    : [];
  const corrections = splitCorrections(
    result?.corrections ?? [],
    shownItems.map((item) => item.eventId),
  );

  const currentContext = result && (
    <BriefingPreservedContext result={result} compact={compact} />
  );
  const original = result && preservedPublication(result);

  return (
    <BriefingTelemetry roundId={published?.id ?? null}>
      <article
        data-reading={compact ? 'compact' : 'full'}
        className={personal && result ? 'mt-[18px]' : CARD}
        aria-busy={loading}
      >
        {loading && (
          <LoadingIndicator
            label="브리핑을 불러오고 있어요."
            className="flex min-h-16 w-full text-caption text-zoop-muted"
          />
        )}
        {error && (
          <p role="alert" className={EMPTY}>
            {error}
          </p>
        )}
        {result && personal ? (
          <ScheduledPersonalBriefing
            key={`${result.id}:${memberId}`}
            round={result}
            compact={compact}
          />
        ) : (
          result && (
            <>
              <header className="border-b border-zoop-border pb-[18px]">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-title-sm font-bold tracking-[-0.025em]">
                    {result.edition === 'morning' ? '출근' : '퇴근'} 브리핑
                  </h2>
                  <span className={STATUS_PILL}>
                    {result.continuity?.mode === 'reference'
                      ? '참고 브리핑'
                      : result.continuity?.mode === 'recap'
                        ? result.continuity.recap.status === 'available'
                          ? '복기 브리핑'
                          : '확인 브리핑'
                        : statuses[result.status]}
                  </span>
                </div>
                {compact && (
                  <p className={`${NOTE} mt-2`}>
                    데이터 기준 {briefingTime(result.dataAsOf)}
                    {result.metadata.source.includes('simulation') ||
                    result.metadata.source.includes('replay')
                      ? ' · 과거 자료 시뮬레이션'
                      : ''}
                  </p>
                )}
                {!compact && publicationInfo}
              </header>
              {result.notice && (
                <p className={`${EMPTY} mt-4`} role="status">
                  {result.notice.message}
                  {result.notice.reason && ` · ${result.notice.reason}`}
                  {result.notice.at && ` · ${briefingTime(result.notice.at)}`}
                </p>
              )}
              {!compact && result.status === 'published' && (
                <BriefingOutlook
                  outlook={result.outlook}
                  issues={result.items.map((item) => ({
                    eventId: item.eventId,
                    title: item.title,
                    anchor: shownItems.includes(item)
                      ? issueAnchor(item)
                      : undefined,
                  }))}
                />
              )}
              {!compact &&
                result.continuity &&
                result.continuity.mode !== 'core' && (
                  <BriefingContinuity
                    value={result.continuity}
                    compact={compact}
                  />
                )}
              {result.status === 'published' && compact && (
                <>
                  {!knownLimits && partialInfo}
                  {feedbackReadError}
                  <IssueCentricBriefing
                    result={result}
                    beforeIssues={
                      personal ? (
                        <PersonalizedIssueSelection
                          roundId={result.id}
                          dataAsOf={result.dataAsOf}
                          checking={checking}
                        />
                      ) : undefined
                    }
                    items={result.items}
                    renderExtra={issueExtra}
                    issueCorrections={corrections.byIssue}
                  />
                  <BriefingCorrections corrections={corrections.round} />
                </>
              )}
              {result.status === 'published' && !compact && (
                <BriefingReadingSection
                  compact={
                    compact &&
                    Boolean(
                      result.continuity && result.continuity.mode !== 'core',
                    )
                  }
                  title="시장·지표와 전체 저장 상태 보기"
                >
                  {(!compact || !knownLimits) && partialInfo}
                  {result.issueIntelligence ? (
                    <>
                      <IssueCentricBriefing
                        compact={false}
                        result={result}
                        beforeIssues={
                          personal ? (
                            <PersonalizedIssueSelection
                              roundId={result.id}
                              dataAsOf={result.dataAsOf}
                              checking={checking}
                            />
                          ) : undefined
                        }
                        items={result.items}
                        renderExtra={issueExtra}
                        issueCorrections={corrections.byIssue}
                      />
                      <BriefingReadingSection
                        compact
                        title="이전 생성 전문·시장 요약·시세 보존본"
                      >
                        {original ? (
                          <BriefingPreservedContext
                            result={original}
                            compact={false}
                          />
                        ) : (
                          <p className={NOTE}>
                            이전 발행본을 확인하지 못해 보존본을 표시하지
                            않습니다.
                          </p>
                        )}
                      </BriefingReadingSection>
                    </>
                  ) : (
                    currentContext
                  )}
                  {result.items.length === 0 &&
                    result.emptyReason === 'no_issues_in_window' &&
                    !result.issueIntelligence &&
                    !result.continuity && (
                      <BriefingRecap
                        key={`${result.id}:${result.graphVersion}:${result.dataAsOf}`}
                        round={result}
                        compact={compact}
                      />
                    )}
                  {personal && !result.issueIntelligence && (
                    <PersonalizedIssueSelection
                      roundId={result.id}
                      dataAsOf={result.dataAsOf}
                      checking={checking}
                    />
                  )}
                  {feedbackReadError}
                  {!result.issueIntelligence && (
                    <BriefingIssueList
                      compact={compact}
                      items={result.items}
                      roundId={result.id}
                      graphVersion={result.graphVersion}
                      graphHref={`/?round=${encodeURIComponent(result.id)}`}
                      renderExtra={issueExtra}
                      issueCorrections={corrections.byIssue}
                    />
                  )}
                  <BriefingReadingSection
                    compact={compact}
                    title="이전 브리핑과 핵심 이슈 변화 보기"
                  >
                    {result.edition === 'evening' && (
                      <BriefingComparison
                        since={result.sinceMorning}
                        roundDate={result.date}
                        graphRoundId={
                          result.issueIntelligence ? undefined : result.id
                        }
                      />
                    )}
                    {result.edition === 'morning' && (
                      <BriefingComparison
                        basis="previous"
                        previous={result.previousComparison ?? null}
                        roundDate={result.date}
                        graphRoundId={
                          result.issueIntelligence ? undefined : result.id
                        }
                      />
                    )}
                  </BriefingReadingSection>
                  <BriefingCorrections corrections={corrections.round} />
                  {roundFeedback}
                </BriefingReadingSection>
              )}
              {compact && result.status === 'published' && roundFeedback}
            </>
          )
        )}
        {result?.status === 'published' && (
          <p className={`${NOTE} mt-4`}>{BRIEFING_DISCLAIMER}</p>
        )}
        {canRetry && (
          <button className={PRIMARY_BUTTON} type="button" onClick={reload}>
            다시 시도
          </button>
        )}
      </article>
    </BriefingTelemetry>
  );
}
