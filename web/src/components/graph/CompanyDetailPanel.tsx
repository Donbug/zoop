import { companyLogo } from '@/util/company-logo';
import CompanyLogo from '@/components/common/CompanyLogo';
import type { EventContext } from '@/types/map/event';
import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import LoadingIndicator from '@/components/common/LoadingIndicator';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { setWatchlistCompany } from '@/apis/graph/companies';
import { useCompanyData } from '@/hooks/useCompanyData';
import type { GraphNode, GraphResponse } from '@/types/map/graph';
import type { CompanyIssue } from '@/types/map/company';
import { relatedCompaniesHelp, relationHelp } from './relation-help';
import DocumentSentiment from './DocumentSentiment';
import type { WatchSync } from '@/types/map';
import IssueDocumentSentiments from './IssueDocumentSentiments';
import { visibleSentiment } from './visible-sentiment';
import { eventTimeText } from '@/util/event-time';

type RelatedCompany = { id: string; name: string; sharedIssueCount: number };
type Props = {
  companyId: string;
  panelWidth?: number;
  companyDetailHref?: (id: string) => string;
  context?: EventContext;
  fallback: GraphNode;
  relatedCompanies: RelatedCompany[];
  token: string | null;
  /** 지도 화면에서 마지막으로 저장한 관심 목록(사이드바에서 저장한 것 포함). */
  watchSync?: WatchSync | null;
  onWatchSaved?: (watchlistIds: string[]) => void;
  onClose: () => void;
  onSelectIssue: (id: string) => void;
  tutorialIssueId?: string;
  tutorialAi?: boolean;
  tutorialSaving?: boolean;
  onFocus: () => void;
  onSelectRelation?: (companyId: string) => void;
  /** 지도에 함께 밝게 표시 중인 관련 기업. */
  activeRelatedId?: string | null;
  onAskAi: () => void;
  /** 지금 지도 그래프: 직접 사건의 앞뒤 사건(FOLLOWS), 관련 기업 로고, 사건 근거, 중심 버튼 조건에 쓴다. */
  graph?: Pick<GraphResponse, 'nodes' | 'edges'> | null;
  /** 지금 지도의 중심 노드. 이 기업이 이미 중심이면 [기업 중심 그래프]를 숨긴다. */
  focusId?: string | null;
  /** 사건 줄의 [근거 보기]: 지도에서 찾은 그 사건의 근거로 근거 창을 연다. */
  onIssueEvidence?: (issue: {
    id: string;
    title: string;
    evidenceIds: string[];
  }) => void;
};

/** 패널 사건 목록 한 줄: 기업 API 사건 또는 지도에서 찾은 직접 사건의 앞뒤 사건. */
type PanelIssue = Pick<
  CompanyIssue,
  'title' | 'eventTime' | 'timePrecision' | 'role'
> & {
  issueId: string;
  evidenceCount: number | null;
  /** 간접 사건이 이어진 이유(구조적 관련, 앞선·이어진 사건) */
  why?: string;
};

const VISIBLE_ISSUES = 3;
const VISIBLE_DOCUMENTS = 3;

/** 섹션 머리 옆 정보 아이콘: 관계 유형의 뜻(prototype node-panel.tsx RelationHint). */
function RelationHint({ label, text }: { label: string; text: string }) {
  return (
    <details className="company-source">
      <summary aria-label={`${label} 설명`}>i</summary>
      <p className="right-auto! left-0!">{text}</p>
    </details>
  );
}

/**
 * D-GRP-03 · prototype node-panel.tsx:185-204: 간접 사건은 구조적 관련 사건과, 지도에서 FOLLOWS 선으로 이어진 직접 사건의
 * 앞뒤 사건이다. FOLLOWS는 나중 사건에서 앞선 사건으로 향한다.
 */
