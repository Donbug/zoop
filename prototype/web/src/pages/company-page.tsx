// FS038–044: 기업 전환은 period/asOf/tab을 유지하고 issue/bucket/open을 해제한다.
// 차트·타임라인·관계 그래프는 주소에 고정한 동일 공개 기준 시점을 독립 조회한다.
// 탭·기간·시점은 push, 사건·버킷 선택은 replace. 진입 지도·복귀 스크롤 계약은 유지한다.
import { Building2, FileText, Map as MapIcon, Network, Zap } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, type Schemas } from "@/api/client";
import { queryKeys, useCompany, useCompanyDocuments, useCompanyEvents, useCompanyGraph, useCompanyPrices, useEventInRange } from "@/api/queries";
import { CompanyHeader } from "@/components/domain/company-header";
import { DisclaimerNote } from "@/components/domain/status-labels";
import { Button } from "@/components/ui/button";
import { EmptyState, SkeletonLines, ErrorState } from "@/components/ui/feedback";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { CompanyDocuments } from "@/features/company-documents";
import { CompanyHolding } from "@/features/company-holding";
import { CompanyMetrics } from "@/features/company-metrics";
import { CompanyQuote } from "@/features/company-quote";
import { CompanyTimeline } from "@/features/company-timeline";
import { CompanyGraph } from "@/features/company-graph";
import { CompanySwitcher } from "@/features/company-switcher";
import { useOverlays, useScreenChatTargets } from "@/features/overlays";
import { companySwitchUrl, detailRange, eventEndDate, exchangeZone, groupEvents, parseAsOf, parsePeriod, widerPeriodFor, type Period } from "@/lib/company-timeline";
import { isGraphUrl, readGraphEntry, type GraphEntry, type GraphRestoreState } from "@/lib/graph-entry";
import { formatEventTime } from "@/lib/labels";

type Tab = "events" | "documents" | "info";

/** 지도로 갈 때 실어 보내는 복귀 정보. 지도(main-page)의 복귀 링크가 읽는다. graphEntry는 이 상세의 진입 그래프. */
export interface CompanyReturn {
  path: string;
  label: string;
  state: { from: string; restoreScroll: true; graphEntry: GraphEntry | null };
}

const SCROLL_KEY = "zoop:company-scroll";
const ENTRY_KEY = "zoop:company-graph-entry";
// 문서를 새로 읽으면 첫 이력 항목의 key가 다시 'default'가 되므로, 이전 문서에서 저장한 그 칸은 버린다.
sessionStorage.removeItem(`${SCROLL_KEY}:default`);
sessionStorage.removeItem(`${ENTRY_KEY}:default`);

function storedEntry(historyKey: string): GraphEntry | null {
  try {
    const raw = sessionStorage.getItem(`${ENTRY_KEY}:${historyKey}`);
    return raw ? (JSON.parse(raw) as GraphEntry) : null;
  } catch {
    return null;
  }
}

export function CompanyPage() {
  const { id = "" } = useParams<{ id: string }>();
  return <CompanyDetailScreen key={id} companyId={id} />;
}

