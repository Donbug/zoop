import { useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useBriefingIssueTracking } from './briefingTelemetryContext';
import { getBriefing } from '@/apis/briefing/briefing';
import { validEditionReview } from '@/util/editionReview';
import type {
  BriefingDocumentSentiment,
  BriefingItem,
  BriefingResponse,
} from '@/types/briefing';
import {
  briefingIssueViews,
  issueAnchor,
  type BriefingIssueView,
} from '@/util/briefingIssueView';
import { briefingTime } from '@/util/briefingTime';
import { validIssueIntelligence } from '@/util/issueIntelligence';
import {
  readingGroups,
  groupCompanies,
  paragraphs,
  uniqueText,
  validIssueReading,
} from '@/util/briefingIssueReading';
import { safeArticleUrl } from '@/components/graph/event-format';
import MarketIndicators from './MarketIndicators';
import BriefingItemDetails from './BriefingItemDetails';
import BriefingContinuity from './BriefingContinuity';
import BriefingRecap from './BriefingRecap';
import BriefingS3Impacts from './BriefingS3Impacts';
import ImpactCue from '@/components/common/ImpactCue';
import {
  BriefingDocumentSentiments,
  IssueCorrections,
} from './BriefingPublishedNotes';
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
type Correction = BriefingResponse['corrections'][number];
const articleCount = (item: BriefingItem) =>
  item.sourceSupport ? ` · 보도 기사 ${item.sourceSupport.articleCount}건` : '';

const signed = (s: string) => `${Number(s) > 0 ? '+' : ''}${s}%`;
const amount = (s: string) =>
  Number(s).toLocaleString('ko-KR', { maximumFractionDigits: 4 });

function sentences(text: string) {
  return uniqueText(
    paragraphs(text).flatMap((p) => p.split(/(?<=[.!?。])\s+(?=[가-힣A-Z])/)),
  );
}
function ReadingText({ text, compact }: { text: string; compact: boolean }) {
  const parts = sentences(text);
  if (!compact || parts.length < 2)
    return (
      <p className={`${BODY} mt-2 whitespace-pre-line`}>
        {paragraphs(text).join('\n')}
      </p>
    );
  return (
    <>
      <p className={`${BODY} mt-2`}>{parts[0]}</p>
      <details>
        <summary
          className={`min-h-11 cursor-pointer content-center text-caption text-zoop-muted ${FOCUS_RING}`}
        >
          전체 설명
        </summary>
        <p className={`${BODY} whitespace-pre-line`}>
          {parts.slice(1).join('\n')}
        </p>
      </details>
    </>
  );
}