function indirectIssues(
  direct: CompanyIssue[],
  structural: CompanyIssue[],
  graph: Props['graph'],
): PanelIssue[] {
  const directIds = new Set(direct.map((issue) => issue.issueId));
  const seen = new Set(directIds);
  const list: PanelIssue[] = structural
    .filter((issue) => !seen.has(issue.issueId) && seen.add(issue.issueId))
    .map((issue) => ({ ...issue, why: '구조적 관련' }));
  for (const edge of graph?.edges ?? []) {
    if (edge.relationType !== 'FOLLOWS') continue;
    const [anchor, other, why] = directIds.has(edge.target)
      ? [edge.target, edge.source, '이어진 사건']
      : directIds.has(edge.source)
        ? [edge.source, edge.target, '앞선 사건']
        : [];
    const node = graph?.nodes.find((item) => item.id === other);
    if (!anchor || !node || node.kind !== 'issue' || seen.has(node.id))
      continue;
    seen.add(node.id);
    const title = direct.find((issue) => issue.issueId === anchor)?.title;
    list.push({
      issueId: node.id,
      title: node.label,
      eventTime: node.eventTime,
      timePrecision: node.timePrecision,
      evidenceCount: node.evidenceCount,
      why: title ? `${why} · ${title}` : why,
    });
  }
  return list;
}

/** 지도에서 이 기업과 사건을 잇는 선의 근거. 그런 선이 없으면 그 사건에 닿은 선(공유 선 제외)의 근거. */
function issueEvidence(
  graph: Props['graph'],
  companyId: string,
  issueId: string,
) {
  const touching = (graph?.edges ?? []).filter(
    (edge) =>
      edge.relationType !== 'SHARES_ISSUE' &&
      (edge.source === issueId || edge.target === issueId),
  );
  const own = touching.filter(
    (edge) => edge.source === companyId || edge.target === companyId,
  );
  return [
    ...new Set((own.length ? own : touching).flatMap((e) => e.evidenceIds)),
  ];
}

function number(value: number | null, currency?: string) {
  if (value === null) return '—';
  return new Intl.NumberFormat('ko-KR', {
    maximumFractionDigits: currency === 'KRW' ? 0 : 2,
  }).format(value);
}

function Sparkline({ values }: { values: number[] }) {
  const points = useMemo(() => {
    if (values.length < 2) return '';
    const min = Math.min(...values);
    const range = Math.max(1, Math.max(...values) - min);
    return values
      .map(
        (value, index) =>
          `${(index / (values.length - 1)) * 280},${76 - ((value - min) / range) * 64}`,
      )
      .join(' ');
  }, [values]);
  return (
    <svg
      className="company-sparkline"
      viewBox="0 0 280 84"
      role="img"
      aria-label="최근 1개월 가격 추이"
    >
      <line x1="0" y1="76" x2="280" y2="76" />
      <polyline points={points} />
    </svg>
  );
}

function SectionError({
  message,
  retry,
}: {
  message?: string;
  retry: () => void;
}) {
  if (!message) return null;
  return (
    <p className="company-section-error" role="alert">
      일부 정보를 불러오지 못했습니다.{' '}
      <button data-tutorial-action="retry" onClick={retry}>
        다시 시도
      </button>
    </p>
  );
}

