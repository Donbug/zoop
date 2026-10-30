import CompanyInfoTab from './CompanyInfoTab';
import PriceChart from './PriceChart';
import { formatKst, formatMoney } from '@/util/format';
import { formatTimelineTime } from '@/util/event-time';
import { ChangeRate } from '@/components/stocks/StockQuote';
import BoltIcon from './BoltIcon';
import { useEffect, useEffectEvent, useRef, useState } from 'react';
import {
  Link,
  useLocation,
  useNavigate,
  useNavigationType,
  useParams,
} from 'react-router-dom';
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
  legacyTimeRange,
  bucketKey,
  impactEdges,
  number,
  requestTime,
  versionOnlyAddress,
} from './detail-model';

// D-COM-01 B1: 백엔드 financials 컨트롤러가 생기면 계약을 확인하고 다시 켠다.
const COMPANY_FINANCIALS_ENABLED = false;

const workspaceClasses =
  'company-workspace grid grid-cols-[200px_minmax(0,1fr)_280px] gap-3 m-0 overflow-visible text-zoop-ink max-[1000px]:grid-cols-[160px_minmax(0,1fr)] max-md:flex max-md:flex-col [&_section]:border-b [&_section]:border-zoop-line [&_section]:py-4 [&_h1]:text-display [&_h1]:font-bold [&_h1]:tracking-[-0.035em] [&_h2]:mb-3 [&_h2]:text-body [&_h2]:font-bold [&_h2]:tracking-[-0.025em] [&_h3]:font-semibold [&_p]:text-caption [&_p]:text-zoop-muted [&_p]:leading-[1.7] [&_button]:cursor-pointer [&_button]:rounded-full [&_button]:border [&_button]:border-zoop-line [&_button]:bg-white [&_button]:min-h-[36px] [&_button]:px-4 [&_button]:py-2 [&_button]:text-caption! [&_button[aria-pressed=true]]:bg-zoop-ink [&_button[aria-pressed=true]]:text-white [&_button:disabled]:opacity-50 [&_button:disabled]:cursor-default [&_a]:cursor-pointer [&_a]:px-[9px] [&_a]:py-1.5 [&_a]:text-caption [&_button:focus-visible]:outline-2 [&_button:focus-visible]:outline-offset-2 [&_button:focus-visible]:outline-zoop-ink [&_a:focus-visible]:outline-2 [&_a:focus-visible]:outline-offset-2 [&_a:focus-visible]:outline-zoop-ink [&_nav]:my-3 [&_nav]:flex [&_nav]:flex-wrap [&_nav]:gap-1.5 [&_article]:border-b [&_article]:border-zoop-line [&_article]:py-3 [&_table]:w-full [&_table]:text-caption [&_table]:wrap-anywhere [&_[role=alert]]:text-zoop-alert [&_details]:my-3 [&_input]:max-w-full [&_input]:rounded-xl [&_input]:border [&_input]:border-zoop-line [&_input]:bg-white [&_input]:px-3 [&_input]:py-2 [&_input]:min-h-[38px] [&_input:focus-visible]:outline-2 [&_input:focus-visible]:outline-offset-2 [&_input:focus-visible]:outline-zoop-ink [&_summary:focus-visible]:outline-2 [&_summary:focus-visible]:outline-offset-2 [&_summary:focus-visible]:outline-zoop-ink max-md:[&_table]:block max-md:[&_table]:overflow-auto max-md:[&_section]:min-w-0 max-md:[&_section]:wrap-anywhere';

function Status<T>({
  resource,
  label,
}: {
  resource: Resource<T>;
  label: string;
}) {
  if (resource.loading) return <p role="status">{label} 불러오는 중…</p>;
  if (!resource.error) return null;
  // 계약의 오류 코드별 안내. 다시 보내도 같은 결과인 오류(없음·버전 없음·조건 오류)에는 다시 시도를 두지 않는다.
  const fixed = fixedFailure(
    resource.errorStatus,
    resource.errorCode,
    resource.errorRetryable,
  );
  return (
    <div role="alert">
      <p>
        {label} 조회 실패 · {resource.error}
      </p>
      {fixed ? (
        <p>{fixed}</p>
      ) : (
        <button onClick={resource.retry}>{label} 다시 조회</button>
      )}
    </div>
  );
}
function fixedFailure(
  status: number | null,
  code: string | null,
  retryable: boolean | null,
) {
  if (
    status === 401 ||
    status === 403 ||
    code === 'ACCESS_DENIED' ||
    code === 'MEMBER_REQUIRED'
  )
    return '이 자료를 조회할 권한이 없어요.';
  if (status === 404 || code === 'RESOURCE_NOT_FOUND')
    return '해당 자료가 없어요.';
  if (status === 409 || code === 'VERSION_UNAVAILABLE')
    return '이 기준 시점의 공개 자료가 없어요. [최신 시점]으로 돌아가 확인해 주세요.';
  if (status === 422 || code === 'INVALID_REQUEST')
    return '조회 조건을 확인해 주세요.';
  // F05: 공급자 인증·형식 문제처럼 다시 보내도 같은 장애는 다시 시도를 두지 않는다.
  if (retryable === false)
    return '자료 공급원의 설정이나 응답 형식 문제로 지금은 확인할 수 없어요.';
  return null;
}
// D-COM-01 / F6: display KST while retaining the API timestamp for machines.
function ReferenceTime({
  value,
  missing = '미제공',
}: {
  value: string | null | undefined;
  missing?: string;
}) {
  return value ? <time dateTime={value}>{formatKst(value)}</time> : missing;
}