function CompanyDetailScreen({ companyId }: { companyId: string }) {
  const location = useLocation();
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { openChat } = useOverlays();
  const [params, setParams] = useSearchParams();
  const locationState = location.state as { from?: unknown; restoreScroll?: unknown; graphEntry?: GraphEntry | null } | null;
  const from = typeof locationState?.from === "string" && locationState.from.startsWith("/") ? locationState.from : null;

  const tabParam = params.get("tab");
  const tab: Tab = tabParam === "documents" || tabParam === "info" ? tabParam : "events";
  const period = parsePeriod(params.get("period"));
  const selectedId = params.get("issue");
  const openGroups = new Set((params.get("open") ?? "").split(",").filter(Boolean));

  const [initialAsOf] = useState(() => new Date());
  const asOfParam = params.get("asOf");
  const asOf = parseAsOf(asOfParam) ?? initialAsOf;
  const range = detailRange(period, asOf, exchangeZone(companyId));
  const hops = params.get("hops") === "2" ? 2 : 1;
  const selectedBucket = params.get("bucket");
  const graph = useCompanyGraph(companyId, range.to, hops);

  const company = useCompany(companyId, range.to);
  // 하단 [AI] 탭으로 질문 창을 열면 이 기업을 질문 대상으로 넘긴다(기업 정보를 받기 전에는 넘기지 않는다).
  useScreenChatTargets(company.data ? [{ id: companyId, kind: "company", label: company.data.name }] : []);
  const events = useCompanyEvents(companyId, range, hops);
  // 선택 사건은 새 목록에서 확인된 뒤에만 상세를 조회하고 강조한다. 그 전까지 주소의 id는 잠정 보관이다.
  const listed = events.isSuccess && selectedId !== null && [...events.data.items, ...events.data.unknownTimeItems].some((e) => e.id === selectedId);
  const confirmedId = listed ? selectedId : null;
  const selectedEvent = useEventInRange(confirmedId, range.to);
  // 탭 안 영역(차트·문서)도 탭을 열기 전에 요청을 시작한다. 같은 키라 탭의 컴포넌트는 이 결과를 그대로 쓴다.
  useCompanyPrices(companyId, range);
  useCompanyDocuments(companyId, range);

  // 진입 그래프: 지도에서 들어왔으면 그 상태를 이 이력 항목에 묶어 둔다(뒤로 가기로 돌아와도 같은 진입 그래프).
  const entryKey = location.key;
  const [graphEntry, setGraphEntry] = useState<GraphEntry | null>(() => locationState?.graphEntry ?? storedEntry(entryKey));
  useEffect(() => {
    if (graphEntry || !from || !isGraphUrl(from)) return;
    const saved = readGraphEntry();
    setGraphEntry(saved && saved.url === from ? saved : { url: from });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (graphEntry) sessionStorage.setItem(`${ENTRY_KEY}:${entryKey}`, JSON.stringify(graphEntry));
  }, [graphEntry, entryKey]);
  const backToGraph = () => {
    if (graphEntry) navigate(graphEntry.url, { state: { graphRestore: graphEntry } satisfies GraphRestoreState });
    else navigate(`/?mode=all&focus=${encodeURIComponent(companyId)}&hops=1&asOf=${encodeURIComponent(range.to)}`);
  };

  // 상세를 떠나면 진행 중인 이 기업 조회를 취소한다(FS044: 이탈 전 응답이 복귀 후 화면에 반영되지 않게).
  useEffect(
    () => () => {
      for (const key of [queryKeys.company(companyId), queryKeys.quote(companyId), queryKeys.metrics(companyId), ["prices", companyId], ["events", companyId], queryKeys.companyDocuments(companyId), ["event"]])
        void queryClient.cancelQueries({ queryKey: key, fetchStatus: "fetching" });
    },
    [companyId, queryClient],
  );

  // 없어진 탭을 요청받으면 사건 탭(기업 개요 아래 기본 탭)으로 옮기고 알린다.
  const unknownTab = tabParam !== null && tabParam !== "events" && tabParam !== "documents" && tabParam !== "info";
  useEffect(() => {
    if (!unknownTab) return;
    update((p) => p.delete("tab"), true);
    toast({ title: "요청한 탭이 없어 사건 탭을 보여 드려요", tone: "warning" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [unknownTab]);

  const update = (change: (p: URLSearchParams) => void, replace: boolean) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        change(next);
        return next;
      },
      { replace, state: location.state, preventScrollReset: true },
    );
  useEffect(() => {
    if (parseAsOf(asOfParam)) return;
    update(p => p.set("asOf", initialAsOf.toISOString()), true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asOfParam, initialAsOf]);
  const switchCompany = (id: string) => navigate(companySwitchUrl(id, params), { state: { ...locationState, graphEntry } });
  const setAsOf = (time: string) => update(p => {
    p.set("asOf", new Date(time).toISOString());
    p.delete("open");
    p.delete("bucket");
  }, false);
  const setTab = (next: Tab) => update((p) => p.set("tab", next), false);
  const setPeriod = (next: Period) => {
    if (next === period) return;
    update((p) => {
      p.set("period", next);
      p.delete("open");
      p.delete("bucket");
    }, false);
  };
  const selectEvent = (eventId: string | null) => update(p => {
    if (eventId) p.set("issue", eventId); else p.delete("issue");
    const bucket = groupEvents(events.data?.items ?? [], [], period, range.timeZone).find(group => group.items.some(event => event.id === eventId));
    if (bucket) p.set("bucket", bucket.key); else p.delete("bucket");
  }, true);
  // 날짜 선택(FS041): 묶음을 펼치면 날짜를 고른 것이라 이전 선택(상세·차트 강조)을 거둔다. 접을 때는 그 묶음 안의 선택만 푼다.
  const toggleGroup = (key: string, eventIds: string[], expand: boolean) =>
    update((p) => {
      const open = new Set(openGroups);
      if (expand) open.add(key);
      else open.delete(key);
      if (open.size > 0) p.set("open", [...open].join(","));
      else p.delete("open");
      if (expand) {
        p.set("bucket", key);
        if (eventIds.length === 1) p.set("issue", eventIds[0]!);
        else if (!selectedId || !eventIds.includes(selectedId)) p.delete("issue");
      } else if (selectedId && eventIds.includes(selectedId)) {
        p.delete("issue");
        p.delete("bucket");
      }
    }, true);
  // 차트에서 날짜를 고르면 묶음을 펼치고, 그 날짜 사건이 1건이면 자동 선택(상세 조회), 여러 건이면 선택을 비워 카드에서 고르게 한다.
  const pickDate = (keys: string[], eventIds: string[]) =>
    update((p) => {
      p.set("open", [...new Set([...openGroups, ...keys])].join(","));
      p.set("bucket", keys[0]!);
      if (eventIds.length === 1) p.set("issue", eventIds[0]!);
      else if (!selectedId || !eventIds.includes(selectedId)) p.delete("issue");
    }, true);
  const highlightedIds = useMemo(() => {
    const groups = events.data ? groupEvents(events.data.items, [], period, range.timeZone) : [];
    return new Set(confirmedId ? [confirmedId] : selectedId ? [] : groups.filter(group => group.key === selectedBucket).flatMap(group => group.items.map(event => event.id)));
  }, [events.data, period, range.timeZone, confirmedId, selectedId, selectedBucket]);
  const pickGraphIssue = (id: string) => {
    const node = graph.data?.nodes.find(node => node.id === id);
    const date = eventEndDate(node?.eventTime);
    const wider: Period | null = !date ? (period !== "1y" ? "1y" : null) : date < range.from.slice(0, 10) ? widerPeriodFor(date, period, range.today) : null;
    update(p => {
      p.set("tab", "events");
      p.set("issue", id);
      if (wider) {
        p.set("period", wider);
        p.delete("open");
      }
      p.delete("bucket");
    }, true);
  };

  // 선택 사건 판정: 새 목록이 성공했는데 없으면(기간 밖) 또는 상세가 404이면 선택을 풀고 알린다. 목록 실패는 판정하지 않는다.
  const outOfRange = selectedId !== null && events.isSuccess && !listed;
  const gone = confirmedId !== null && selectedEvent.error instanceof ApiError && selectedEvent.error.status === 404;
  useEffect(() => {
    if (!outOfRange && !gone) return;
    selectEvent(null);
    toast({ title: gone ? "선택했던 사건을 지금은 볼 수 없어 선택을 풀었어요" : "선택했던 사건이 이 기간에 없어 선택을 풀었어요", tone: "warning" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outOfRange, gone]);

  // 스크롤 위치: 스크롤할 때마다 기억해 두었다가 화면을 떠날 때 이 이력 항목(location.key)과 '마지막 기업 상세' 칸에 저장한다.
  const url = location.pathname + location.search;
  const scrollY = useRef(0);
  const urlRef = useRef(url);
  urlRef.current = url;
  useEffect(() => {
    const onScroll = () => {
      scrollY.current = window.scrollY;
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  const historyKey = location.key;
  useLayoutEffect(
    () => () => {
      const saved = JSON.stringify({ url: urlRef.current, y: scrollY.current });
      sessionStorage.setItem(`${SCROLL_KEY}:${historyKey}`, saved);
      sessionStorage.setItem(`${SCROLL_KEY}:last`, saved);
    },
    [historyKey],
  );
  const [pendingScroll, setPendingScroll] = useState<number | null>(() => {
    const raw = sessionStorage.getItem(`${SCROLL_KEY}:${location.key}`) ?? (locationState?.restoreScroll === true ? sessionStorage.getItem(`${SCROLL_KEY}:last`) : null);
    if (!raw) return null;
    const saved = JSON.parse(raw) as { url: string; y: number };
    return saved.url === url ? saved.y : null;
  });
  const settled = (q: { isPending: boolean; fetchStatus: string }) => !q.isPending || q.fetchStatus === "idle";
  const ready = settled(company) && (tab !== "events" || (settled(events) && (confirmedId === null || settled(selectedEvent))));
  useEffect(() => {
    if (pendingScroll === null || !ready) return;
    const frame = requestAnimationFrame(() => {
      window.scrollTo({ top: pendingScroll, behavior: "instant" });
      setPendingScroll(null);
    });
    return () => cancelAnimationFrame(frame);
  }, [pendingScroll, ready]);

  if (company.error instanceof ApiError && company.error.status === 404) {
    return (
      <Page onBackToGraph={backToGraph} hasEntry={graphEntry !== null}>
        <EmptyState
          title="기업을 찾을 수 없어요"
          description="주소가 바뀌었거나 지금은 제공하지 않는 기업이에요. 지도에서 다른 기업을 찾아보세요."
          action={
            <>
              <Button asChild>
                <Link to="/?mode=all">
                  <MapIcon aria-hidden="true" />
                  시장 전체 지도에서 찾기
                </Link>
              </Button>
              <Button variant="ghost" asChild>
                <Link to="/me/stocks">내 종목 보기</Link>
              </Button>
            </>
          }
        />
      </Page>
    );
  }

  const companyName = company.data?.name ?? companyId;
  const showOnMap = (event: Schemas["EventDetail"]) => {
    const returnTo: CompanyReturn = { path: url, label: companyName, state: { from: from ?? "/", restoreScroll: true, graphEntry } };
    navigate(`/?mode=all&select=${encodeURIComponent(`node:${event.id}`)}&focus=${encodeURIComponent(companyId)}&hops=2&asOf=${encodeURIComponent(range.to)}`, { state: { returnTo } });
  };
  const ask = (event: Schemas["EventDetail"]) =>
    openChat({
      targets: [
        { id: companyId, kind: "company", label: companyName },
        {
          id: event.id,
          kind: "issue",
          evidenceIds: event.evidenceIds,
          label: event.title,
          detail: [event.timePrecision !== "unknown" && formatEventTime(event.eventTime, event.timePrecision), `근거 ${event.evidenceIds.length}건`]
            .filter(Boolean)
            .join(" · "),
        },
      ],
    });

  return (
    <Page onBackToGraph={backToGraph} hasEntry={graphEntry !== null}
      switcher={<CompanySwitcher companyId={companyId} company={company.data} asOf={range.to} connectedIds={graph.data?.nodes.filter(node => node.kind === "company").map(node => node.id) ?? []} onSwitch={switchCompany} />}
      graph={<CompanyGraph companyId={companyId} graph={graph} asOf={range.to} hops={hops} onHops={hops => update(p => p.set("hops", String(hops)), false)} selectedId={confirmedId} highlightedIds={highlightedIds} onIssue={pickGraphIssue} onCompany={switchCompany} onMap={() => {
        const returnTo: CompanyReturn = { path: url, label: companyName, state: { from: from ?? "/", restoreScroll: true, graphEntry } };
        navigate(`/?mode=all&focus=${encodeURIComponent(companyId)}&hops=${hops}&asOf=${encodeURIComponent(range.to)}${confirmedId ? `&select=${encodeURIComponent(`node:${confirmedId}`)}` : ""}`, { state: { returnTo } });
      }} />}
    >
      {company.isPending && <SkeletonLines lines={2} label="기업 정보를 불러오고 있어요" />}
      {company.isError && <ErrorState compact error={company.error} title="기업 정보를 불러오지 못했어요" onRetry={() => void company.refetch()} />}
      {company.data && (
        <CompanyHeader
          as="h1"
          id={company.data.id}
          name={company.data.name}
          ticker={company.data.ticker}
          sector={company.data.sector}
          brandColor={company.data.brandColor}
          logoUrl={company.data.logoUrl}
          holding={company.data.holding}
          watch={company.data.watch}
        />
      )}
      {!company.data && <h1 className="sr-only">기업 상세</h1>}
      <CompanyQuote companyId={companyId} />
      <CompanyMetrics companyId={companyId} />
      <CompanyHolding companyId={companyId} />

      <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)} className="flex flex-col gap-2">
        <TabsList className="w-full md:w-96">
          <TabsTrigger value="events">
            <Zap aria-hidden="true" />
            사건
          </TabsTrigger>
          <TabsTrigger value="documents">
            <FileText aria-hidden="true" />
            문서
          </TabsTrigger>
          <TabsTrigger value="info">
            <Building2 aria-hidden="true" />
            기업 정보
          </TabsTrigger>
        </TabsList>
        <TabsContent value="events">
          <CompanyTimeline
            companyId={companyId}
            company={company.data}
            events={events}
            selectedEvent={selectedEvent}
            range={range}
            onPeriodChange={setPeriod}
            selectedId={confirmedId}
            onSelect={selectEvent}
            openGroups={openGroups}
            onToggleGroup={toggleGroup}
            onShowOnMap={showOnMap}
            onAsk={ask}
            onPickDate={pickDate}
            selectedBucket={selectedBucket}
            onAsOfChange={setAsOf}
            onLatest={() => setAsOf(new Date().toISOString())}
            onCompany={switchCompany}
          />
        </TabsContent>
        <TabsContent value="documents">
          <CompanyDocuments companyId={companyId} range={range} />
        </TabsContent>
        <TabsContent value="info">
          {company.isPending && <SkeletonLines lines={3} label="기업 정보를 불러오고 있어요" />}
          {company.isError && <ErrorState error={company.error} title="기업 정보를 불러오지 못했어요" onRetry={() => void company.refetch()} />}
          {company.data && <CompanyInfo company={company.data} />}
        </TabsContent>
      </Tabs>
    </Page>
  );
}

function Page({ onBackToGraph, hasEntry, children, switcher, graph }: { onBackToGraph: () => void; hasEntry: boolean; children: React.ReactNode; switcher?: React.ReactNode; graph?: React.ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-[1800px] px-4 py-4 md:px-6 md:py-6">
      <div className={switcher ? "grid min-w-0 grid-cols-1 items-start gap-6 lg:grid-cols-[272px_minmax(0,1fr)]" : "grid min-w-0 grid-cols-1 items-start gap-6"}>
        {switcher}
        <div className="grid min-w-0 grid-cols-1 items-start gap-6 min-[1400px]:grid-cols-[minmax(0,1fr)_360px] 2xl:grid-cols-[minmax(0,1fr)_420px]">
          <div data-company-detail-body className="flex min-w-0 flex-col gap-4">
            <Button variant="ghost" size="sm" className="-ml-3 w-fit" onClick={onBackToGraph}><Network aria-hidden="true" />{hasEntry ? "그래프로 돌아가기" : "관계 그래프 보기"}</Button>
            {children}
            <DisclaimerNote className="pt-2" />
          </div>
          <div className="min-w-0 min-[1400px]:sticky min-[1400px]:top-20">{graph}</div>
        </div>
      </div>
    </div>
  );
}

/** 카탈로그에 있는 값만 행으로 보인다. 없는 값(AI 요약·재무 지표·빈 별칭)은 자리를 만들지 않는다. 시장은 종목 id 앞부분(KRX:…)이다. */
function CompanyInfo({ company }: { company: Schemas["CompanyDetail"] }) {
  const market = company.id.includes(":") ? company.id.split(":")[0]! : null;
  const rows = ([
    ["종목 코드", company.ticker],
    ["시장", market],
    ["다른 이름", company.aliases.length > 0 ? company.aliases.join(", ") : null],
    ["업종", company.sector],
  ] satisfies [string, string | null][]).filter((row): row is [string, string] => Boolean(row[1]));
  if (rows.length === 0) return <EmptyState title="등록된 기업 정보가 없어요" />;
  return (
    <dl className="flex flex-col pt-2">
      {rows.map(([label, value]) => (
        <div key={label} className="grid min-h-12 grid-cols-[6rem_minmax(0,1fr)] items-center gap-x-3 border-b border-border-subtle py-3 text-base last:border-b-0 md:grid-cols-[8rem_minmax(0,1fr)]">
          <dt className="text-sm text-text-secondary">{label}</dt>
          <dd className="text-text-primary">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
