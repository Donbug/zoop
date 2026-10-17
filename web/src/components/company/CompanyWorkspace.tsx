import PriceChart from './PriceChart';
import CompanyInfoTab from './CompanyInfoTab';
import { useEffect } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { useAuthStore } from '@/stores/useAuthStore';
import { useCompanyResource, type Resource } from '@/hooks/useCompanyResource';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import { companyUrl } from '@/apis/company/company';
import type {
  Company,
  Quote,
  Prices,
  Portfolio,
  Events,
  EventDetail,
  Financials,
  Impact,
  Meta,
} from '@/types/company/detail';
import type { ChartPeriod } from '@/types/company';
import type { GraphResponse } from '@/types/map/graph';
import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import CompanyCatalog from './CompanyCatalog';
import CompanyDocumentPanel from './CompanyDocumentPanel';
import CompanyGraphPreview from './CompanyGraphPreview';
import {
  periods,
  exactTime,
  timeRange,
  bucketKey,
  impactEdges,
  selectTime,
  number,
} from './detail-model';

const workspaceClasses =
  'company-workspace grid grid-cols-[200px_minmax(0,1fr)_280px] gap-0 m-0 overflow-hidden rounded-[5px] border border-[var(--zoop-line)] bg-[var(--zoop-soft)] text-[var(--zoop-ink)] max-[1000px]:grid-cols-[160px_minmax(0,1fr)] max-md:flex max-md:flex-col [&_section]:border-b [&_section]:border-[var(--zoop-line)] [&_section]:py-4 [&_h1]:text-[26px] [&_h1]:font-bold [&_h1]:tracking-[-0.035em] [&_h2]:mb-3 [&_h2]:text-sm [&_h2]:font-bold [&_h2]:tracking-[-0.025em] [&_h3]:font-semibold [&_p]:text-xs [&_p]:text-[var(--zoop-muted)] [&_p]:leading-[1.7] [&_button]:cursor-pointer [&_button]:rounded-[3px] [&_button]:border [&_button]:border-[var(--zoop-line)] [&_button]:bg-white [&_button]:min-h-[34px] [&_button]:px-[9px] [&_button]:py-1.5 [&_button]:text-xs! [&_button[aria-pressed=true]]:bg-[var(--zoop-ink)] [&_button[aria-pressed=true]]:text-white [&_button:disabled]:opacity-50 [&_button:disabled]:cursor-default [&_a]:cursor-pointer [&_a]:px-[9px] [&_a]:py-1.5 [&_a]:text-xs [&_button:focus-visible]:outline-2 [&_button:focus-visible]:outline-offset-2 [&_button:focus-visible]:outline-[var(--zoop-ink)] [&_a:focus-visible]:outline-2 [&_a:focus-visible]:outline-offset-2 [&_a:focus-visible]:outline-[var(--zoop-ink)] [&_nav]:my-3 [&_nav]:flex [&_nav]:flex-wrap [&_nav]:gap-1 [&_article]:border-b [&_article]:border-[var(--zoop-line)] [&_article]:py-3 [&_table]:w-full [&_table]:text-xs [&_table]:wrap-anywhere [&_[role=alert]]:text-[#a12828] [&_details]:my-3 [&_input]:max-w-full [&_input]:rounded-[3px] [&_input]:border [&_input]:border-[var(--zoop-line)] [&_input]:bg-white [&_input]:px-2 [&_input]:py-1.5 [&_input]:min-h-[34px] [&_input:focus-visible]:outline-2 [&_input:focus-visible]:outline-offset-2 [&_input:focus-visible]:outline-[var(--zoop-ink)] [&_summary:focus-visible]:outline-2 [&_summary:focus-visible]:outline-offset-2 [&_summary:focus-visible]:outline-[var(--zoop-ink)] max-md:[&_table]:block max-md:[&_table]:overflow-auto max-md:[&_section]:min-w-0 max-md:[&_section]:wrap-anywhere';