function Basis({ metadata }: { metadata: Meta | undefined }) {
  return metadata ? (
    <p className="wrap-anywhere">
      출처 {metadata.source} · 공개 자료 기준{' '}
      <ReferenceTime value={metadata.asOf} /> · 버전{' '}
      {metadata.graphVersion ?? '미제공'}
      {metadata.partial ? ' · 일부 자료 미제공' : ''}
    </p>
  ) : null;
}
/** A02: 사건과 이 기업 사이의 직접 승인 관계. 빈 배열은 직접 관계가 확인되지 않은 사건(2-hop 등)이다. */
const RELATION_LABEL: Record<string, string> = {
  INVOLVES: '직접 관련',
  STRUCTURALLY_RELATED_TO: '구조적 관련',
};
const relationLabel = (types: string[]) =>
  types.map((type) => RELATION_LABEL[type] ?? type).join(' · ');

/** 사건·문서·기업 정보 탭(밑줄형) */
const TAB =
  'flex-1 rounded-none! border-0! border-b-2! border-transparent! bg-transparent! py-2.5! text-body! text-zoop-muted aria-pressed:border-zoop-ink! aria-pressed:bg-transparent! aria-pressed:font-semibold aria-pressed:text-zoop-ink!';

/** 차트 기간의 처음 시세 대비 변화(D-COM-05). 상승은 빨강, 하락은 파랑으로 보인다. */
function PriceChange({
  label,
  first,
  last,
  currency,
}: {
  label: string;
  first: number;
  last: number;
  currency: string;
}) {
  const diff = last - first;
  const rate = first ? diff / first : 0;
  const tone =
    diff > 0 ? 'text-zoop-up' : diff < 0 ? 'text-zoop-down' : 'text-zoop-muted';
  return (
    <p>
      {label} · 처음 시세 대비{' '}
      <span className={`font-semibold tabular-nums ${tone}`}>
        {diff > 0 ? '▲ +' : diff < 0 ? '▼ ' : ''}
        {formatMoney(diff, currency)} ({(rate * 100).toFixed(2)}%)
      </span>
    </p>
  );
}

/** 타임라인에 한 번에 보이는 시간 버킷 수 */
const BUCKET_PAGE = 10;
const bucketElementId = (key: string) =>
  `bucket-${key.replace(/[^\w-]/g, '_')}`;

function ClockIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      className="size-3.5 shrink-0"
    >
      <circle cx="8" cy="8" r="6" />
      <path d="M8 4.8V8l2.2 1.4" />
    </svg>
  );
}
/** 관계 그래프 영역은 svg를 그래프 크기로 늘리므로 아이콘의 크기·배경을 되돌린다. */
function HomeIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-3.5! w-3.5! shrink-0 bg-transparent!"
    >
      <path d="M2.5 7.5 8 3l5.5 4.5M4 6.5V13h3V9.5h2V13h3V6.5" />
    </svg>
  );
}

/** 사건 시점 지도의 기준 시각. 현재 기준 시점보다 늦을 수 없다. */
function eventReferenceTime(
  event: { eventTime: string | null; timePrecision: string } | null | undefined,
  current: string | null,
) {
  if (!event?.eventTime) return current;
  const time =
    event.timePrecision === 'datetime' && exactTime(event.eventTime)
      ? event.eventTime
      : event.timePrecision === 'day'
        ? `${event.eventTime.slice(0, 10)}T23:59:59+09:00`
        : null;
  if (!time) return current;
  return current && Date.parse(time) > Date.parse(current) ? current : time;
}

/** 같은 순간을 다르게 적은 RFC 3339 시각(Z·오프셋·소수초)도 같은 시각으로 본다. */
const sameInstant = (a: string | null, b: string | null) =>
  !!a && !!b && Date.parse(a) === Date.parse(b);

