// UI-06 기업 상세(요구 35–41, 명세 v1.2 FS038·FS040·FS041·FS044). 개요(머리글)·시세·지표·가상 보유·차트·사건·문서를 각자 독립 요청으로
// 화면을 열 때 함께 조회하고(탭에 가려진 차트·문서도 미리 조회한다) 준비되는 대로 그린다. 한 영역이 실패하면 그 영역만 오류와
// [다시 시도]를 보이고, 자료 없음은 빈 안내, 권한 없음(비회원의 보유)은 영역을 숨긴다. 기업이 바뀌면 화면 상태를 통째로 새로 만든다(key).
// 시세(현재가·지표)는 개요와 따로 조회하고, 주가 차트는 사건 탭에서 타임라인과 같은 범위로 함께 바뀐다.
// 주소 상태: ?tab=events|documents|info, ?period=1d|1m|1y(기본 1m), ?event=<사건>, ?open=<펼친 날짜 묶음>.
//  - 탭·기간은 이력에 쌓고(push, 뒤로 가기로 되돌림), 사건 선택·묶음 펼침은 바꿔 쓴다(replace).
// 기간 전환(FS040·D04): 조회 범위는 KST 조회 시각을 공통 종료 시각으로 새로 잡는다(lib/company-timeline detailRange).
//  - 바꾸는 즉시 이전 사건 상세와 강조를 거두되 선택 사건 id는 주소에 잠정으로 남긴다.
//  - 새 사건 목록이 성공하면 그 사건이 있으면 새 범위로 상세를 다시 조회해 선택을 유지하고, 없으면 선택을 풀고 알린다.
//  - 목록 조회가 실패하면 선택을 풀지 않는다(사건 없음으로 판정하지 않는다). 목록 [다시 시도]가 성공한 뒤 판단한다.
// 그래프 왕복(FS044·D06):
//  - [그래프로 돌아가기]는 이 상세에 들어온 그래프 상태(주소·카메라·범례, lib/graph-entry)로 간다. 그래프에서 들어오지 않았으면
//    (직접 주소·내 종목·브리핑) 전체 관계 그래프를 연다. 브라우저 뒤로 가기는 실제 이력을 따르며 이 화면이 막지 않는다.
//  - [지도에서 보기]는 시장 전체 지도에 ?select=node:<사건>&focus=<사건>&hops=1 로 사건과 연결 기업을 강조하고,
//    지도 쪽 복귀 링크(state.returnTo)와 브라우저 뒤로 가기 모두 이 주소로 돌아온다. 스크롤 위치는 떠날 때 저장해 내용이
//    준비되면 되돌린다. 돌아오면 범위를 새로 잡아 다시 조회하고 선택 사건은 위 규칙으로 유지·해제한다.
//  - 보관하는 상태: 기업(경로)·차트 기간·선택 사건·탭·스크롤. 재무 기간은 재무 기능이 없어 두지 않는다.
//  - 상세를 떠나면 진행 중인 상세 조회를 취소해, 떠나기 전 응답이 돌아온 뒤의 새 조회를 덮지 않게 한다.
import { Building2, FileText, Map as MapIcon, Network, Zap } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, type Schemas } from "@/api/client";
import { queryKeys, useCompany, useCompanyDocuments, useCompanyEvents, useCompanyPrices, useEventInRange } from "@/api/queries";
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
import { useOverlays } from "@/features/overlays";
import { detailRange, parsePeriod, type Period } from "@/lib/company-timeline";
import { FULL_GRAPH_URL, isGraphUrl, readGraphEntry, type GraphEntry, type GraphRestoreState } from "@/lib/graph-entry";
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
  const selectedId = params.get("event");
  const openGroups = new Set((params.get("open") ?? "").split(",").filter(Boolean));

  // 조회 범위: 처음 그릴 때와 기간이 바뀔 때마다 그 시각을 공통 종료 시각으로 새로 잡는다(뒤로 가기로 기간이 바뀌어도 같다).
  const [range, setRange] = useState(() => detailRange(period));
  if (range.period !== period) setRange(detailRange(period));

  const company = useCompany(companyId);
  const events = useCompanyEvents(companyId, range);
  // 선택 사건은 새 목록에서 확인된 뒤에만 상세를 조회하고 강조한다. 그 전까지 주소의 id는 잠정 보관이다.
  const listed = events.isSuccess && selectedId !== null && [...events.data.items, ...events.data.unknownTimeItems].some((e) => e.id === selectedId);
  const confirmedId = listed ? selectedId : null;
  const selectedEvent = useEventInRange(confirmedId, range.to);
  // 탭 안 영역(차트·문서)도 탭을 열기 전에 요청을 시작한다. 같은 키라 탭의 컴포넌트는 이 결과를 그대로 쓴다.
  useCompanyPrices(companyId, range);
  useCompanyDocuments(companyId);

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
    else navigate(FULL_GRAPH_URL);
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
  const setTab = (next: Tab) => update((p) => p.set("tab", next), false);
  const setPeriod = (next: Period) => {
    if (next === period) return;
    update((p) => {
      p.set("period", next);
      p.delete("open");
    }, false);
  };
  const selectEvent = (eventId: string | null) => update((p) => (eventId ? p.set("event", eventId) : p.delete("event")), true);
  // 날짜 선택(FS041): 묶음을 펼치면 날짜를 고른 것이라 이전 선택(상세·차트 강조)을 거둔다. 접을 때는 그 묶음 안의 선택만 푼다.
  const toggleGroup = (key: string, eventIds: string[], expand: boolean) =>
    update((p) => {
      const open = new Set(openGroups);
      if (expand) open.add(key);
      else open.delete(key);
      if (open.size > 0) p.set("open", [...open].join(","));
      else p.delete("open");
      if (expand || (selectedId !== null && eventIds.includes(selectedId))) p.delete("event");
    }, true);
  // 차트에서 날짜를 고르면 묶음을 펼치고, 그 날짜 사건이 1건이면 자동 선택(상세 조회), 여러 건이면 선택을 비워 카드에서 고르게 한다.
  const pickDate = (keys: string[], eventIds: string[]) =>
    update((p) => {
      p.set("open", [...new Set([...openGroups, ...keys])].join(","));
      if (eventIds.length === 1) p.set("event", eventIds[0]!);
      else p.delete("event");
    }, true);

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
    navigate(`/?mode=all&select=${encodeURIComponent(`node:${event.id}`)}&focus=${encodeURIComponent(event.id)}&hops=1`, { state: { returnTo } });
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
    <Page onBackToGraph={backToGraph} hasEntry={graphEntry !== null}>
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
          />
        </TabsContent>
        <TabsContent value="documents">
          <CompanyDocuments companyId={companyId} />
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

function Page({ onBackToGraph, hasEntry, children }: { onBackToGraph: () => void; hasEntry: boolean; children: React.ReactNode }) {
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 px-4 py-4 md:px-6 md:py-6">
      <Button variant="ghost" size="sm" className="-ml-3 w-fit" onClick={onBackToGraph}>
        <Network aria-hidden="true" />
        {hasEntry ? "그래프로 돌아가기" : "관계 그래프 보기"}
      </Button>
      {children}
      <DisclaimerNote className="pt-2" />
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