function CompanyInIssue({
  view,
  evening,
  compact,
  commonFacts,
  connection,
  position,
  sentiments,
}: {
  sentiments?: BriefingDocumentSentiment[];
  compact: boolean;
  commonFacts: string[];
  connection: string;
  position: string;
  view: BriefingIssueView['companies'][number];
  evening: boolean;
}) {
  const { company, price } = view;
  const extraFacts = paragraphs(view.fact?.text ?? '').filter(
    (fact) => !commonFacts.includes(fact),
  );
  return (
    <section
      aria-label={`${company.name} 관련 판단`}
      className="space-y-3 border-t border-zoop-line pt-4"
    >
      <h5 className="flex flex-wrap items-center gap-2 text-body font-bold">
        {company.id ? (
          <Link
            to={`/companies/${encodeURIComponent(company.id)}`}
            className={`underline underline-offset-4 ${FOCUS_RING}`}
          >
            {company.name}
          </Link>
        ) : (
          company.name
        )}
        {view.assessment && (
          <span className="text-caption">
            <ImpactCue tone={view.assessment} badge>
              사업 영향 · {labels[view.assessment]}
            </ImpactCue>
          </span>
        )}
      </h5>
      <p className={NOTE}>
        연결 이유 ·{' '}
        {connection ||
          (company.roleUnconfirmed
            ? '이번 사건과의 관계 근거 미확인'
            : '이 사건의 근거에서 기업명이 확인됐으며 구체적인 역할은 추가 확인이 필요합니다.')}
      </p>
      {connection && (
        <p className={NOTE}>
          {position === 'primary'
            ? '직접 당사자'
            : position === 'related'
              ? '이번 사건에 연결된 기업'
              : '연결 후보 · 영향 확정 전'}
        </p>
      )}
      <BriefingDocumentSentiments
        sentiments={sentiments?.filter(
          (s) => s.sentiment.companyId === company.id,
        )}
        companies={[company]}
        label={`${company.name} 문서 판정`}
      />
      <section aria-label="한 줄 결론">
        <h6 className="text-body font-bold">한 줄 결론</h6>
        <ReadingText
          compact={compact}
          text={
            view.conclusion?.text ??
            (view.impact && view.impact.text.length <= 160
              ? view.impact.text
              : '이 이슈의 사업 영향은 아직 판단하기 어렵습니다.')
          }
        />
      </section>
      <div className="grid gap-3 sm:grid-cols-2">
        <section className="rounded-lg border border-zoop-positive/20 bg-zoop-positive/5 p-4">
          <h6 className="text-body font-bold">
            <ImpactCue tone="positive">긍정 가능성</ImpactCue>
          </h6>
          <ReadingText
            compact={compact}
            text={view.positive?.text ?? '현재 근거에서 확인된 긍정 요인 없음'}
          />
        </section>
        <section className="rounded-lg border border-zoop-alert/20 bg-zoop-alert/5 p-4">
          <h6 className="text-body font-bold">
            <ImpactCue tone="negative">위험·불확실성</ImpactCue>
          </h6>
          <ReadingText
            compact={compact}
            text={view.negative?.text ?? '현재 근거에서 확인된 위험 요인 없음'}
          />
        </section>
      </div>
      {extraFacts.length > 0 && (
        <section>
          <h6 className="text-body font-bold">
            <ImpactCue tone="neutral" icon="check">
              이 기업에 추가로 확인된 사실
            </ImpactCue>
          </h6>
          <ReadingText compact={compact} text={extraFacts.join('\n')} />
        </section>
      )}
      {price?.status === 'available' && (
        <div className="rounded border border-zoop-line bg-zoop-wash p-3">
          <p className="text-body font-semibold">
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
      {(view.impact ||
        view.outlook ||
        view.risks.length > 0 ||
        view.conditions.length > 0) && (
        <details>
          <summary
            className={`min-h-11 cursor-pointer content-center text-body font-semibold ${FOCUS_RING}`}
          >
            자세한 사업 분석·전망
          </summary>
          <div className="mt-3 space-y-4">
            {view.impact && (
              <section>
                <h6 className="text-body font-bold">사업상 의미</h6>
                <p className={`${BODY} mt-2`}>{view.impact.text}</p>
              </section>
            )}
            {view.outlook && (
              <section>
                <h6 className="text-body font-bold">현재 전망과 확인 조건</h6>
                <p className={`${BODY} mt-2`}>{view.outlook.text}</p>
              </section>
            )}
            {view.conditions.length > 0 && (
              <section>
                <h6 className="text-body font-bold">상세 확인 조건</h6>
                <ul className="mt-2 list-disc space-y-2 pl-4">
                  {view.conditions.map((c, i) => (
                    <li className={BODY} key={i}>
                      {c.text}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {view.risks.length > 0 && (
              <section>
                <h6 className="text-body font-bold">
                  판단을 바꿀 위험·반대 조건
                </h6>
                <ul className="mt-2 list-disc space-y-2 pl-4">
                  {view.risks.map((c, i) => (
                    <li className={BODY} key={i}>
                      {c.text}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        </details>
      )}
      {view.refs.length > 0 && (
        <details>
          <summary
            className={`min-h-11 cursor-pointer content-center text-caption ${FOCUS_RING}`}
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
                    className={`text-body underline ${FOCUS_RING}`}
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
  hideComparison = false,
  comparisonState = 'ready',
}: {
  view: BriefingIssueView;
  result: BriefingResponse;
  hideComparison?: boolean;
  comparisonState?: 'loading' | 'error' | 'ready';
}) {
  const evening = result.edition === 'evening';
  const changed = view.companies.filter(
    (c) => c.comparison && c.comparison.status !== 'unavailable',
  );
  const watching = view.companies.filter((c) => c.nextChecks.length > 0);
  return (
    <>
      {!hideComparison && (
        <section>
          {view.companies
            .filter((c) => c.previous)
            .map((c) => (
              <div
                key={c.company.id}
                className="mb-3 rounded border border-zoop-line p-3"
              >
                <p className="text-caption font-semibold">
                  {c.company.name} · 같은 이슈의 이전 판단
                </p>
                <p className={`${BODY} mt-1`}>{c.previous!.judgment.text}</p>
              </div>
            ))}
          {comparisonState !== 'ready' ? (
            <p className={NOTE}>
              {comparisonState === 'loading'
                ? '이전 회차 판단을 확인하고 있어요.'
                : '이전 회차 조회 실패로 판단 비교를 확인하지 못했어요.'}
            </p>
          ) : changed.length ? (
            <>
              <h4 className="text-body font-bold">
                {evening
                  ? '아침 판단에서 달라진 점'
                  : '전날 판단에서 달라진 점'}
              </h4>
              <ul className="mt-2 space-y-3">
                {changed.map((c) => (
                  <li key={c.company.id}>
                    <p className="text-caption font-semibold">
                      {c.company.name}
                    </p>
                    <p className={`${BODY} mt-1`}>{c.comparison!.text}</p>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className={NOTE}>비교 가능한 이전 판단 없음</p>
          )}
          {!result.issueIntelligence && result.aiPriceOutlooks?.historyNote && (
            <details className="mt-2">
              <summary
                className={`min-h-11 cursor-pointer content-center text-caption ${FOCUS_RING}`}
              >
                비교에 사용한 판본
              </summary>
              <p className={NOTE}>{result.aiPriceOutlooks.historyNote}</p>
            </details>
          )}
        </section>
      )}
      <section>
        <h4 className="text-body font-bold">
          <ImpactCue tone="neutral" icon="calendar">
            다음 확인사항
          </ImpactCue>
        </h4>
        {watching.length ? (
          <ul className="mt-2 space-y-3">
            {watching.map((c) => (
              <li key={c.company.id}>
                <p className="text-caption font-semibold">{c.company.name}</p>
                <ul className="mt-1 list-disc space-y-2 pl-4">
                  {c.nextChecks.map((condition, i) => (
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
  group,
  rank,
  compact,
  comparisonState,
  result,
  renderExtra,
  corrections,
}: {
  corrections: Correction[];
  group: ReturnType<typeof readingGroups>[number];
  rank: number;
  comparisonState: 'loading' | 'error' | 'ready';
  compact: boolean;
  result: BriefingResponse;
  renderExtra?: (item: BriefingItem) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const item = group.members[0].item;
  const recordOpen = useBriefingIssueTracking(result.id, item.eventId);
  const displayedItem = { ...item, rank };
  const companies = groupCompanies(group);
  const facts = uniqueText(
    group.members.flatMap((v) =>
      paragraphs(
        'text' in v.item.summary ? v.item.summary.text : v.item.summary.reason,
      ),
    ),
  );
  const selectionSummary = group.selections.length
    ? uniqueText([
        sentences(group.selections[0].whyImportant.text)[0],
        sentences(group.selections[0].whyNow.text)[0],
      ]).join(' ')
    : sentences(item.reason)[0];
  const newsObserved = companies.some((c) =>
    c.view.news.some((n) => n.status === 'observed'),
  );
  const summaryView = {
    ...group.members[0],
    companies: companies.map((c) => c.view),
  };
  const evidenceCount = new Set(
    group.members.flatMap((v) => v.item.evidenceIds),
  ).size;
  const sentiments = group.members.flatMap(
    (m) => m.item.documentSentiments ?? [],
  );
  return (
    <li>
      {group.members.length > 1 &&
        group.members.map((m) => (
          // 회차 판단의 근거 이슈 앵커. 묶음 카드는 사건마다 같은 카드로 이어 준다.
          <span
            key={m.item.eventId}
            id={issueAnchor(m.item)}
            className="block scroll-mt-4"
          />
        ))}
      <details
        id={
          group.members.length > 1
            ? `briefing-group-${group.id}`
            : issueAnchor(item)
        }
        onToggle={(e) => {
          const next = e.currentTarget.open;
          if (next && !open) recordOpen();
          setOpen(next);
        }}
        className={`scroll-mt-4 overflow-hidden border border-zoop-line bg-zoop-paper ${
          corrections.length ? 'rounded-t-2xl border-b-0' : 'rounded-2xl'
        }`}
      >
        <summary
          className={`cursor-pointer list-none p-5 sm:p-6 ${FOCUS_RING}`}
        >
          <span className="flex justify-between gap-3 text-caption text-zoop-muted">
            <span>핵심 이슈 {rank}</span>
            <span aria-hidden>{open ? '접기 −' : '자세히 +'}</span>
          </span>
          <strong className="mt-3 block text-title-sm font-bold leading-snug">
            {group.title}
          </strong>
          <span className="mt-3 block text-body leading-relaxed">
            <b>선정 이유 · </b>
            {selectionSummary}
          </span>
          <span className="mt-3 block text-caption text-zoop-muted">
            {companies.length
              ? companies.map((c) => c.view.company.name).join(' · ')
              : '연결 기업 미확인'}{' '}
            · 관련 기업 {companies.length}곳 · 근거 {evidenceCount}건
            {group.members.length === 1 && articleCount(item)}
          </span>
        </summary>
        {open && (
          <div className="space-y-6 border-t border-zoop-line p-5 sm:p-6">
            <p className={NOTE}>
              시장 관측 ·{' '}
              {newsObserved
                ? '일부 연결 기업의 발표 전후 가격 관측 있음 · 인과관계와 구분'
                : '발표 전후 비교 가능한 주가 반응 미확인 · 저장 시세는 별도 표시'}
            </p>
            {group.reason && (
              <p className={NOTE}>함께 묶은 이유 · {group.reason}</p>
            )}
            <section>
              <h4 className="text-body font-bold">
                <ImpactCue tone="neutral" icon="check">
                  공통으로 확인된 사실
                </ImpactCue>
              </h4>
              <ul className="mt-2 space-y-2">
                {facts.map((fact) => (
                  <li className={BODY} key={fact}>
                    {fact}
                  </li>
                ))}
              </ul>
            </section>
            {companies.map(({ view, connection, position }) => (
              <CompanyInIssue
                key={view.company.id}
                view={view}
                compact={compact}
                commonFacts={facts}
                connection={connection}
                position={position}
                sentiments={sentiments}
                evening={result.edition === 'evening'}
              />
            ))}
            <IssueFollowUp
              comparisonState={comparisonState}
              view={summaryView}
              result={result}
              hideComparison={
                group.members.length > 1 &&
                group.members.some((m) =>
                  m.companies.some(
                    (c) =>
                      c.previous ||
                      (c.comparison && c.comparison.status !== 'unavailable'),
                  ),
                )
              }
            />
            {group.members.length > 1 ? (
              <details>
                <summary
                  className={`min-h-11 cursor-pointer content-center text-caption ${FOCUS_RING}`}
                >
                  세부 사건의 원래 분석·근거·평가
                </summary>
                <div className="space-y-5">
                  {group.members.map((member) => (
                    <section
                      key={member.item.eventId}
                      aria-label={`${member.item.title} 원래 분석`}
                    >
                      <h4 className="text-body font-bold">
                        {member.item.title}
                      </h4>
                      <p className={`${NOTE} mt-2`}>
                        {member.item.reason}
                        {articleCount(member.item)}
                      </p>
                      {member.companies.map((view) => {
                        const connection = group.selections
                          .find((s) => s.issueId === member.item.eventId)
                          ?.connections.find(
                            (c) => c.companyId === view.company.id,
                          );
                        return (
                          <CompanyInIssue
                            key={view.company.id}
                            view={view}
                            compact={false}
                            commonFacts={facts}
                            connection={connection?.basis.text ?? ''}
                            position={connection?.position ?? 'unconfirmed'}
                            sentiments={member.item.documentSentiments}
                            evening={result.edition === 'evening'}
                          />
                        );
                      })}
                      <IssueFollowUp
                        view={member}
                        result={result}
                        comparisonState={comparisonState}
                      />
                      <details>
                        <summary
                          className={`min-h-11 cursor-pointer content-center text-caption ${FOCUS_RING}`}
                        >
                          기업별 독립 검증·추가 근거
                        </summary>
                        <BriefingS3Impacts round={result} item={member.item} />
                      </details>
                      <BriefingItemDetails
                        roundId={result.id}
                        graphVersion={result.graphVersion}
                        item={member.item}
                        evidenceOnly
                      />
                      {renderExtra?.(member.item)}
                    </section>
                  ))}
                </div>
              </details>
            ) : (
              <>
                <details>
                  <summary
                    className={`min-h-11 cursor-pointer content-center text-body font-semibold ${FOCUS_RING}`}
                  >
                    기업별 독립 검증·추가 근거
                  </summary>
                  <BriefingS3Impacts
                    key={`${result.id}:${item.eventId}:${result.graphVersion}`}
                    round={result}
                    item={item}
                  />
                </details>
                <BriefingItemDetails
                  roundId={result.id}
                  graphVersion={result.graphVersion}
                  item={displayedItem}
                  evidenceOnly
                />
                <details>
                  <summary
                    className={`min-h-11 cursor-pointer content-center text-caption ${FOCUS_RING}`}
                  >
                    선정 이유
                  </summary>
                  <p className={NOTE}>{item.reason}</p>
                </details>
                {renderExtra?.(displayedItem)}
              </>
            )}
            {group.selections.length > 0 && (
              <details>
                <summary
                  className={`min-h-11 cursor-pointer content-center text-caption ${FOCUS_RING}`}
                >
                  선정 근거 전체
                </summary>
                {group.selections.map((s) => (
                  <div className="space-y-2 py-2" key={s.issueId}>
                    <p className={BODY}>
                      <b>사건 중요도 · </b>
                      {s.whyImportant.text}
                    </p>
                    <p className={BODY}>
                      <b>이번 회차의 새 정보 · </b>
                      {s.whyNow.text}
                    </p>
                    <p className={NOTE}>
                      {s.priceUsedForRanking
                        ? '비교 가능한 가격 관측을 동순위 보강에 사용'
                        : '가격 관측은 순위 보강에 사용하지 않음'}
                    </p>
                  </div>
                ))}
              </details>
            )}
          </div>
        )}
      </details>
      {corrections.length > 0 && (
        // 접힌 카드에서도 정정이 보이도록 카드 아래쪽 테두리 안에 붙여 둔다.
        <div className="rounded-b-2xl border border-t-0 border-zoop-line bg-zoop-paper px-5 pb-5 sm:px-6">
          <IssueCorrections corrections={corrections} />
        </div>
      )}
    </li>
  );
}

/** D-BRF-01/02: indicators → issues; companies belong inside an issue, never dedupe selection by company. */
export default function IssueCentricBriefing({
  result,
  items = result.items,
  renderExtra,
  compact = true,
  issueCorrections,
}: {
  result: BriefingResponse;
  items?: BriefingItem[];
  /** 55: 화면에 있는 이슈에 붙는 정정(eventId별) */
  issueCorrections?: Map<string, Correction[]>;
  compact?: boolean;
  renderExtra?: (item: BriefingItem) => ReactNode;
}) {
  const [history, setHistory] = useState<{
    key: string;
    status: 'loading' | 'error' | 'ready';
    value?: BriefingResponse;
  }>();
  const [historyAttempt, setHistoryAttempt] = useState(0);
  const prior = result.issueIntelligence
    ? null
    : validEditionReview(result)?.previousReview;
  const priorDate = prior?.date,
    priorEdition = prior?.edition,
    priorId = prior?.roundId;
  const historyKey = `${result.id}:${priorId}:${priorDate}:${priorEdition}:${historyAttempt}`;
  const needsHistory = Boolean(priorDate && priorEdition && priorId);
  const comparisonState = !needsHistory
    ? 'ready'
    : history?.key === historyKey
      ? history.status
      : 'loading';
  const previous =
    history?.key === historyKey && history.status === 'ready'
      ? history.value
      : undefined;
  useEffect(() => {
    let active = true;
    if (priorDate && priorEdition && priorId)
      getBriefing(priorDate, priorEdition)
        .then((value) => {
          if (
            value.id !== priorId ||
            value.date !== priorDate ||
            value.edition !== priorEdition
          )
            throw new Error('previous_round_mismatch');
          if (active) setHistory({ key: historyKey, status: 'ready', value });
        })
        .catch(() => {
          if (active) setHistory({ key: historyKey, status: 'error' });
        });
    return () => {
      active = false;
    };
  }, [priorDate, priorEdition, priorId, historyKey]);
  const views = briefingIssueViews(
    result,
    items,
    previous?.id === priorId ? previous : undefined,
  );
  const groups = readingGroups(result, views, compact);
  return (
    <div data-presentation="issue-centered">
      <MarketIndicators
        variables={result.marketVariables}
        compact
        showBaseline
      />
      {result.items.length === 0 &&
        result.emptyReason === 'no_issues_in_window' &&
        !result.issueIntelligence &&
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
      {comparisonState === 'error' && (
        <p role="alert" className={EMPTY}>
          이전 회차를 불러오지 못했어요. 현재 브리핑은 계속 볼 수 있습니다.{' '}
          <button
            type="button"
            className={`underline ${FOCUS_RING}`}
            onClick={() => setHistoryAttempt((n) => n + 1)}
          >
            이전 회차 다시 확인
          </button>
        </p>
      )}
      <section className={SECTION} aria-label="핵심 이슈 중심 브리핑">
        {result.issueIntelligence && !validIssueIntelligence(result) && (
          <p role="alert" className={EMPTY}>
            새 분석의 회차·이슈·근거 연결을 확인하지 못했습니다.
          </p>
        )}
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h3 className={SECTION_TITLE}>핵심 이슈</h3>
          {!result.issueIntelligence && (
            <Link
              to={`/?round=${encodeURIComponent(result.id)}`}
              className={`text-caption underline ${FOCUS_RING}`}
            >
              이슈 관계 지도 ↗
            </Link>
          )}
        </div>
        {result.issueReading && !validIssueReading(result) && (
          <p role="alert" className={EMPTY}>
            사건 통합 검토의 근거·버전이 맞지 않아 원래 이슈 목록을 표시합니다.
          </p>
        )}
        {!compact && !!validIssueReading(result)?.groups.length && (
          <p className={`${NOTE} mb-3`}>
            묶기 전 세부 사건별 분석과 평가를 원래 항목으로 보존한 보기입니다.
          </p>
        )}
        {groups.length ? (
          <ol className="space-y-3">
            {groups.map((group, index) => (
              <IssueCard
                key={group.id}
                group={group}
                rank={index + 1}
                comparisonState={comparisonState}
                compact={compact}
                result={result}
                renderExtra={renderExtra}
                corrections={group.members.flatMap(
                  (m) => issueCorrections?.get(m.item.eventId) ?? [],
                )}
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
