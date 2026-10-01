// UI-06 기업 상세(요구 35–41). 개요(머리글)·가상 보유·사건·문서·기업 정보를 각자 조회해 준비되는 대로 그리고,
// 한 영역이 실패하면 그 영역만 오류와 [다시 시도]를 보인다(요구 54). 기업이 바뀌면 화면 상태를 통째로 새로 만든다(key).
// 시세(현재가·지표)는 개요와 따로 조회하고, 주가 차트는 사건 탭에서 타임라인과 같은 기간으로 함께 바뀐다(요구 35·37).
// 주소 상태(요구 41): ?tab=events|documents|info, ?period=1d|1m|1y(기본 1m), ?event=<사건>, ?open=<펼친 날짜 묶음>.
//  - 탭·기간은 이력에 쌓고(push, 뒤로 가기로 되돌림), 사건 선택·묶음 펼침은 바꿔 쓴다(replace).
//  - [지도에서 보기]는 시장 전체 지도에 ?select=node:<사건>&focus=<사건>&hops=1 로 사건과 연결 기업을 강조하고,
//    지도 쪽 복귀 링크(state.returnTo)와 브라우저 뒤로 가기 모두 이 주소로 돌아온다. 스크롤 위치는 떠날 때 저장해 내용이
//    준비되면 되돌린다. 돌아오면 선택 사건을 다시 조회해 없어졌으면 선택을 풀고 알린다.
// 복귀 링크: 들어올 때 받은 location.state.from(지도·내 종목·브리핑), 없으면 지도(/).
import { ArrowLeft, Building2, FileText, Map as MapIcon, Zap } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { ApiError, type Schemas } from "@/api/client";
import { useCompany, useCompanyEvents, useEvent } from "@/api/queries";
import { CompanyHeader } from "@/components/domain/company-header";
import { DisclaimerNote } from "@/components/domain/status-labels";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SkeletonLines } from "@/components/ui/feedback";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { CompanyDocuments } from "@/features/company-documents";
import { CompanyHolding } from "@/features/company-holding";
import { CompanyMetrics } from "@/features/company-metrics";
import { CompanyQuote } from "@/features/company-quote";
import { CompanyTimeline } from "@/features/company-timeline";
import { useOverlays } from "@/features/overlays";
import { parsePeriod, periodFrom, todayKst, type Period } from "@/lib/company-timeline";
import { formatEventTime } from "@/lib/labels";

type Tab = "events" | "documents" | "info";

/** 지도로 갈 때 실어 보내는 복귀 정보. 지도(main-page)의 복귀 링크가 읽는다. */
export interface CompanyReturn {
  path: string;
  label: string;
  state: { from: string; restoreScroll: true };
}

const SCROLL_KEY = "zoop:company-scroll";
// 문서를 새로 읽으면 첫 이력 항목의 key가 다시 'default'가 되므로, 이전 문서에서 저장한 그 칸은 버린다.
sessionStorage.removeItem(`${SCROLL_KEY}:default`);

function backLabel(from: string) {
  if (from.startsWith("/me/stocks")) return "내 종목으로 돌아가기";
  if (from.startsWith("/briefing")) return "브리핑으로 돌아가기";
  return "지도로 돌아가기";
}

export function CompanyPage() {
  const { id = "" } = useParams<{ id: string }>();
  return <CompanyDetailScreen key={id} companyId={id} />;
}

function CompanyDetailScreen({ companyId }: { companyId: string }) {
  const location = useLocation();
  const navigate = useNavigate();
  const toast = useToast();
  const { openChat } = useOverlays();
  const [params, setParams] = useSearchParams();
  const locationState = location.state as { from?: unknown; restoreScroll?: unknown } | null;
  const backTo = typeof locationState?.from === "string" && locationState.from.startsWith("/") ? locationState.from : "/";

  const tabParam = params.get("tab");
  const tab: Tab = tabParam === "documents" || tabParam === "info" ? tabParam : "events";
  const period = parsePeriod(params.get("period"));
  const selectedId = params.get("event");
  const openGroups = new Set((params.get("open") ?? "").split(",").filter(Boolean));
  const [today] = useState(todayKst);

  const company = useCompany(companyId);
  const events = useCompanyEvents(companyId, periodFrom(period, today));
  const selectedEvent = useEvent(selectedId ?? undefined, { revalidate: true });

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
      p.delete("event");
      p.delete("open");
    }, false);
  };
  const selectEvent = (eventId: string | null) => update((p) => (eventId ? p.set("event", eventId) : p.delete("event")), true);
  const toggleGroup = (key: string) =>
    update((p) => {
      const open = new Set(openGroups);
      if (open.has(key)) open.delete(key);
      else open.add(key);
      if (open.size > 0) p.set("open", [...open].join(","));
      else p.delete("open");
    }, true);
  const openGroupsFor = (keys: string[]) =>
    update((p) => {
      const open = new Set([...openGroups, ...keys]);
      p.set("open", [...open].join(","));
    }, true);

  // 선택 사건 확인: 다시 조회해 없어졌거나 이 기간 목록에 없으면 선택을 풀고 알린다.
  const missing =
    selectedId !== null &&
    ((selectedEvent.error instanceof ApiError && selectedEvent.error.status === 404) ||
      (events.isSuccess && ![...events.data.items, ...events.data.unknownTimeItems].some((e) => e.id === selectedId)));
  useEffect(() => {
    if (!missing) return;
    selectEvent(null);
    toast({ title: "선택했던 사건을 지금은 볼 수 없어 선택을 풀었어요", tone: "warning" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [missing]);

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
  const ready =
    settled(company) &&
    (tab !== "events" || (settled(events) && (selectedId === null || settled(selectedEvent))));
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
      <Page backTo={backTo}>
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
    const returnTo: CompanyReturn = { path: url, label: companyName, state: { from: backTo, restoreScroll: true } };
    navigate(`/?mode=all&select=${encodeURIComponent(`node:${event.id}`)}&focus=${encodeURIComponent(event.id)}&hops=1`, { state: { returnTo } });
  };
  const ask = (event: Schemas["EventDetail"]) =>
    openChat({
      targets: [
        { id: companyId, kind: "company", label: companyName },
        {
          id: event.id,
          kind: "issue",
          label: event.title,
          detail: [event.timePrecision !== "unknown" && formatEventTime(event.eventTime, event.timePrecision), `근거 ${event.evidenceIds.length}건`]
            .filter(Boolean)
            .join(" · "),
        },
      ],
    });

  return (
    <Page backTo={backTo}>
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
            period={period}
            today={today}
            onPeriodChange={setPeriod}
            selectedId={selectedId}
            onSelect={selectEvent}
            openGroups={openGroups}
            onToggleGroup={toggleGroup}
            onShowOnMap={showOnMap}
            onAsk={ask}
            onOpenGroups={openGroupsFor}
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

function Page({ backTo, children }: { backTo: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 px-4 py-4 md:px-6 md:py-6">
      <Button variant="ghost" size="sm" asChild className="-ml-3 w-fit">
        <Link to={backTo}>
          <ArrowLeft aria-hidden="true" />
          {backLabel(backTo)}
        </Link>
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
