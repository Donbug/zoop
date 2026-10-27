import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { BriefingItem, BriefingResponse } from '@/types/briefing';
import {
  briefingIssueViews,
  issueAnchor,
  type BriefingIssueView,
} from '@/util/briefingIssueView';
import { briefingTime } from '@/util/briefingTime';
import { safeArticleUrl } from '@/components/graph/event-format';
import MarketIndicators from './MarketIndicators';
import BriefingItemDetails from './BriefingItemDetails';
import BriefingContinuity from './BriefingContinuity';
import BriefingRecap from './BriefingRecap';
import BriefingS3Impacts from './BriefingS3Impacts';
import {
  BODY,
  EMPTY,
  FOCUS_RING,
  NOTE,
  SECTION,
  SECTION_TITLE,
} from './briefingStyles';

const labels = {
  positive: '긍정 요인',
  negative: '부정 요인',
  mixed: '긍정·부정 혼재',
  watch: '판단 유보',
};
const signed = (s: string) => `${Number(s) > 0 ? '+' : ''}${s}%`;
const amount = (s: string) =>
  Number(s).toLocaleString('ko-KR', { maximumFractionDigits: 4 });

function CompanyInIssue({
  view,
  evening,
}: {
  view: BriefingIssueView['companies'][number];
  evening: boolean;
}) {
  const { company, price } = view;
  return (
    <section
      aria-label={`${company.name} 관련 판단`}
      className="space-y-3 border-t border-zoop-line pt-4"
    >
      <h5 className="flex flex-wrap items-center gap-2 text-sm font-bold">
        {company.name}
        {view.assessment && (
          <span className="rounded border border-zoop-line px-2 py-1 text-xs">
            기존 기업 사업 판단 · {labels[view.assessment]}
          </span>
        )}
      </h5>
      {view.impact ? (
        <>
          <p className={BODY}>{view.impact.text}</p>
          <p className={NOTE}>
            이 이슈와 인용된 배경을 함께 본 기업의 사업상 판단입니다.
          </p>
        </>
      ) : (
        <p className={NOTE}>이 이슈에 연결된 기존 v5 기업 전망이 없습니다.</p>
      )}
      {price?.status === 'available' && (
        <div className="rounded border border-zoop-line bg-zoop-wash p-3">
          <p className="text-sm font-semibold">
            {price.sessionDate}{' '}
            {price.latest.kind === 'daily_close' ? '종가' : '완료 봉'}{' '}
            {amount(price.latest.value)} {price.currency}
            {price.day.changeRatePercent !== null && (
              <>
                {' '}
                · {signed(price.day.changeRatePercent)} (
                {price.day.baselineDate} 대비)
              </>
            )}
          </p>
          <p className={`${NOTE} mt-1`}>
            관측 {briefingTime(price.latest.observedAt)}
          </p>
          {view.news.map((n) => (
            <p className={`${NOTE} mt-2`} key={n.evidenceId}>
              기사 {briefingTime(n.publishedAt)} ·{' '}
              {n.status === 'observed' &&
              n.before &&
              n.changeRatePercent !== null
                ? `공개 전 마지막 확인가 ${amount(n.before.value)} → 최근 확인가 ${amount(price.latest.value)} ${price.currency} (${signed(n.changeRatePercent)})`
                : n.status === 'no_post_news_trade'
                  ? '기사 공개 후 완료된 정규장 봉이 없습니다.'
                  : '공개 직전 비교 가격이 부족해 뉴스 전후 변화율을 판단할 수 없습니다.'}
            </p>
          ))}
          {evening && (
            <p className={`${NOTE} mt-2`}>{price.sinceMorning.observation}</p>
          )}
          <p className={`${NOTE} mt-2`}>
            가격은 별도 관측이며, 이 뉴스가 변동의 원인이라는 증거는 아닙니다.
          </p>
        </div>
      )}
      {price?.status !== 'available' && (
        <p className={NOTE}>
          시세 확인 범위 ·{' '}
          {price?.reason ??
            '이 회차에 연결된 검증 가능한 기업 시세가 없습니다.'}
        </p>
      )}
      {view.outlook && (
        <div>
          <h6 className="text-sm font-semibold">현재 전망과 확인 조건</h6>
          <p className={`${BODY} mt-2`}>{view.outlook.text}</p>
        </div>
      )}
      {view.risks.length > 0 && (
        <details>
          <summary
            className={`min-h-11 cursor-pointer content-center text-xs ${FOCUS_RING}`}
          >
            판단이 약해질 조건
          </summary>
          <ul className="list-disc space-y-2 pl-4">
            {view.risks.map((s, i) => (
              <li key={i} className={BODY}>
                {s.text}
              </li>
            ))}
          </ul>
        </details>
      )}
      {view.refs.length > 0 && (
        <details>
          <summary
            className={`min-h-11 cursor-pointer content-center text-xs ${FOCUS_RING}`}
          >
            기업 판단의 근거·배경 {view.refs.length}건
          </summary>
          <ul className="space-y-4">
            {view.refs.map((s) => (
              <li key={s.id}>
                {safeArticleUrl(s.url) ? (
                  <a
                    href={safeArticleUrl(s.url)!}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={`text-sm underline ${FOCUS_RING}`}
                  >
                    {s.title} ↗
                  </a>
                ) : (
                  <p className={BODY}>{s.title}</p>
                )}
                <p className={NOTE}>{briefingTime(s.publishedAt)}</p>
                <blockquote
                  className={`${NOTE} mt-2 border-l-2 border-zoop-line pl-3`}
                >
                  {s.quote}
                </blockquote>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

/** Follow-up belongs to the issue that supplied the evidence, never to a company-only card. */
function IssueFollowUp({
  view,
  result,
}: {
  view: BriefingIssueView;
  result: BriefingResponse;
}) {
  const evening = result.edition === 'evening';
  const changed = view.companies.filter(
    (c) => c.comparison && c.comparison.status !== 'unavailable',
  );
  const watching = view.companies.filter((c) => c.conditions.length > 0);
  return (
    <>
      <section>
        <h4 className="text-sm font-bold">
          {evening ? '아침 판단에서 달라진 점' : '전날 판단에서 달라진 점'}
        </h4>
        {changed.length ? (
          <ul className="mt-2 space-y-3">
            {changed.map((c) => (
              <li key={c.company.id}>
                <p className="text-xs font-semibold">{c.company.name}</p>
                <p className={`${BODY} mt-1`}>{c.comparison!.text}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p className={`${NOTE} mt-2`}>
            이 이슈에 연결된 비교 가능한 이전 판단이 아직 없습니다.
          </p>
        )}
        {result.aiPriceOutlooks?.historyNote && (
          <details className="mt-2">
            <summary
              className={`min-h-11 cursor-pointer content-center text-xs ${FOCUS_RING}`}
            >
              비교에 사용한 판본
            </summary>
            <p className={NOTE}>{result.aiPriceOutlooks.historyNote}</p>
          </details>
        )}
      </section>
      <section>
        <h4 className="text-sm font-bold">
          {evening ? '다음 거래일 확인할 사건' : '오늘 확인할 사건'}
        </h4>
        {watching.length ? (
          <ul className="mt-2 space-y-3">
            {watching.map((c) => (
              <li key={c.company.id}>
                <p className="text-xs font-semibold">{c.company.name}</p>
                <ul className="mt-1 list-disc space-y-2 pl-4">
                  {c.conditions.map((condition, i) => (
                    <li className={BODY} key={i}>
                      {condition.text}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        ) : (
          <p className={`${NOTE} mt-2`}>
            이 이슈에 연결된 확인 조건이 아직 없습니다.
          </p>
        )}
      </section>
    </>
  );
}

function IssueCard({
  view,
  result,
  renderExtra,
}: {
  view: BriefingIssueView;
  result: BriefingResponse;
  renderExtra?: (item: BriefingItem) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const item = view.item;
  return (
    <li>
      <details
        id={issueAnchor(item)}
        onToggle={(e) => setOpen(e.currentTarget.open)}
        className="scroll-mt-4 rounded-lg border border-zoop-line bg-zoop-paper"
      >
        <summary className={`cursor-pointer list-none p-4 ${FOCUS_RING}`}>
          <span className="flex justify-between gap-3 text-xs text-zoop-muted">
            <span>핵심 이슈 {item.rank}</span>
            <span aria-hidden>{open ? '접기 −' : '자세히 +'}</span>
          </span>
          <strong className="mt-2 block text-base leading-snug">
            {item.title}
          </strong>
          <span className="mt-3 block text-xs text-zoop-muted">
            {item.companies.length
              ? item.companies.map((c) => c.name).join(' · ')
              : '연결 기업 미확인'}{' '}
            · 관련 기업 {item.companies.length}곳 · 근거 {item.evidenceCount}건
          </span>
        </summary>
        {open && (
          <div className="space-y-5 border-t border-zoop-line p-4">
            <section>
              <h4 className="text-sm font-bold">무슨 일이 있었나요?</h4>
              <p className={`${BODY} mt-2`}>
                {'text' in item.summary
                  ? item.summary.text
                  : item.summary.reason}
              </p>
            </section>
            <BriefingS3Impacts
              key={`${result.id}:${item.eventId}:${result.graphVersion}`}
              round={result}
              item={item}
            />
            <IssueFollowUp view={view} result={result} />
            {view.companies.map((c) => (
              <CompanyInIssue
                key={c.company.id}
                view={c}
                evening={result.edition === 'evening'}
              />
            ))}
            <BriefingItemDetails
              roundId={result.id}
              graphVersion={result.graphVersion}
              item={item}
              evidenceOnly
            />
            <details>
              <summary
                className={`min-h-11 cursor-pointer content-center text-xs ${FOCUS_RING}`}
              >
                선정 이유
              </summary>
              <p className={NOTE}>{item.reason}</p>
            </details>
            {renderExtra?.(item)}
          </div>
        )}
      </details>
    </li>
  );
}

/** D-BRF-01/02: indicators → issues; companies belong inside an issue, never dedupe selection by company. */
export default function IssueCentricBriefing({
  result,
  items = result.items,
  renderExtra,
}: {
  result: BriefingResponse;
  items?: BriefingItem[];
  renderExtra?: (item: BriefingItem) => ReactNode;
}) {
  const views = briefingIssueViews(result, items);
  return (
    <div data-presentation="issue-centered">
      <MarketIndicators
        variables={result.marketVariables}
        compact
        showBaseline
      />
      {result.items.length === 0 &&
        result.emptyReason === 'no_issues_in_window' &&
        !result.continuity && (
          <BriefingRecap
            key={`${result.id}:${result.graphVersion}:${result.dataAsOf}`}
            round={result}
            compact
          />
        )}

      {result.continuity && result.continuity.mode !== 'core' && (
        <BriefingContinuity value={result.continuity} compact />
      )}
      <section className={SECTION} aria-label="핵심 이슈 중심 브리핑">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h3 className={SECTION_TITLE}>핵심 이슈</h3>
          <Link
            to={`/?round=${encodeURIComponent(result.id)}`}
            className={`text-xs underline ${FOCUS_RING}`}
          >
            이슈 관계 지도 ↗
          </Link>
        </div>
        {views.length ? (
          <ol className="space-y-3">
            {views.map((v) => (
              <IssueCard
                key={v.item.eventId}
                view={v}
                result={result}
                renderExtra={renderExtra}
              />
            ))}
          </ol>
        ) : (
          <p className={EMPTY}>
            이 회차에 새로 선정된 핵심 이슈가 없습니다. 복기·수집 상태는 위
            안내를 확인하세요.
          </p>
        )}
      </section>
    </div>
  );
}