export default function CompanyWorkspace() {
  const { id = '' } = useParams();
  const { params, updateQuery } = useRouteQuery();
  const location = useLocation();
  const navigationType = useNavigationType();
  const navigate = useNavigate();
  const auth = useAuth();
  const revision = useAuthStore((s) => s.sessionRevision);
  const owner = auth.isAuthenticated ? `${auth.member?.id}:${revision}` : '';
  const period = (periods.find((p) => p.value === params.get('period'))
    ?.value ?? '1m') as ChartPeriod;
  const asOf = params.get('asOf'),
    version = params.get('graphVersion'),
    eventId = params.get('event');
  // D-COM-06: 타임라인 사건의 [이 당시 관계그래프 보기]로 고른 시각. 오른쪽 관계 그래프에만 쓰고
  // 차트·타임라인의 기준 시점(asOf)은 그대로 둔다. 정확한 시각이 아니거나 기준 시점보다 이르지 않으면 무시한다.
  const requestedGraphAsOf = params.get('graphAsOf');
  const invalid = !!asOf && !exactTime(asOf);
  // 그래프 밖을 눌러 끝낸 시점은 주소에서 지워지기 전에도 바로 현재 시점 그래프로 보인다.
  const [closedGraphTime, setClosedGraphTime] = useState<{
    asOf: string;
    entryKey: string;
  } | null>(null);
  const closedGraphAsOf = closedGraphTime?.asOf ?? null;
  // D-COM-06: the close is complete once the URL drops that time. Clear it
  // before rendering so Back/Forward can restore the same timestamp later.
  if (
    closedGraphTime &&
    (requestedGraphAsOf !== closedGraphTime.asOf ||
      (navigationType === 'POP' && location.key !== closedGraphTime.entryKey))
  )
    setClosedGraphTime(null);
  else if (closedGraphTime && location.key !== closedGraphTime.entryKey)
    setClosedGraphTime({ ...closedGraphTime, entryKey: location.key });
  const graphAsOf =
    requestedGraphAsOf &&
    requestedGraphAsOf !== closedGraphAsOf &&
    exactTime(requestedGraphAsOf) &&
    asOf &&
    !invalid &&
    Date.parse(requestedGraphAsOf) < Date.parse(asOf)
      ? requestedGraphAsOf
      : null;
  const snapshot = { asOf, graphVersion: version };
  // 사건 시점 그래프는 그 시점의 공개 버전을 서버가 고르게 한다(버전을 보내지 않는다).
  const graphSnapshot = graphAsOf
    ? { asOf: graphAsOf, graphVersion: null }
    : snapshot;
  const ready = !!asOf && !invalid;
  const versionOnly = versionOnlyAddress(asOf, version);
  const range = ready ? timeRange(asOf!, period) : {};
  const company = useCompanyResource<Company>(
    invalid ? null : companyUrl(id, '', snapshot),
    owner,
  );
  // D-COM-04·06 (#358): 버전만 있는 주소는 서버가 그 버전이 처음 공개된 시각을 metadata.asOf로 준다.
  // 그 버전으로 답했고 정확한 시각이면 주소의 asOf로 채운다(처음 열 때와 같은 방식). 채운 주소를 기억해
  // "처음 공개된 시점으로 보는 중"을 알리고, 그 주소가 409·422면 예전처럼 열 수 없다고 안내한다.
  const [versionPin, setVersionPin] = useState<{
    version: string;
    asOf: string;
  } | null>(null);
  const versionStart =
    versionOnly &&
    company.data?.metadata.graphVersion === version &&
    exactTime(company.data.metadata.asOf)
      ? requestTime(company.data.metadata.asOf)
      : null;
  if (
    versionStart &&
    (versionPin?.version !== version || versionPin.asOf !== versionStart)
  )
    setVersionPin({ version: version!, asOf: versionStart });
  const pinnedFromVersion =
    !!versionPin && versionPin.version === version && versionPin.asOf === asOf;
  const versionStartFailed =
    pinnedFromVersion &&
    (company.errorStatus === 409 || company.errorStatus === 422);
  const quote = useCompanyResource<Quote>(companyUrl(id, '/quote'));
  // D-COM-06: 사건 시점 그래프는 그래프를 쓰는 동안만 유지한다. 그래프 영역 밖(다른 사건·탭·빈 곳 등)을
  // 누르면 현재 기준 시점 그래프로 돌아간다. 키보드로 누른 것도 click으로 들어온다.
  // 누른 곳의 동작(다른 사건 고르기 등)도 주소를 바꾸므로, 주소의 graphAsOf는 그 변경이 반영된 뒤에 지운다.
  // 먼저 지우면 아직 반영되지 않은 그 변경을 예전 주소로 덮어쓴다.
  const graphPanel = useRef<HTMLElement>(null);
  const paramsKey = params.toString();
  const clearClosedGraphTime = useEffectEvent(() => {
    if (closedGraphAsOf && params.get('graphAsOf') === closedGraphAsOf)
      updateQuery({ graphAsOf: null }, { replace: true });
  });
  useEffect(() => {
    clearClosedGraphTime();
  }, [paramsKey]);
  const clearIfUnchanged = useEffectEvent((clickedAt: string) => {
    // 누른 곳이 주소를 바꾸지 않았으면(빈 곳 등) 여기서 지운다.
    if (params.toString() === clickedAt) clearClosedGraphTime();
  });
  // 지운 뒤 그래프 시점이 풀려 듣기를 해제해도 예약한 정리는 남아야 해서 타이머는 화면을 떠날 때만 취소한다.
  const closeTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(closeTimer.current), []);
  const graphTimeOpen = graphAsOf;
  useEffect(() => {
    if (!graphTimeOpen) return;
    const timeToClose = graphTimeOpen;
    const clickedAt = paramsKey;
    function outside(event: MouseEvent) {
      const target = event.target;
      if (
        !(target instanceof Element) ||
        graphPanel.current?.contains(target) ||
        target.closest('[data-graph-time-trigger]')
      )
        return;
      setClosedGraphTime({ asOf: timeToClose, entryKey: location.key });
      window.clearTimeout(closeTimer.current);
      closeTimer.current = window.setTimeout(
        () => clearIfUnchanged(clickedAt),
        300,
      );
    }
    document.addEventListener('click', outside, true);
    return () => document.removeEventListener('click', outside, true);
  }, [graphTimeOpen, paramsKey, location.key]);
  // 버전 단독 주소는 그 버전의 차트를 열 수 없다고 안내하므로 가격 조회도 시작하지 않는다.
  const prices = useCompanyResource<Prices>(
    invalid || versionOnly
      ? null
      : companyUrl(id, '/prices', { period, ...range }),
  );
  useEffect(() => {
    // FS040: 처음 열 때의 기준 시점은 기업 응답의 공개 기준 시점과 그 버전이다. 가격 봉 시각은
    // 거래가 없는 날(주말·휴장)에 오래된 시점을 가리켜 이후 공개 자료를 빼거나 409를 만든다.
    // 공개 그래프 버전이 없으면(스냅샷 미게시) 고정하지 않는다. 고정하면 409가 된다.
    // 주소에 graphVersion만 있으면 그 버전이 처음 공개된 시각(versionStart)을 asOf로 채운다.
    if (versionStart) {
      updateQuery({ asOf: versionStart, period }, { replace: true });
      return;
    }
    const latest = company.data?.metadata.asOf;
    const currentVersion = company.data?.metadata.graphVersion ?? null;
    if (
      !asOf &&
      !version &&
      company.data &&
      currentVersion &&
      latest &&
      exactTime(latest)
    )
      updateQuery(
        { asOf: requestTime(latest), graphVersion: currentVersion, period },
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
    company.data?.metadata.asOf,
    company.data?.metadata.graphVersion,
    period,
    versionStart,
  ]);
  const depth = params.get('depth') === '2' ? 2 : 1;
  const eventsQuery = new URLSearchParams({
    ...(ready
      ? period === '1d' &&
        prices.data?.status === 'available' &&
        prices.data.range
        ? { from: prices.data.range.from, to: prices.data.range.to }
        : legacyTimeRange(asOf!, period)
      : {}),
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
    ready ? companyUrl(id, '/graph', { ...graphSnapshot, depth }) : null,
  );
  const event = useCompanyResource<EventDetail>(
    ready && eventId
      ? `/api/v1/events/${encodeURIComponent(eventId)}?${new URLSearchParams(Object.entries(snapshot).filter((entry): entry is [string, string] => entry[1] !== null))}`
      : null,
  );
  // 영향 경로는 그래프 시점이 지금 고른 사건의 시각일 때만 그 시각으로 조회한다.
  // 다른 사건을 고르는 순간(그래프 시점이 풀리기 전)에도 그 사건을 남의 시각으로 조회하지 않는다.
  const selectedEvent =
    events.data?.items.find((item) => item.id === eventId) ?? event.data;
  const impactSnapshot = sameInstant(
    graphAsOf,
    eventReferenceTime(selectedEvent, asOf),
  )
    ? graphSnapshot
    : snapshot;
  const impact = useCompanyResource<Impact>(
    ready && eventId
      ? companyUrl(
          id,
          `/issues/${encodeURIComponent(eventId)}/impact`,
          impactSnapshot,
        )
      : null,
  );
  const portfolio = useCompanyResource<Portfolio>(
    auth.isAuthenticated ? '/api/v1/portfolio' : null,
    owner,
  );
  const financials = useCompanyResource<Financials>(
    COMPANY_FINANCIALS_ENABLED && ready
      ? companyUrl(id, '/financials', snapshot)
      : null,
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
  // 최근 버킷부터. 시각을 알 수 없는 버킷은 맨 뒤에 둔다.
  const sortedGroups = [...groups].sort(([a], [b]) =>
    /^\d/.test(a) === /^\d/.test(b)
      ? b.localeCompare(a)
      : /^\d/.test(a)
        ? -1
        : 1,
  );
  // 사건이 많은 기간(예: 1년)에는 최근 버킷부터 나눠 보여 준다. 선택한 버킷은 항상 보인다.
  const bucketScope = `${period}|${asOf ?? ''}`;
  const [bucketPage, setBucketPage] = useState({
    scope: bucketScope,
    limit: BUCKET_PAGE,
  });
  const bucketLimit =
    bucketPage.scope === bucketScope ? bucketPage.limit : BUCKET_PAGE;
  const shownGroups = sortedGroups.slice(
    0,
    Math.max(
      bucketLimit,
      sortedGroups.findIndex(([key]) => key === selectedBucket) + 1,
    ),
  );
  useEffect(() => {
    if (!selectedBucket) return;
    // 스크립트가 고른 smooth는 CSS의 동작 줄이기 규칙보다 앞서므로 여기서 따로 끈다.
    const reduced =
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    document.getElementById(bucketElementId(selectedBucket))?.scrollIntoView?.({
      block: 'nearest',
      behavior: reduced ? 'auto' : 'smooth',
    });
  }, [selectedBucket]);
  const mapQuery = new URLSearchParams({
    mode: 'all',
    select: `node:${eventId ?? id}`,
    companyId: id,
    period,
    tab,
    depth: String(depth),
    returnTo: `${location.pathname}${location.search}`,
  });
  if (graphAsOf) mapQuery.set('asOf', graphAsOf);
  else if (asOf) mapQuery.set('asOf', asOf);
  if (version && !graphAsOf) mapQuery.set('graphVersion', version);
  if (eventId) mapQuery.set('event', eventId);
  // 사건의 관계는 그 사건 시각 기준 지도로 연다. 기업 상세의 기준 시점은 그대로 둔다.
  // 시각이 없으면 현재 기준 시점을 쓰고, 일 정밀도는 그날 한국 시간 끝까지로 본다.
  const eventMapQuery = new URLSearchParams(mapQuery);
  const eventAsOf = eventReferenceTime(event.data, asOf);
  if (eventAsOf) {
    eventMapQuery.set('asOf', eventAsOf);
    // D-COM-06: 사건 링크는 오른쪽 그래프의 임시 시점을 물려받지 않는다.
    // 본문과 같은 시점이면 원래 공개 버전을 복원하고, 다르면 서버가 고른다.
    eventMapQuery.delete('graphVersion');
    if (version && Date.parse(eventAsOf) === Date.parse(asOf ?? ''))
      eventMapQuery.set('graphVersion', version);
  }
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
      // 사건을 골라도 기준 시점은 바꾸지 않는다. 그래프 시점은 [이 당시 관계그래프 보기]로만 옮긴다.
    });
  }
  /** D-COM-06: 사건 시각의 관계 그래프. 월·연 정밀도나 시각 미상, 현재 기준 시점과 같거나 늦은 사건은 옮기지 않는다. */
  const eventGraphTime = (item: Events['items'][number]) => {
    const time = eventReferenceTime(item, asOf);
    return time && asOf && Date.parse(time) < Date.parse(asOf) ? time : null;
  };
  function showEventGraph(item: Events['items'][number], time: string) {
    setClosedGraphTime(null);
    updateQuery({
      graphAsOf: time,
      event: item.id,
      bucket: bucketKey(item, period),
      document: null,
      evidence: null,
    });
    // 좁은 화면에서는 관계 그래프가 본문 아래에 있으므로 바뀐 그래프로 옮겨 보여 준다.
    if (window.matchMedia?.('(max-width: 1000px)').matches)
      graphPanel.current?.scrollIntoView({ block: 'start' });
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
              graphAsOf: null,
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
      <div className="min-w-0 rounded-2xl bg-white p-6 shadow-sm max-md:p-4">
        {versionOnly && (company.loading || versionStart) && (
          <p role="status" className="mb-4 text-body text-zoop-muted">
            그래프 버전({version})이 처음 공개된 시점을 확인하고 있어요.
          </p>
        )}
        {versionOnly && !company.loading && !versionStart && (
          <p role="alert" className="mb-4 text-body text-zoop-alert">
            이 주소에는 기준 시점 없이 그래프 버전({version})만 있어, 그 버전의
            차트·사건·관계 그래프를 열 수 없어요.{' '}
            <button
              type="button"
              className="font-semibold underline"
              // 최신 자료에서 남은 사건 시점(graphAsOf)이 다시 활성화되지 않게 함께 지운다.
              onClick={() =>
                updateQuery({ graphVersion: null, graphAsOf: null })
              }
            >
              최신 자료로 보기
            </button>
          </p>
        )}
        {pinnedFromVersion && !versionStartFailed && (
          <p role="status" className="mb-4 text-body text-zoop-muted">
            {`그래프 버전(${version})이 처음 공개된 시점(${formatKst(asOf!)})으로 보는 중이에요.`}
          </p>
        )}
        {versionStartFailed && (
          <p role="alert" className="mb-4 text-body text-zoop-alert">
            {`그래프 버전(${version})이 처음 공개된 시점으로 열지 못했어요. `}
            <button
              type="button"
              className="font-semibold underline"
              onClick={() =>
                updateQuery({ asOf: null, graphVersion: null, graphAsOf: null })
              }
            >
              최신 자료로 보기
            </button>
          </p>
        )}
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
              <strong className="text-title">
                {quote.data.quote.price === null
                  ? '미제공'
                  : formatMoney(
                      quote.data.quote.price,
                      quote.data.quote.currency,
                    )}
              </strong>
              <span>
                {' '}
                · 전일 대비{' '}
                <ChangeRate
                  rate={quote.data.quote.changeRate}
                  change={quote.data.quote.change}
                  currency={quote.data.quote.currency}
                  className=""
                />
              </span>
              <p>
                공급자 관측{' '}
                <ReferenceTime
                  value={quote.data.quote.asOf}
                  missing="시각 미제공"
                />{' '}
                · {quote.data.source.name} ·{' '}
                {quote.data.source.delayNote ?? '지연 정보 미제공'}
              </p>
              <dl className="my-3 flex flex-wrap gap-x-3 gap-y-2 text-caption [&_dt]:text-zoop-faint [&_dd]:font-semibold max-md:grid max-md:grid-cols-[auto_minmax(0,1fr)]">
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
        {(holding || portfolio.error) && (
          <section aria-label="가상 계좌 보유">
            <h2>가상 계좌 보유 · 프로젝트용 모의 데이터</h2>
            {portfolio.error && (
              <Status resource={portfolio} label="모의 보유" />
            )}
            {holding && (
              <>
                <dl className="my-3 flex flex-wrap gap-x-3 gap-y-2 text-caption [&_dt]:text-zoop-faint [&_dd]:font-semibold max-md:grid max-md:grid-cols-[auto_minmax(0,1fr)]">
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
                      ? '-'
                      : `${number(holding.weight * 100)}%`}
                  </dd>
                </dl>
                <p>
                  모의 수량 기준{' '}
                  <ReferenceTime value={portfolio.data?.mockAsOf} /> · 평가 기준{' '}
                  <ReferenceTime
                    value={portfolio.data?.valuation?.calculatedAt}
                  />
                </p>
                {portfolio.data?.valuation?.weightUnavailableReason && (
                  <p>{portfolio.data.valuation.weightUnavailableReason}</p>
                )}
              </>
            )}
            {!holding && portfolio.data?.connected && (
              <p>이 기업의 모의 보유 종목이 없어요.</p>
            )}
            <Basis metadata={portfolio.data?.metadata} />
          </section>
        )}
        <nav
          aria-label="기업 상세 보기"
          className="my-0! gap-0! border-b border-zoop-line"
        >
          {[
            ['events', '사건'],
            ['documents', '문서'],
            ['info', '기업 정보'],
          ].map(([value, label]) => (
            <button
              key={value}
              aria-pressed={tab === value}
              onClick={() => updateQuery({ tab: value })}
              className={TAB}
            >
              {label}
            </button>
          ))}
        </nav>
        <section aria-label="시세 차트" data-screen-id="D-COM-06">
          <h2 className="sr-only">시세 차트·기준 시점</h2>
          <nav aria-label="차트 기간" className="items-center gap-3!">
            <div className="inline-flex overflow-hidden rounded-[3px] border border-zoop-line">
              {periods.map((p) => (
                <button
                  key={p.value}
                  aria-pressed={period === p.value}
                  className="min-w-14 rounded-none! border-0! border-r! border-zoop-line! last:border-r-0!"
                  onClick={() => {
                    // 선택한 사건은 유지하고, 새 기간의 버킷으로 다시 맞춘다(FS044).
                    const selected = events.data?.items.find(
                      (item) => item.id === eventId,
                    );
                    updateQuery({
                      period: p.value,
                      bucket: selected ? bucketKey(selected, p.value) : null,
                    });
                  }}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <button
              className="font-semibold"
              onClick={() =>
                updateQuery({
                  asOf: null,
                  graphVersion: null,
                  graphAsOf: null,
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
            기준{' '}
            {asOf
              ? formatKst(asOf)
              : versionOnly
                ? '시점 없음'
                : '최신 제공 시점 확인 중'}{' '}
            · {periods.find((p) => p.value === period)?.bucket} 버킷
          </p>
          {prices.data?.status === 'available' &&
            prices.data.points.length > 1 && (
              <PriceChange
                label={periods.find((p) => p.value === period)?.label ?? ''}
                first={prices.data.points[0].close}
                last={prices.data.points.at(-1)!.close}
                currency={prices.data.currency}
              />
            )}
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
                  range={prices.data.range}
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
                />
                <p>
                  {prices.data.source.name} ·{' '}
                  {periods.find((p) => p.value === period)?.bucket}별 종가 ·
                  마지막 시세{' '}
                  {formatKst(prices.data.points.at(-1)?.time ?? null)} ·{' '}
                  {prices.data.source.delayNote ?? '지연 정보 미제공'}
                </p>
                <details className="text-caption">
                  <summary className="cursor-pointer text-zoop-muted">
                    표로 보기
                  </summary>
                  <table className="mt-2 w-full text-left tabular-nums">
                    <thead>
                      <tr className="text-zoop-muted">
                        <th className="py-1 font-medium">시각</th>
                        <th className="py-1 text-right font-medium">종가</th>
                      </tr>
                    </thead>
                    <tbody>
                      {prices.data.points.map((point) => (
                        <tr
                          key={point.time}
                          className="border-t-[0.667px] border-zoop-line"
                        >
                          <td className="py-1">
                            <ReferenceTime value={point.time} />
                          </td>
                          <td className="py-1 text-right">
                            {number(point.close)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              </>
            ))}
          <p className="border-l-2 border-zoop-faint bg-zoop-soft p-2 text-caption text-zoop-muted">
            차트와 사건의 시점이 겹쳐도 인과관계를 뜻하지 않아요.
          </p>
        </section>
        {tab === 'events' && (
          <section aria-label="사건 타임라인" data-screen-id="D-COM-05">
            <h2>사건 타임라인</h2>
            <Status resource={events} label="타임라인" />
            {!ready && !versionOnly && (
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
                <p className="text-caption text-zoop-muted">
                  {periods.find((p) => p.value === period)?.label} · 사건{' '}
                  {events.data.items.length}건 · 시점 미상 제외{' '}
                  {events.data.metadata.excludedUnknownTime ?? 0}건
                </p>
                {!groups.size && (
                  <p className="text-caption text-zoop-muted">
                    해당 기간에 공개·유효한 사건이 없어요.
                  </p>
                )}
                {/* FS041: 시간 버킷마다 사건 수를 보이고 사건 카드를 나열한다. 차트 ⚡ 표식이나 버킷을 고르면 그 버킷을 강조한다. */}
                <ol className="flex flex-col">
                  {shownGroups.map(([key, items]) => (
                    <li
                      key={key}
                      id={bucketElementId(key)}
                      className={`grid grid-cols-[7rem_1fr] gap-4 border-b-[0.667px] border-zoop-line px-2 py-4 ${selectedBucket === key ? 'bg-zoop-wash' : ''}`}
                    >
                      <p className="text-caption text-zoop-muted tabular-nums">
                        {key}
                      </p>
                      <div className="flex flex-col gap-3">
                        <button
                          aria-pressed={selectedBucket === key}
                          aria-label={`${key} · 사건 ${items.length}건`}
                          onClick={() =>
                            updateQuery({
                              bucket: key,
                              event: null,
                              document: null,
                              evidence: null,
                            })
                          }
                          className="border-0! bg-transparent! min-h-0! p-0! aria-pressed:bg-transparent! aria-pressed:text-zoop-ink! inline-flex items-center gap-1 self-start font-semibold text-zoop-ink aria-pressed:underline"
                        >
                          <BoltIcon />
                          사건 {items.length}건
                        </button>
                        {items.map((item) => {
                          const itemGraphTime = eventGraphTime(item);
                          return (
                            <article
                              key={item.id}
                              className="flex flex-col gap-1 border-0! py-0! xl:grid xl:grid-cols-[minmax(0,1fr)_auto] xl:items-start xl:gap-x-3 xl:[&>*]:col-start-1"
                            >
                              <p className="text-caption text-zoop-muted">
                                문서 {item.articleCount}건 ·{' '}
                                {relationLabel(item.relationTypes) ||
                                  '직접 관계 미확인'}
                              </p>
                              <button
                                aria-pressed={eventId === item.id}
                                onClick={() => selectEvent(item)}
                                className="border-0! bg-transparent! min-h-0! p-0! aria-pressed:bg-transparent! aria-pressed:text-zoop-ink! self-start text-left text-body! font-semibold text-zoop-ink underline-offset-4 hover:underline aria-pressed:underline"
                              >
                                {item.title}
                              </button>
                              <p className="text-caption text-zoop-muted tabular-nums">
                                {item.eventTime ? (
                                  <time dateTime={item.eventTime}>
                                    {formatTimelineTime(
                                      item.eventTime,
                                      item.timePrecision,
                                    )}
                                  </time>
                                ) : (
                                  '시점 미상'
                                )}
                              </p>
                              <button
                                onClick={() => selectEvent(item, 'documents')}
                                className="border-0! bg-transparent! min-h-0! p-0! aria-pressed:bg-transparent! aria-pressed:text-zoop-ink! self-start text-caption! text-zoop-muted underline underline-offset-4"
                              >
                                근거 문서 {item.articleCount}건 보기
                              </button>
                              {itemGraphTime && (
                                <button
                                  type="button"
                                  aria-pressed={
                                    sameInstant(graphAsOf, itemGraphTime) &&
                                    eventId === item.id
                                  }
                                  data-graph-time-trigger
                                  aria-label={`${item.title} · 이 당시 관계그래프 보기`}
                                  onClick={() =>
                                    showEventGraph(item, itemGraphTime)
                                  }
                                  className="mt-1 inline-flex items-center gap-1.5 self-start whitespace-nowrap xl:col-start-2! xl:row-span-4 xl:row-start-1 xl:mt-0 xl:self-center"
                                >
                                  <ClockIcon />이 당시 관계그래프 보기
                                </button>
                              )}
                            </article>
                          );
                        })}
                      </div>
                    </li>
                  ))}
                </ol>
                {shownGroups.length < sortedGroups.length && (
                  <button
                    onClick={() =>
                      setBucketPage({
                        scope: bucketScope,
                        limit: shownGroups.length + BUCKET_PAGE,
                      })
                    }
                    className="self-start"
                  >
                    이전 사건 더 보기 (
                    {sortedGroups.length - shownGroups.length}개 날짜)
                  </button>
                )}
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
                        · 보도 시각{' '}
                        <ReferenceTime value={item.reportedAt} missing="미상" />{' '}
                        (사건 시각 아님)
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
                    <Link to={`/?${eventMapQuery}`}>
                      이 사건 시점의 관계를 지도에서 보기
                    </Link>
                  </article>
                )}
              </>
            )}
          </section>
        )}
        {tab === 'documents' && <CompanyDocumentPanel />}
        {tab === 'info' && <CompanyInfoTab resource={company} />}
        {COMPANY_FINANCIALS_ENABLED && (
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
                          {f.accountingBasis ?? '회계 기준 미제공'} · {f.source}{' '}
                          · <ReferenceTime value={f.asOf} />
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
        )}
      </div>
      {/* D-COM-04: 넓은 화면은 와이어프레임처럼 오른쪽 열에 두고 스크롤해도 화면 안에 남는다.
          1000px 이하에서는 본문 아래로 옮겨 넓게 본다. */}
      <aside
        ref={graphPanel}
        className="min-w-0 self-start rounded-2xl bg-white p-4 shadow-sm min-[1001px]:sticky min-[1001px]:top-4 min-[1001px]:max-h-[calc(100vh-2rem)] min-[1001px]:overflow-y-auto max-[1000px]:col-start-2 [&_li]:text-caption [&_li]:wrap-anywhere [&_svg]:h-auto [&_svg]:w-full [&_svg]:bg-zoop-line max-md:w-full"
        aria-label="시점 기반 관계 그래프"
        data-screen-id="D-COM-04"
      >
        <div className="flex items-center justify-between gap-2">
          <h2 className="mb-0!">관계 그래프</h2>
          <Link className={ui.button} to={`/?${mapQuery}`}>
            지도에서 보기
          </Link>
        </div>
        <nav aria-label="관계 깊이" className="grid! grid-cols-2 gap-0!">
          {[1, 2].map((d) => (
            <button
              key={d}
              aria-pressed={depth === d}
              className="rounded-none! first:rounded-l-[3px]! last:rounded-r-[3px]!"
              onClick={() => updateQuery({ depth: String(d), bucket: null })}
            >
              {d}단계
            </button>
          ))}
        </nav>
        {graphAsOf && (
          <p role="status" className="mt-2">
            사건 시점 {formatKst(graphAsOf)} 기준 관계예요. 차트·타임라인은 기존
            기준 시점 그대로예요.
          </p>
        )}
        <Status resource={graph} label="관계 그래프" />
        {!ready && !versionOnly && (
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
              key={`${id}:${asOf}:${version}:${graphAsOf}:${depth}`}
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
                  next.delete('graphAsOf');
                  navigate(`/companies/${encodeURIComponent(node)}?${next}`);
                }
              }}
            />
          </>
        )}
        {/* 사건 시점 그래프를 열 수 없어도(공개 버전 없음 등) 돌아갈 수 있게 그래프 상태와 상관없이 둔다. */}
        {graphAsOf && (
          <div className="mt-2 flex justify-end">
            <button
              type="button"
              aria-label="현재 시점 관계 그래프로 돌아가기"
              title="현재 시점으로"
              className={`${ui.button} inline-flex items-center gap-1`}
              onClick={() => updateQuery({ graphAsOf: null })}
            >
              <HomeIcon />
              현재
            </button>
          </div>
        )}
        {eventId && (
          <>
            <Status resource={impact} label="영향 경로" />
            {impact.data && (
              <>
                <h3>
                  {impact.data.pathStatus ===
                  'structural_path_details_unavailable'
                    ? '구조 경로 상세'
                    : impact.data.steps.length
                      ? '공개 자료에 확인된 영향 경로'
                      : '직접 연결 확인'}
                </h3>
                {!impact.data.steps.length && (
                  <p>
                    {impact.data.pathStatus ===
                    'structural_path_details_unavailable'
                      ? '구조 관계는 공개 그래프에서 확인됐지만, 전체 경로 상세는 제공되지 않아요.'
                      : '이 기준 시점의 공개 그래프에서 기업과 사건의 직접 연결을 확인하지 못했어요.'}
                  </p>
                )}
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
