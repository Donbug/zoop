import { useCallback } from 'react';
import LoadingIndicator from '@/components/common/LoadingIndicator';
import { Link } from 'react-router-dom';
import { getPersonalizedBriefingIssues } from '@/apis/briefing/briefing';
import { useAsyncData } from '@/hooks/useAsyncData';
import { selectMemberId, useAuthStore } from '@/stores/useAuthStore';
import { briefingTime } from '@/util/briefingTime';
import { EMPTY, FOCUS_RING, NOTE } from './briefingStyles';
import PersonalAiJudgment from './PersonalAiJudgment';
import { personalAiOverview } from '@/util/personalAiOverview';

/** D-BRF-01/02: personal candidates have their own evidence, not shared-publication feedback/detail IDs. */
export default function PersonalizedIssueSelection({
  roundId,
  dataAsOf,
  checking = false,
}: {
  roundId: string;
  dataAsOf: string | null;
  checking?: boolean;
}) {
  const memberId = useAuthStore(selectMemberId);
  const revision = useAuthStore((s) => s.sessionRevision);
  const load = useCallback(async () => {
    if (!memberId) return null;
    const result = await getPersonalizedBriefingIssues(roundId);
    if (useAuthStore.getState().sessionRevision !== revision)
      throw new Error('계정이 변경됐어요.');
    if (
      result.roundId !== roundId ||
      Date.parse(result.dataAsOf) !== Date.parse(dataAsOf ?? '') ||
      result.items.length > 3
    )
      throw new Error('선택한 회차와 개인화 결과가 일치하지 않아요.');
    return result;
  }, [memberId, revision, roundId, dataAsOf]);
  const query = useAsyncData(load);
  const link = `font-semibold underline underline-offset-4 ${FOCUS_RING}`;
  if (checking)
    return (
      <LoadingIndicator
        label="로그인 상태를 확인하고 있어요."
        className={`${NOTE} flex min-h-8 w-full`}
      />
    );
  if (!memberId)
    return (
      <p className={EMPTY}>
        내 종목 브리핑은 로그인 후 확인할 수 있어요.{' '}
        <Link className={link} to="/login">
          로그인하기
        </Link>
      </p>
    );
  if (query.status === 'loading')
    return (
      <LoadingIndicator
        label="보유·관심 종목의 관련 이슈를 찾고 있어요."
        className={`${NOTE} flex min-h-8 w-full`}
      />
    );
  if (query.status === 'error')
    return (
      <div role="alert" className={EMPTY}>
        개인화 결과를 불러오지 못했어요. 공통 브리핑은 아래에서 볼 수 있어요.{' '}
        <button className={link} onClick={() => query.reload()}>
          다시 시도
        </button>
      </div>
    );
  const result = query.data;
  if (!result) return null;
  const ai =
    result.aiAnalysis?.status === 'available' &&
    result.aiAnalysis.roundId === roundId &&
    Date.parse(result.aiAnalysis.cutoff) === Date.parse(dataAsOf ?? '')
      ? result.aiAnalysis
      : null;
  const overview = ai ? personalAiOverview(ai, result.edition) : null;
  return (
    <section
      aria-label="내 종목 핵심 이슈"
      className="my-6 space-y-4 border-b border-zoop-line pb-6"
    >
      <div>
        <h2 className="text-lg font-bold">내 종목 핵심 이슈</h2>
        <p className={NOTE}>
          현재 보유 {result.basis.holdings.length}개 · 관심{' '}
          {result.basis.watchlist.length}개 · {briefingTime(result.dataAsOf)}{' '}
          기준
        </p>
        {result.basis.holdings.length > 0 && (
          <p className={NOTE}>보유 종목은 연결한 모의 계좌 기준입니다.</p>
        )}
        {result.scope?.includes('simulation') && (
          <p className={NOTE}>저장된 과거 자료를 재사용한 개인화 결과입니다.</p>
        )}
        {result.poolVersion && (
          <p className={NOTE}>
            전체 적격 후보 {result.eligibleCount}개 중 관련{' '}
            {result.matchingCount}개 · 최대 3개 선정
          </p>
        )}
      </div>
      {ai && (
        <div className="rounded-panel bg-zoop-wash p-4">
          <p className="text-sm font-semibold">내 종목 영향 요약</p>
          <p className="mt-2 text-sm leading-relaxed">{overview?.text}</p>
          {overview?.comparisonNote && (
            <p className={`${NOTE} mt-2`}>{overview.comparisonNote}</p>
          )}
        </div>
      )}
      {result.aiAnalysis?.status === 'unavailable' &&
        result.items.length > 0 && (
          <p className={NOTE}>
            현재 종목 기준의 새 AI 설명은 아직 제공되지 않습니다. 아래에서
            확인된 선정·연결 근거를 볼 수 있어요.
          </p>
        )}
      {result.status !== 'available' && (
        <p role="status" className={EMPTY}>
          {result.message}
          {result.status === 'no_companies' && (
            <>
              {' '}
              <Link to="/my" className={link}>
                내 종목 설정하기
              </Link>
            </>
          )}
        </p>
      )}
      {result.excludedByCurrentAccess > 0 && (
        <p className={NOTE}>
          현재 근거 제공 권한을 확인할 수 없는 관련 후보{' '}
          {result.excludedByCurrentAccess}개는 제외했어요.
        </p>
      )}
      {result.items.map((item, i) => (
        <article
          key={item.issueId}
          className="rounded-panel border border-panel-line p-4"
        >
          <p className={NOTE}>관련 이슈 {i + 1}</p>
          <h3 className="mt-1 text-base font-bold">{item.title}</h3>
          <p className="mt-2 text-sm leading-relaxed">
            <strong>왜 중요한가요?</strong> {item.whyImportant}
          </p>
          <p className="mt-2 text-sm leading-relaxed">
            <strong>이번 회차의 새 정보</strong> {item.whyNow}
          </p>
          <ul className="mt-3 space-y-2 text-sm">
            {item.matches.map((m) => (
              <li key={m.companyId}>
                <strong>{m.name}</strong> ·{' '}
                {m.kinds
                  .map((k) => (k === 'holding' ? '보유' : '관심'))
                  .join('·')}{' '}
                ·{' '}
                {m.directness === 'direct'
                  ? '직접 당사자'
                  : '근거로 연결된 기업'}
                <p className={NOTE}>{m.reason}</p>
              </li>
            ))}
          </ul>
          {ai &&
            item.matches.map((match) => {
              const value =
                ai.draft.issues[item.issueId]?.companies[match.companyId];
              return value ? (
                <PersonalAiJudgment
                  key={match.companyId}
                  name={match.name}
                  kinds={match.kinds}
                  value={value}
                />
              ) : null;
            })}
          <details className="mt-3">
            <summary
              className={`cursor-pointer text-sm font-semibold ${FOCUS_RING}`}
            >
              확인된 근거 {item.sources.length}건과 상세 보기
            </summary>
            <p className="mt-2 text-sm">
              {item.analysis ??
                '이 후보의 상세 전망은 저장되어 있지 않습니다. 확인된 사실과 선정·연결 근거를 제공합니다.'}
            </p>
            {item.nextCheck && (
              <p className="mt-2 text-sm">
                <strong>다음 확인사항</strong> {item.nextCheck}
              </p>
            )}
            {item.sources.map((s) => (
              <blockquote
                key={s.evidenceId}
                className="mt-3 border-l-2 border-panel-line pl-3 text-sm"
              >
                {s.quote}
                <p className={NOTE}>
                  {briefingTime(s.publishedAt)} ·{' '}
                  <a
                    className={link}
                    href={s.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    원문 보기
                  </a>
                </p>
              </blockquote>
            ))}
          </details>
        </article>
      ))}
      <details>
        <summary
          className={`cursor-pointer text-sm font-semibold ${FOCUS_RING}`}
        >
          이전 이슈 추적 ({result.tracking.length})
        </summary>
        <p className={`${NOTE} mt-2`}>
          현재 내 종목으로 고정된 직전 회차를 다시 조회한 결과입니다. 과거에
          실제로 열람한 목록을 뜻하지 않습니다.
        </p>
        {!result.tracking.length && (
          <p className={`${NOTE} mt-2`}>
            {result.trackingStatus === 'available'
              ? '직전 회차에 추적할 적격 관련 이슈가 없습니다.'
              : '비교 가능한 직전 후보 저장본을 확인하지 못했습니다.'}
          </p>
        )}
        {result.tracking.map((t) => (
          <div
            key={`${t.issueId}:${t.companyId}`}
            className="mt-3 border-t border-panel-line pt-3 text-sm"
          >
            <strong>
              {t.title} · {t.companyName}
            </strong>
            <p>{t.message}</p>
            {t.personalAiNextCheck ? (
              <p>개인화 분석의 확인사항: {t.personalAiNextCheck}</p>
            ) : t.nextCheck ? (
              <p>기존 확인사항: {t.nextCheck}</p>
            ) : null}
          </div>
        ))}
      </details>
      {ai && (
        <details>
          <summary className="cursor-pointer text-xs text-zoop-muted">
            AI 분석 기준
          </summary>
          <p className={NOTE}>
            선정된 이슈·연결 기업·저장 시세로 새로 작성하고 별도 AI 요청에서
            근거를 대조한 설명입니다. {ai.model} · {ai.promptVersion} ·{' '}
            {briefingTime(ai.generatedAt)}
          </p>
        </details>
      )}
      <p className={NOTE}>
        아래 공통 브리핑의 시세·원문·평가는 그대로 유지됩니다.
      </p>
    </section>
  );
}