// WBS 6.6.23 · D-GRP-03 · Figma 619:6729
export default function CompanyDetailPanel(props: Props) {
  // 로그인 뒤 같은 지도·같은 기업으로 돌아와 관심 추가를 다시 누를 수 있게 지금 위치를 넘긴다.
  const location = useLocation();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [props.companyId]);
  const [retry, setRetry] = useState(0);
  const { data, loading, marketLoading, errors } = useCompanyData(
    props.companyId,
    props.token,
    retry,
    props.context,
  );
  const [watchOverride, setWatchOverride] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const [watchError, setWatchError] = useState('');
  // 사이드바에서 이 기업의 관심을 바꾸면 ★도 같은 목록으로 맞춘다. 저장 중에는 내 저장 결과를 기다린다.
  const [appliedSync, setAppliedSync] = useState(props.watchSync?.seq ?? 0);
  if (props.watchSync && props.watchSync.seq !== appliedSync) {
    setAppliedSync(props.watchSync.seq);
    if (!saving)
      setWatchOverride(props.watchSync.ids.includes(props.companyId));
  }
  const company = data?.company;
  // 그래프 응답 전에는 지도 노드가 가진 관심 표시로 시작한다.
  const watch =
    watchOverride ?? Boolean(company?.watch ?? props.fallback.watch);

  async function toggleWatch() {
    if (!props.token || saving) return;
    const previous = watch;
    const desired = !previous;
    setWatchOverride(desired);
    setSaving(true);
    setWatchError('');
    try {
      const settings = await setWatchlistCompany(props.companyId, desired);
      setWatchOverride(settings.watchlistIds.includes(props.companyId));
      props.onWatchSaved?.(settings.watchlistIds);
    } catch {
      setWatchOverride(previous);
      setWatchError('관심기업 저장에 실패했습니다. 다시 시도해 주세요.');
    } finally {
      setSaving(false);
    }
  }

  const quote = data?.quote?.status === 'available' ? data.quote : null;
  const prices = data?.prices?.status === 'available' ? data.prices : null;
  const metrics = data?.metrics?.status === 'available' ? data.metrics : null;
  const holding = data?.holding;
  const name = company?.name ?? props.fallback.label;
  const logoUrl = companyLogo(
    props.fallback.id,
    company?.logoUrl ?? props.fallback.logoUrl,
  );
  const currency = quote?.quote.currency;
  const changePositive = (quote?.quote.change ?? 0) >= 0;
  // D-GRP-03 · prototype node-panel.tsx:285-290: 관련 기업 줄에 로고를 둔다. 누르면 두 기업과
  // 공유 사건만 지도에 밝게 표시한다(사건 공유 선은 2026-11-04부터 그리지 않는다).
  const relatedItem = (related: RelatedCompany) => {
    const node = props.graph?.nodes.find((item) => item.id === related.id);
    return (
      <li key={related.id}>
        <button
          className="flex-row! items-center! gap-3!"
          aria-pressed={props.activeRelatedId === related.id}
          onClick={() => props.onSelectRelation?.(related.id)}
        >
          <CompanyLogo
            name={related.name}
            logoUrl={companyLogo(related.id, node?.logoUrl ?? null)}
            className="grid! size-8 rounded-full border border-zoop-line bg-zoop-paper p-0! text-caption font-bold"
          />
          <div className="min-w-0 flex-1">
            <b>{related.name}</b>
            <span>공유 사건 {related.sharedIssueCount}건</span>
          </div>
        </button>
      </li>
    );
  };
  // M9 · prototype node-panel.tsx:110-111: 연결이 없거나 이미 이 기업이 중심이면 중심 보기를 숨긴다.
  const canFocus =
    props.focusId !== props.companyId &&
    (!props.graph ||
      props.graph.edges.some(
        (edge) =>
          edge.source === props.companyId || edge.target === props.companyId,
      ));
  const issueRow = (issue: PanelIssue, indirect: boolean) => {
    const tutorial = props.tutorialIssueId === issue.issueId;
    const evidenceIds = props.onIssueEvidence
      ? issueEvidence(props.graph, props.companyId, issue.issueId)
      : [];
    const time =
      eventTimeText(issue.eventTime, issue.timePrecision) ?? '시각 미상';
    return (
      <li key={issue.issueId}>
        <button
          className={tutorial ? 'tutorial-target' : undefined}
          data-tutorial-action={tutorial ? 'issue' : undefined}
          onClick={() => props.onSelectIssue(issue.issueId)}
        >
          <b>{issue.title}</b>
          <span>
            {indirect ? `${time} · ${issue.why}` : time}
            {issue.evidenceCount !== null && ` · 근거 ${issue.evidenceCount}건`}
          </span>
          {issue.role && (
            <span>
              역할 · {issue.role === 'participant' ? '참여 기업' : issue.role}
            </span>
          )}
        </button>
        {evidenceIds.length > 0 && (
          <div className="px-3 pb-2">
            <button
              type="button"
              className="w-auto! rounded-panel border border-zoop-line bg-zoop-paper px-2.5! py-1! text-caption font-semibold text-zoop-ink hover:bg-zoop-soft"
              onClick={() =>
                props.onIssueEvidence?.({
                  id: issue.issueId,
                  title: issue.title,
                  evidenceIds,
                })
              }
            >
              근거 {evidenceIds.length}건 보기
            </button>
          </div>
        )}
        <IssueDocumentSentiments
          documents={data?.documents?.items ?? []}
          companyId={props.companyId}
          issueId={issue.issueId}
        />
      </li>
    );
  };
  // M2 · prototype node-panel.tsx:255-256,275: 사건은 3건만 펼치고 나머지는 접는다. 튜토리얼 대상이 접힌 쪽이면 펼친다.
  const issueList = (
    issues: PanelIssue[],
    indirect: boolean,
    label: string,
  ) => {
    const rest = issues.slice(VISIBLE_ISSUES);
    return (
      <>
        <ul className="company-list">
          {issues.slice(0, VISIBLE_ISSUES).map((i) => issueRow(i, indirect))}
        </ul>
        {rest.length > 0 && (
          <details
            className="company-aliases"
            open={
              rest.some((issue) => issue.issueId === props.tutorialIssueId) ||
              undefined
            }
          >
            <summary>
              {label} {rest.length}건 더 보기
            </summary>
            <ul className="company-list mt-2">
              {rest.map((issue) => issueRow(issue, indirect))}
            </ul>
          </details>
        )}
      </>
    );
  };
  const indirect = company
    ? indirectIssues(
        company.directIssues,
        company.structuralIssues,
        props.graph,
      )
    : [];
  const documents = data?.documents?.items ?? [];

  return (
    <aside
      id="company-detail-panel"
      className={`company-panel ${ui.shell}`}
      style={props.panelWidth ? { width: `${props.panelWidth}px` } : undefined}
      data-screen-id="D-GRP-03"
      aria-label={`${name} 기업 상세`}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.stopPropagation();
          props.onClose();
        }
      }}
    >
      <header className="company-panel-header">
        {/* D-GRP-03: 로고·종목코드·기업명·가격·등락을 한 덩어리로 모은다(증권 앱의 종목 머리와 같은 순서). */}
        <div className="flex items-start gap-3">
          <CompanyLogo
            name={name}
            logoUrl={logoUrl}
            className="size-14 shrink-0 rounded-full border border-zoop-line bg-zoop-paper text-title-sm font-extrabold"
          />
          <div className="min-w-0 flex-1">
            <p className="company-code">
              {[
                company?.ticker ?? props.companyId.split(':')[1],
                company?.market,
                company?.sector,
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>
            <h2 className={ui.title} ref={heading} tabIndex={-1}>
              {name}
            </h2>
            {/* D-GRP-03: 별칭은 기업명 아래에서 펼쳐 확인해요. */}
            {company && company.aliases.length > 0 && (
              <details className="company-aliases">
                <summary>기업명 더 보기</summary>
                <p>{company.aliases.join(' · ')}</p>
              </details>
            )}
            {quote && (
              <>
                <div className="company-price-row">
                  <strong>
                    {number(quote.quote.price, currency)}{' '}
                    <small>{currency}</small>
                  </strong>
                  <p className={changePositive ? 'up' : 'down'}>
                    {changePositive ? '▲ +' : '▼ '}
                    {number(quote.quote.change, currency)} (
                    {changePositive ? '+' : ''}
                    {((quote.quote.changeRate ?? 0) * 100).toFixed(2)}%)
                  </p>
                </div>
                {/* 언제 기준의 값인지 알려 주는 보조 정보라 아래 중요 정보보다 작게 둔다. */}
                <div className="company-quote-meta">
                  <span>
                    {quote.quote.asOf
                      ? `${new Date(quote.quote.asOf).toLocaleString('ko-KR', {
                          month: 'numeric',
                          day: 'numeric',
                          hour: 'numeric',
                          minute: '2-digit',
                        })} 기준`
                      : '기준 시각 미제공'}{' '}
                    · 전일 대비 · {quote.source.name}
                    {quote.source.delayNote ? ' · 지연 가능' : ''}
                  </span>
                  <details className="company-source">
                    <summary aria-label={`시세 출처: ${quote.source.name}`}>
                      i
                    </summary>
                    <p>
                      {quote.source.name} ·{' '}
                      {quote.source.official ? '공식' : '공개 자료'} · 종목 기호{' '}
                      {quote.source.symbol}
                    </p>
                  </details>
                </div>
              </>
            )}
          </div>
          <button
            className={ui.close}
            onClick={props.onClose}
            aria-label="기업 상세 닫기"
          >
            ×
          </button>
        </div>
        <div className="company-identity">
          <div className="company-statuses">
            {(company?.holding || props.fallback.holding) && (
              <span>보유 종목</span>
            )}
            {(company?.watch || props.fallback.watch) && <span>관심 종목</span>}
          </div>
        </div>
      </header>
      {/* 그래프 응답(사건·뉴스·공시)과 그 외 응답(시세·지표·보유)은 따로 도착한다. 패널은 바로 열고
          기업명·로고·보유·관심은 지도 노드 값으로 먼저 보인다. 그래프 응답은 해당 섹션에서만 기다린다. */}
      <div className={`company-panel-scroll ${ui.scroll}`}>
        {/* 기업 머리 바로 아래에 주요 동작을 둔다(시세 박스보다 먼저). */}
        <div className={`company-actions ${ui.actions}`}>
          <Link
            state={{
              from: `${location.pathname}${location.search}${location.hash}`,
            }}
            to={
              props.companyDetailHref?.(props.companyId) ??
              `/companies/${encodeURIComponent(props.companyId)}`
            }
          >
            기업 상세
          </Link>
          {props.token ? (
            <button
              onClick={() => void toggleWatch()}
              disabled={saving}
              aria-pressed={watch}
            >
              {saving ? '저장 중…' : watch ? '★ 관심 해제' : '☆ 관심 추가'}
            </button>
          ) : (
            <Link to="/login" state={{ from: location }}>
              로그인 후 관심 추가
            </Link>
          )}
          {canFocus && (
            <button onClick={props.onFocus}>기업 중심 그래프</button>
          )}
          <button
            className={`bg-panel-ink! text-white! ${props.tutorialAi ? 'tutorial-target tutorial-ai-target' : ''}`}
            disabled={props.tutorialSaving}
            onClick={props.onAskAi}
          >
            AI에게 질문
          </button>
        </div>
        {watchError && (
          <p className="company-watch-error" role="alert">
            {watchError}{' '}
            <button onClick={() => void toggleWatch()}>재시도</button>
          </p>
        )}
        <section className={`company-quote ${ui.sectionFrame}`}>
          <h3 className="sr-only">시세</h3>
          {/* 시세·가격·지표·보유는 그래프 응답과 따로 도착한다. 기다리는 동안 이 자리에만 표시한다. */}
          {marketLoading && (
            <LoadingIndicator
              label="시세 정보를 불러오는 중"
              className="flex min-h-12 w-full"
            />
          )}
          {quote ? (
            <>
              <div className="company-stat-grid">
                <span>
                  거래량 <b>{number(quote.quote.volume)}</b>
                </span>
                <span>
                  일중 범위{' '}
                  <b>
                    {number(quote.quote.dayLow)}–{number(quote.quote.dayHigh)}
                  </b>
                </span>
                <span>
                  52주 범위{' '}
                  <b>
                    {number(quote.quote.fiftyTwoWeekLow)}–
                    {number(quote.quote.fiftyTwoWeekHigh)}
                  </b>
                </span>
              </div>
            </>
          ) : data?.quote?.status === 'unavailable' ? (
            <p className="company-unavailable">
              시세 미제공 · {data.quote.reason}
            </p>
          ) : null}
          <SectionError
            message={errors.quote}
            retry={() => setRetry((value) => value + 1)}
          />
          {prices ? (
            <figure className="company-price-chart">
              <figcaption>최근 1개월 시세 추이</figcaption>
              <Sparkline values={prices.points.map((point) => point.close)} />
              <p className="company-chart-range">
                <span>{prices.points.at(0)?.time.slice(0, 10)}</span>
                <span>{prices.points.at(-1)?.time.slice(0, 10)}</span>
              </p>
              <p className="company-caption">
                {prices.source.name} · 마지막 거래{' '}
                {prices.points.at(-1)?.time.slice(0, 10)}
              </p>
            </figure>
          ) : data?.prices?.status === 'unavailable' ? (
            <p className="company-unavailable">
              가격 추이 미제공 · {data.prices.reason}
            </p>
          ) : null}
          <SectionError
            message={errors.prices}
            retry={() => setRetry((value) => value + 1)}
          />
        </section>
        <details className={`company-metrics ${ui.sectionFrame}`}>
          <summary>
            주요 지표 <span>{metrics ? `${metrics.items.length}개` : '—'}</span>
          </summary>
          {metrics?.items.map((item) => (
            <p key={item.code}>
              <span>{item.label}</span>
              <b>{item.value}</b>
            </p>
          ))}
          {data?.metrics?.status === 'unavailable' && (
            <p className="company-unavailable">
              지표 미제공 · {data.metrics.reason}
            </p>
          )}
          <SectionError
            message={errors.metrics}
            retry={() => setRetry((value) => value + 1)}
          />
        </details>
        {(holding || errors.holding) && (
          <section className={ui.sectionFrame}>
            <div className="company-section-title">
              <h3>가상 계좌 보유</h3>
            </div>
            {holding ? (
              <div className="company-holding">
                <span>
                  수량 <b>{number(holding.quantity)}주</b>
                </span>
                <span>
                  평균 단가{' '}
                  <b>
                    {number(holding.avgPrice)} {holding.avgPriceCurrency}
                  </b>
                </span>
                <span>
                  평가액{' '}
                  <b>
                    {holding.marketValue === null
                      ? '제공되지 않음'
                      : number(holding.marketValue)}
                  </b>
                </span>
                <span>
                  비중{' '}
                  <b>{holding.weight === null ? '-' : `${holding.weight}%`}</b>
                </span>
              </div>
            ) : errors.holding ? null : (
              <p className="company-unavailable">
                이 기업의 모의 보유 내역이 없습니다.
              </p>
            )}
            <SectionError
              message={errors.holding}
              retry={() => setRetry((value) => value + 1)}
            />
          </section>
        )}
        {!company && (
          <section className={ui.sectionFrame}>
            {loading ? (
              <LoadingIndicator
                label="관련 사건을 불러오는 중"
                className="company-panel-loading flex min-h-12 w-full"
              />
            ) : (
              <div className="company-panel-fatal" role="alert">
                <p>관련 사건을 불러오지 못했습니다.</p>
                <button onClick={() => setRetry((value) => value + 1)}>
                  다시 시도
                </button>
              </div>
            )}
          </section>
        )}
        {company && (
          <>
            <section className={ui.sectionFrame}>
              <div className="company-section-title">
                <div className="flex items-center gap-1.5">
                  <h3>직접 관련 사건</h3>
                  <RelationHint
                    label="직접 관련"
                    text={relationHelp.INVOLVES}
                  />
                </div>
                <span>{company.directIssues.length}</span>
              </div>
              {company.directIssues.length ? (
                issueList(company.directIssues, false, '직접 관련 사건')
              ) : (
                <p className="company-unavailable">
                  직접 관련 사건이 없습니다.
                </p>
              )}
            </section>
            <section className={ui.sectionFrame}>
              <div className="company-section-title">
                <div className="flex items-center gap-1.5">
                  <h3>간접 관련 사건</h3>
                  <RelationHint
                    label="간접 관련"
                    text={`기사에 이 기업이 직접 나오지는 않지만 데이터로 이어진 사건입니다. ${relationHelp.STRUCTURALLY_RELATED_TO} ${relationHelp.FOLLOWS}`}
                  />
                </div>
                <span>{indirect.length}</span>
              </div>
              {indirect.length ? (
                issueList(indirect, true, '간접 관련 사건')
              ) : (
                <p className="company-unavailable">
                  확인된 간접 관련 사건이 없습니다.
                </p>
              )}
            </section>
          </>
        )}
        <section className={ui.sectionFrame}>
          <div className="company-section-title">
            <div className="flex items-center gap-1.5">
              <h3>관련 기업</h3>
              <RelationHint label="관련 기업" text={relatedCompaniesHelp} />
            </div>
            <span>{props.relatedCompanies.length}</span>
          </div>
          {props.relatedCompanies.length ? (
            <>
              <ul className="company-list company-related-companies">
                {props.relatedCompanies.slice(0, 5).map(relatedItem)}
              </ul>
              {/* 6곳부터는 접어 두고, 펼치면 나머지를 같은 목록으로 보여 준다. */}
              {props.relatedCompanies.length > 5 && (
                <details className="company-aliases">
                  <summary>
                    관련 기업 {props.relatedCompanies.length - 5}곳 더 보기
                  </summary>
                  <ul className="company-list company-related-companies">
                    {props.relatedCompanies.slice(5).map(relatedItem)}
                  </ul>
                </details>
              )}
            </>
          ) : (
            <p className="company-unavailable">확인된 관련 기업이 없습니다.</p>
          )}
        </section>
        <section className={ui.sectionFrame}>
          <div className="company-section-title">
            <h3>뉴스·공시</h3>
            <span>{data?.documents?.items.length ?? '—'}</span>
          </div>
          {loading && (
            <LoadingIndicator
              label="뉴스·공시를 불러오는 중"
              className="flex min-h-12 w-full"
            />
          )}
          {documents.length ? (
            <ul className="company-list">
              {/* M7 · prototype company-summary.tsx:76-81: 최근 3건과 문서별 판정만 보이고, 전체는 기업 상세 문서 탭으로 보낸다. */}
              {documents.slice(0, VISIBLE_DOCUMENTS).map((document) => (
                <li key={document.id}>
                  {document.url ? (
                    <a href={document.url} target="_blank" rel="noreferrer">
                      <b>{document.title ?? '제목 없음'}</b>
                      <span>
                        {document.kind === 'news' ? '뉴스' : '공시'} ·{' '}
                        {document.publisher ?? '출처 미상'} ·{' '}
                        {document.publishedAt?.slice(0, 10) ?? '시각 미상'}
                      </span>
                    </a>
                  ) : (
                    <div className="company-document">
                      <b>{document.title ?? '제목 없음'}</b>
                      <span>
                        {document.kind === 'news' ? '뉴스' : '공시'} ·{' '}
                        {document.publisher ?? '출처 미상'} · 원문 링크 미제공
                      </span>
                    </div>
                  )}
                  <DocumentSentimentLine
                    document={document}
                    companyId={props.companyId}
                  />
                </li>
              ))}
            </ul>
          ) : !loading && !errors.documents ? (
            <p className="company-unavailable">표시할 뉴스·공시가 없습니다.</p>
          ) : null}
          {documents.length > VISIBLE_DOCUMENTS && (
            <p className="company-unavailable mt-2">
              최근 {VISIBLE_DOCUMENTS}건만 보여요. 전체 뉴스·공시는{' '}
              <Link
                className="underline"
                state={{
                  from: `${location.pathname}${location.search}${location.hash}`,
                }}
                to={documentsHref(
                  props.companyDetailHref?.(props.companyId) ??
                    `/companies/${encodeURIComponent(props.companyId)}`,
                )}
              >
                기업 상세 문서
              </Link>
              에서 볼 수 있어요.
            </p>
          )}
          <SectionError
            message={errors.documents}
            retry={() => setRetry((value) => value + 1)}
          />
        </section>
      </div>
    </aside>
  );
}

/** 기업 상세 주소에 문서 탭을 더한다(이미 있는 쿼리는 그대로). */
function documentsHref(href: string) {
  const [path, query = ''] = href.split('?');
  const params = new URLSearchParams(query);
  params.set('tab', 'documents');
  return `${path}?${params}`;
}

function DocumentSentimentLine({
  document,
  companyId,
}: {
  document: import('@/types/map/company').CompanyDocument;
  companyId: string;
}) {
  const sentiment = visibleSentiment(document, companyId);
  if (!sentiment) return null;
  return (
    <div className="px-3 pb-2 text-zoop-muted">
      <DocumentSentiment
        value={sentiment}
        name={document.title ?? '뉴스·공시 문서'}
      />
    </div>
  );
}