function Status<T>({
  resource,
  label,
}: {
  resource: Resource<T>;
  label: string;
}) {
  return resource.loading ? (
    <p role="status">{label} 불러오는 중…</p>
  ) : resource.error ? (
    <div role="alert">
      <p>
        {label} 조회 실패 · {resource.error}
      </p>
      <button onClick={resource.retry}>{label} 다시 조회</button>
    </div>
  ) : null;
}
function Basis({ metadata }: { metadata: Meta | undefined }) {
  return metadata ? (
    <p className="wrap-anywhere">
      출처 {metadata.source} · 공개 자료 기준 {metadata.asOf} · 버전{' '}
      {metadata.graphVersion ?? '미제공'}
      {metadata.partial ? ' · 일부 자료 미제공' : ''}
    </p>
  ) : null;
}
export default function CompanyWorkspace() {
  const { id = '' } = useParams();
  const { params, updateQuery } = useRouteQuery();
  const location = useLocation();
  const navigate = useNavigate();
  const auth = useAuth();
  const revision = useAuthStore((s) => s.sessionRevision);
  const owner = auth.isAuthenticated ? `${auth.member?.id}:${revision}` : '';
  const period = (periods.find((p) => p.value === params.get('period'))
    ?.value ?? '1m') as ChartPeriod;
  const asOf = params.get('asOf'),
    version = params.get('graphVersion'),
    eventId = params.get('event');
  const invalid = !!asOf && !exactTime(asOf);
  const snapshot = { asOf, graphVersion: version };
  const ready = !!asOf && !invalid;
  const range = ready ? timeRange(asOf!, period) : {};
  const company = useCompanyResource<Company>(
    invalid ? null : companyUrl(id, '', snapshot),
    owner,
  );
  const quote = useCompanyResource<Quote>(companyUrl(id, '/quote'));
  const prices = useCompanyResource<Prices>(
    invalid ? null : companyUrl(id, '/prices', { period, ...range }),
  );
  const latestPoint =
    prices.data?.status === 'available'
      ? prices.data.points.at(-1)?.time
      : null;
  useEffect(() => {
    const latest = exactTime(latestPoint)
      ? latestPoint
      : company.data?.metadata.asOf;
    if (!asOf && company.data && !prices.loading && latest && exactTime(latest))
      updateQuery(
        {
          asOf: latest,
          graphVersion: company.data?.metadata.graphVersion ?? null,
          period,
        },
        { replace: true },
      );
    if (asOf && !version && company.data?.metadata.graphVersion)
      updateQuery(
        { graphVersion: company.data.metadata.graphVersion },
        { replace: true },
      );
    // URL is the persisted view state; updateQuery intentionally writes only missing defaults.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    asOf,
    version,
    latestPoint,
    company.data?.metadata.asOf,
    company.data?.metadata.graphVersion,
    prices.loading,
    period,
  ]);
  const depth = params.get('depth') === '2' ? 2 : 1;
  const eventsQuery = new URLSearchParams({
    ...range,
    companyId: id,
    depth: String(depth),
    ...(asOf ? { asOf } : {}),
    ...(version ? { graphVersion: version } : {}),
  });
  const events = useCompanyResource<Events>(
    ready ? `/api/v1/events?${eventsQuery}` : null,
    '',
    true,
  );
  const graph = useCompanyResource<GraphResponse>(
    ready ? companyUrl(id, '/graph', { ...snapshot, depth }) : null,
  );
  const event = useCompanyResource<EventDetail>(
    ready && eventId
      ? `/api/v1/events/${encodeURIComponent(eventId)}?${new URLSearchParams(Object.entries(snapshot).filter((entry): entry is [string, string] => entry[1] !== null))}`
      : null,
  );
  const impact = useCompanyResource<Impact>(
    ready && eventId
      ? companyUrl(
          id,
          `/issues/${encodeURIComponent(eventId)}/impact`,
          snapshot,
        )
      : null,
  );
  const portfolio = useCompanyResource<Portfolio>(
    auth.isAuthenticated ? '/api/v1/portfolio' : null,
    owner,
  );
  const financials = useCompanyResource<Financials>(
    ready ? companyUrl(id, '/financials', snapshot) : null,
  );
  const tab = ['events', 'documents', 'info'].includes(params.get('tab') ?? '')
    ? params.get('tab')!
    : 'events';
  const groups = new Map<string, Events['items']>();
  for (const item of events.data?.items ?? []) {
    const key = bucketKey(item, period);
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  const holding = portfolio.data?.connected
    ? portfolio.data.holdings.find((h) => h.companyId === id)
    : null;
  const selectedBucket = params.get('bucket');
  const visible = selectedBucket ? (groups.get(selectedBucket) ?? []) : [];
  const mapQuery = new URLSearchParams({
    mode: 'all',
    select: `node:${eventId ?? id}`,
    companyId: id,
    period,
    tab,
    depth: String(depth),
    returnTo: `${location.pathname}${location.search}`,
  });
  if (asOf) mapQuery.set('asOf', asOf);
  if (version) mapQuery.set('graphVersion', version);
  if (eventId) mapQuery.set('event', eventId);
  const highlighted = graph.data ? impactEdges(graph.data, impact.data) : [];
  function selectEvent(item: Events['items'][number], targetTab?: string) {
    updateQuery({
      event: item.id,
      bucket: bucketKey(item, period),
      document: null,
      evidence: null,
      ...(targetTab
        ? { tab: targetTab, docScope: 'event', document: null, evidence: null }
        : {}),
      ...(item.timePrecision === 'datetime' && exactTime(item.eventTime)
        ? { asOf: item.eventTime! }
        : {}),
    });
  }
  if (invalid)
    return (
      <div className={workspaceClasses} role="alert">
        기준 시점은 오프셋이 포함된 정확한 시각이어야 해요.
        <button
          onClick={() =>
            updateQuery({
              asOf: null,
              graphVersion: null,
              event: null,
              bucket: null,
            })
          }
        >
          최신 제공 시점으로 조회
        </button>
      </div>
    );
  return (
    <div className={workspaceClasses} data-screen-id="D-COM-01 D-COM-01b">
      <CompanyCatalog
        graph={graph}
        currentCompany={company.data}
        portfolio={portfolio}
      />
      <main className="min-w-0 bg-white p-6 max-md:p-4">
        <section aria-label="기업 개요">
          <Status resource={company} label="기업 정보" />
          {company.data && (
            <>
              <h1>{company.data.name}</h1>
              <p>
                {company.data.ticker ?? '코드 미제공'} ·{' '}
                {company.data.market ?? '시장 미제공'} ·{' '}
                {company.data.sector ?? '업종 미제공'}
              </p>
              <p>
                {company.data.summary?.summary ??
                  company.data.summary?.text ??
                  company.data.summary?.reason ??
                  '기업 요약 미제공'}
              </p>
              <Basis metadata={company.data.metadata} />
            </>
          )}
        </section>
        <section aria-label="최신 시세">
          <h2>최신 제공 시세</h2>
          <Status resource={quote} label="시세" />
          {quote.data?.status === 'unavailable' && (
            <p>시세 미제공 · {quote.data.reason}</p>
          )}
          {quote.data?.status === 'available' && (
            <>
              <strong className="text-2xl">
                {number(quote.data.quote.price)} {quote.data.quote.currency}
              </strong>
              <span>
                {' '}
                · 전일 대비 {number(quote.data.quote.change)} (
                {quote.data.quote.changeRate === null
                  ? '미제공'
                  : `${number(quote.data.quote.changeRate * 100)}%`}
                )
              </span>
              <p>
                공급자 관측 {quote.data.quote.asOf ?? '시각 미제공'} ·{' '}
                {quote.data.source.name} ·{' '}
                {quote.data.source.delayNote ?? '지연 정보 미제공'}
              </p>
              <dl className="my-3 flex flex-wrap gap-x-3 gap-y-2 text-xs [&_dt]:text-[var(--zoop-faint)] [&_dd]:font-semibold max-md:grid max-md:grid-cols-[auto_minmax(0,1fr)]">
                <dt>거래량</dt>
                <dd>{number(quote.data.quote.volume)}</dd>
                <dt>당일 저가~고가</dt>
                <dd>
                  {number(quote.data.quote.dayLow)} ~{' '}
                  {number(quote.data.quote.dayHigh)}
                </dd>
                <dt>52주 저가~고가</dt>
                <dd>
                  {number(quote.data.quote.fiftyTwoWeekLow)} ~{' '}
                  {number(quote.data.quote.fiftyTwoWeekHigh)}
                </dd>
              </dl>
            </>
          )}
        </section>
        <section aria-label="가상 계좌 보유">
          <h2>가상 계좌 보유 · 프로젝트용 모의 데이터</h2>
          {!auth.isAuthenticated ? (
            <p>
              {auth.checking
                ? '로그인 상태 확인 중…'
                : '로그인하고 가상 계좌를 연결하면 모의 보유 정보를 볼 수 있어요.'}
            </p>
          ) : (
            <>
              <Status resource={portfolio} label="모의 보유" />
              {portfolio.data && !portfolio.data.connected && (
                <p>연결된 가상 계좌가 없어요.</p>
              )}
              {portfolio.data?.connected && !holding && (
                <p>이 기업의 모의 보유 종목이 없어요.</p>
              )}
              {holding && (
                <>
                  <dl className="my-3 flex flex-wrap gap-x-3 gap-y-2 text-xs [&_dt]:text-[var(--zoop-faint)] [&_dd]:font-semibold max-md:grid max-md:grid-cols-[auto_minmax(0,1fr)]">
                    <dt>보유 수량</dt>
                    <dd>{number(holding.quantity)}주</dd>
                    <dt>평균 매입가</dt>
                    <dd>
                      {number(holding.avgPrice)}{' '}
                      {holding.avgPriceCurrency ?? '통화 미상'}
                    </dd>
                    <dt>평가 금액</dt>
                    <dd>
                      {number(holding.marketValue)}{' '}
                      {holding.quote.status === 'available'
                        ? holding.quote.currency
                        : '시세 미제공'}
                    </dd>
                    <dt>자산 비중</dt>
                    <dd>
                      {holding.weight === null
                        ? '계산 불가'
                        : `${number(holding.weight * 100)}%`}
                    </dd>
                  </dl>
                  <p>
                    모의 수량 기준 {portfolio.data?.mockAsOf ?? '미제공'} · 평가
                    기준 {portfolio.data?.valuation?.calculatedAt ?? '미제공'}
                  </p>
                  {portfolio.data?.valuation?.weightUnavailableReason && (
                    <p>{portfolio.data.valuation.weightUnavailableReason}</p>
                  )}
                </>
              )}
              <Basis metadata={portfolio.data?.metadata} />
            </>
          )}
        </section>
        <nav aria-label="기업 상세 보기">
          {[
            ['events', '사건'],
            ['documents', '문서'],
            ['info', '기업 정보'],
          ].map(([value, label]) => (
            <button
              key={value}
              aria-pressed={tab === value}
              onClick={() => updateQuery({ tab: value })}
            >
              {label}
            </button>
          ))}
        </nav>
        <section aria-label="시세 차트" data-screen-id="D-COM-06">
          <h2>시세 차트·기준 시점</h2>
          <nav aria-label="차트 기간">
            {periods.map((p) => (
              <button
                key={p.value}
                aria-pressed={period === p.value}
                onClick={() => updateQuery({ period: p.value, bucket: null })}
              >
                {p.label}
              </button>
            ))}
            <button
              onClick={() =>
                updateQuery({
                  asOf: null,
                  graphVersion: null,
                  event: null,
                  bucket: null,
                  document: null,
                  evidence: null,
                  docScope: null,
                })
              }
            >
              최신 시점
            </button>
          </nav>
          <p>
            기준 {asOf ?? '최신 제공 시점 확인 중'} ·{' '}
            {periods.find((p) => p.value === period)?.interval} 해상도
          </p>
          <Status resource={prices} label="차트" />
          {prices.data?.status === 'unavailable' && (
            <p>차트 미제공 · {prices.data.reason}</p>
          )}
          {prices.data?.status === 'available' &&
            (prices.data.interval !==
            periods.find((p) => p.value === period)?.interval ? (
              <p role="alert">
                요청한 기간과 공급된 봉 해상도가 달라 차트를 표시하지 않았어요.
              </p>
            ) : (
              <>
                <PriceChart
                  points={prices.data.points}
                  asOf={asOf}
                  period={period}
                  groups={groups}
                  selectedBucket={selectedBucket}
                  selectedEvent={event.data}
                  onBucket={(bucket) =>
                    updateQuery({
                      tab: 'events',
                      bucket,
                      event: null,
                      document: null,
                      evidence: null,
                    })
                  }
                  onSelect={(time) => updateQuery(selectTime(time))}
                />
                <p>
                  {prices.data.source.name} · {prices.data.currency} ·{' '}
                  {prices.data.source.delayNote ?? '지연 정보 미제공'}
                </p>
                <details>
                  <summary>차트 시점 선택·가격 표</summary>
                  <table>
                    <thead>
                      <tr>
                        <th>시각</th>
                        <th>종가</th>
                        <th>선택</th>
                      </tr>
                    </thead>
                    <tbody>
                      {prices.data.points.map((point) => (
                        <tr key={point.time}>
                          <td>{point.time}</td>
                          <td>{number(point.close)}</td>
                          <td>
                            <button
                              disabled={!exactTime(point.time)}
                              onClick={() =>
                                updateQuery({
                                  ...selectTime(point.time),
                                })
                              }
                            >
                              이 시점 선택
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              </>
            ))}
          <p className="border-l-2 border-[var(--zoop-faint)] bg-[var(--zoop-soft)] p-2">
            차트와 사건의 시점이 겹쳐도 인과관계를 뜻하지 않아요.
          </p>
        </section>
        {tab === 'events' && (
          <section aria-label="사건 타임라인" data-screen-id="D-COM-05">
            <h2>사건 타임라인</h2>
            {events.error && [401, 403].includes(events.errorStatus ?? 0) ? (
              <p role="alert">이 시점의 사건을 조회할 권한이 없어요.</p>
            ) : (
              <Status resource={events} label="타임라인" />
            )}
            {!ready && (
              <p role="status">타임라인의 기준 시점을 확인하고 있어요.</p>
            )}
            {events.data && (
              <>
                <Basis metadata={events.data.metadata} />
                {events.data.metadata.partial && (
                  <p role="status">
                    일부 사건만 조회됐어요.{' '}
                    <button onClick={events.retry}>타임라인 다시 조회</button>
                  </p>
                )}
                {(events.data.metadata.failures ?? []).map((failure, index) => (
                  <p key={index}>{failure.message}</p>
                ))}
                <p>
                  제공 사건 {events.data.items.length}건 · 시점 미상 제외{' '}
                  {events.data.metadata.excludedUnknownTime ?? 0}건
                </p>
                {!groups.size && <p>해당 기간에 공개·유효한 사건이 없어요.</p>}
                <ul className="flex flex-wrap gap-2">
                  {[...groups].map(([key, items]) => (
                    <li key={key}>
                      <button
                        aria-pressed={selectedBucket === key}
                        onClick={() =>
                          updateQuery({
                            bucket: key,
                            event: null,
                            document: null,
                            evidence: null,
                          })
                        }
                      >
                        {key} · 사건 {items.length}건
                      </button>
                    </li>
                  ))}
                </ul>
                {visible.map((item) => (
                  <article key={item.id}>
                    <button
                      aria-pressed={eventId === item.id}
                      onClick={() => selectEvent(item)}
                    >
                      {item.title}
                    </button>
                    <p>
                      {item.eventTime ?? '시점 미상'} · 문서 {item.articleCount}
                      건 · {item.relationTypes.join(', ') || '직접 관계 미확인'}
                    </p>
                    <button onClick={() => selectEvent(item, 'documents')}>
                      근거 문서 {item.articleCount}건 보기
                    </button>
                    {item.timePrecision !== 'datetime' && (
                      <p>
                        정확한 사건 시각이 없어 기준 시점을 임의 변경하지
                        않아요.
                      </p>
                    )}
                  </article>
                ))}
                {events.data.unknownTimeItems.length > 0 && (
                  <details>
                    <summary>
                      시점 미상 사건 {events.data.unknownTimeItems.length}건
                    </summary>
                    {events.data.unknownTimeItems.map((item) => (
                      <p key={item.id}>
                        <button onClick={() => selectEvent(item)}>
                          {item.title}
                        </button>{' '}
                        · 보도 시각 {item.reportedAt ?? '미상'} (사건 시각 아님)
                      </p>
                    ))}
                  </details>
                )}
              </>
            )}
            {eventId && (
              <>
                <Status resource={event} label="선택 사건" />
                {event.data && (
                  <article>
                    <h3>{event.data.title}</h3>
                    <p>
                      근거 인용 {event.data.evidenceIds.length}건 · 문서{' '}
                      {
                        new Set(
                          event.data.articles.map((article) => article.id),
                        ).size
                      }
                      건
                    </p>
                    {event.data.evidenceIds.map((evidenceId) => (
                      <button
                        key={evidenceId}
                        onClick={() =>
                          updateQuery({
                            tab: 'documents',
                            evidence: evidenceId,
                            document: null,
                            docScope: 'event',
                          })
                        }
                      >
                        근거 {evidenceId} 보기
                      </button>
                    ))}
                    <Link to={`/?${mapQuery}`}>
                      이 사건의 관계를 지도에서 보기
                    </Link>
                  </article>
                )}
              </>
            )}
          </section>
        )}
        {tab === 'documents' && <CompanyDocumentPanel />}
        {tab === 'info' && <CompanyInfoTab resource={company} />}
        <section aria-label="핵심 재무">
          <h2>핵심 재무</h2>
          <Status resource={financials} label="재무" />
          {financials.data && (
            <>
              <Basis metadata={financials.data.metadata} />
              {financials.data.status !== 'available' ? (
                <p>
                  {financials.data.status === 'failed'
                    ? '재무 조회 실패'
                    : '재무 미제공'}{' '}
                  · {financials.data.reason}
                  <button onClick={financials.retry}>재무 다시 조회</button>
                </p>
              ) : financials.data.items.length ? (
                <dl>
                  {financials.data.items.map((f, i) => (
                    <div key={`${f.name}:${i}`}>
                      <dt>
                        {f.name} ({f.period})
                      </dt>
                      <dd>
                        {number(f.value)} {f.unit} ·{' '}
                        {f.accountingBasis ?? '회계 기준 미제공'} · {f.source} ·{' '}
                        {f.asOf}
                      </dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p>제공된 재무 항목이 없어요.</p>
              )}
            </>
          )}
        </section>
      </main>
      <aside
        className="min-w-0 border-l border-[var(--zoop-line)] p-4 [&_li]:text-xs [&_li]:wrap-anywhere [&_svg]:h-auto [&_svg]:w-full [&_svg]:bg-[var(--zoop-line)] max-[1000px]:col-start-2 max-[1000px]:border-l-0 max-[1000px]:border-t max-md:w-full"
        aria-label="시점 기반 관계 그래프"
        data-screen-id="D-COM-04"
      >
        <h2>관계 그래프</h2>
        <Link className={ui.button} to={`/?${mapQuery}`}>
          지도에서 보기
        </Link>
        <nav aria-label="관계 깊이">
          {[1, 2].map((d) => (
            <button
              key={d}
              aria-pressed={depth === d}
              className={ui.button}
              onClick={() => updateQuery({ depth: String(d), bucket: null })}
            >
              {d}단계
            </button>
          ))}
        </nav>
        {graph.error && [401, 403].includes(graph.errorStatus ?? 0) ? (
          <p role="alert">이 시점의 기업 관계를 조회할 권한이 없어요.</p>
        ) : (
          <Status resource={graph} label="관계 그래프" />
        )}
        {!ready && (
          <p role="status">관계 그래프의 기준 시점을 확인하고 있어요.</p>
        )}
        {graph.data && (
          <>
            <Basis metadata={graph.data.metadata} />
            {graph.data.metadata.partial && (
              <button type="button" className={ui.button} onClick={graph.retry}>
                관계 그래프 다시 조회
              </button>
            )}
            {(graph.data.metadata.failures ?? []).map((failure, i) => (
              <p key={`${failure.section}:${i}`}>{failure.message}</p>
            ))}
            <CompanyGraphPreview
              key={`${id}:${asOf}:${version}:${depth}`}
              selectedId={eventId ?? id}
              data={graph.data}
              highlighted={highlighted}
              onSelect={(node, kind) => {
                if (kind === 'issue')
                  updateQuery({
                    event: node,
                    document: null,
                    evidence: null,
                    bucket: events.data?.items.find((item) => item.id === node)
                      ? bucketKey(
                          events.data.items.find((item) => item.id === node)!,
                          period,
                        )
                      : null,
                  });
                else {
                  const next = new URLSearchParams(params);
                  next.delete('event');
                  next.delete('bucket');
                  next.delete('document');
                  next.delete('evidence');
                  next.delete('docScope');
                  navigate(`/companies/${encodeURIComponent(node)}?${next}`);
                }
              }}
            />
          </>
        )}
        {eventId && (
          <>
            <Status resource={impact} label="영향 경로" />
            {impact.data && (
              <>
                <h3>공개 자료에 확인된 영향 경로</h3>
                {!impact.data.steps.length && <p>확인된 영향 경로가 없어요.</p>}
                <ol>
                  {impact.data.steps.map((step, i) => (
                    <li key={`${step.id}:${i}`}>
                      {step.id} · {step.reason} · 근거 {step.evidenceIds.length}
                      건
                    </li>
                  ))}
                </ol>
                {!highlighted.length && (
                  <p>현재 그래프와 일치하는 확인된 경로만 강조합니다.</p>
                )}
              </>
            )}
          </>
        )}
      </aside>
    </div>
  );
}
