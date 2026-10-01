// UI-03 메인 지도: 데스크톱은 [내 종목 목록 | 지도 | 상세], 모바일은 그래프 기본 + 목록 전환 + 상세 시트.
// 모드는 전체(시장 전체) / 개인화(내 종목: 보유 + 관심) 두 가지(요구 17–19). 주소를 주지 않으면 회원 중 보유·관심이
// 있으면 개인화, 아니면 전체로 연다(요구 6·14).
// 모드·선택·포커스·경로·영향 경로는 주소(?mode=&select=&focus=&hops=&path=&impact=)에 담는다. 모드 전환과 포커스·경로·영향 경로
// 진입·변경·해제는 이력에 쌓고(push, 뒤로 가기로 복귀), 선택은 바꿔 쓴다(replace). 포커스·경로·영향 경로는 함께 두지 않는다.
// 비회원이 잠긴 개인화 모드를 누르면 그 모드 주소로 이동해 로그인 안내를 보여준다(요구 51, 뒤로가기로 전체 복귀).
// 사이드바에서 지도에 있는 기업을 고르면 그 노드를 선택하고 카메라를 그 기업 중심으로 확대·이동한다.
// 데스크톱 사이드바(내 종목)는 도구 막대의 [내 종목]으로 접고 펼친다(넓은 화면은 펼침이 기본, 고른 값은 기억). 접으면 지도가 그 폭을 쓴다.
// 지도 복귀(FS044): 떠날 때 주소·카메라·범례 필터·보기를 저장한다(기업 상세 [그래프로 복귀]용 진입 그래프 + 이 이력 항목).
// 돌아오면 [그래프로 복귀]가 넘긴 state.graphRestore, 없으면 브라우저 뒤로 가기로 돌아온 이력 항목의 저장값으로 복원한다.
// 튜토리얼(요구 15·16): 튜토리얼을 마치지 않은 회원·비회원, 또는 계정 메뉴의 [튜토리얼 다시 보기](?tour=1)에서
// 지도 위 단계형 안내를 띄운다. 데스크톱은 왼쪽 목록 자리, 모바일은 지도 위(문서 흐름 안)에 놓는다.
import { ArrowLeft, PanelLeftClose, PanelLeftOpen, Star, Wallet } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import type { Schemas } from "@/api/client";
import type { CompanyReturn } from "./company-page";
import { useBriefingGraphBasis, useCompanies, useGraph, useLogout, usePortfolio, useSession, useSettings } from "@/api/queries";
import { CompanyMark } from "@/components/domain/company-mark";
import type { CenterRequest, GraphSelection } from "@/components/domain/graph-canvas";
import type { Viewport } from "@/components/domain/graph-layout";
import { GraphModeSwitch, MarkRing } from "@/components/domain/graph-legend";
import { WatchToggle } from "@/components/domain/watch-toggle";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingBlock, Skeleton, SkeletonLines, SkeletonRows } from "@/components/ui/feedback";
import { ListRow } from "@/components/ui/list-row";
import { SectionHeader } from "@/components/ui/section-header";
import { GraphExplorer, type ExplorerView } from "@/features/graph-explorer";
import { GraphTutorialPanel, GraphTutorialSheetBar, useGraphTutorial } from "@/features/graph-tutorial";
import { BriefingGraphBasisBar, BriefingGraphGate } from "@/features/briefing-graph-basis";
import { parsePathParam } from "@/lib/graph-path";
import { saveGraphEntry, type GraphEntry, type GraphRestoreState } from "@/lib/graph-entry";
import { ISOLATED_BUNDLE_ID, type GraphFocus, type LegendKey } from "@/lib/graph-view";
import { emptyReasonMessage, modeLabel, type GraphMode } from "@/lib/labels";
import { useMediaQuery } from "@/lib/theme";
import { track, useScreenView } from "@/lib/track";

const guestLockedModes: GraphMode[] = ["personal"];

/** 브라우저 이력 항목(location.key)별 지도 상태: 뒤로 가기로 메인 지도에 돌아왔을 때 복원한다(같은 탭 세션 동안). */
const historyKey = (key: string) => `zoop:graph-view:${key}`;
function readHistoryEntry(key: string): GraphEntry | null {
  try {
    const raw = sessionStorage.getItem(historyKey(key));
    return raw ? (JSON.parse(raw) as GraphEntry) : null;
  } catch {
    return null;
  }
}

/** 사이드바를 접었는지(사용자가 고른 값). 없으면 화면 폭으로 정한다. */
const SIDEBAR_KEY = "zoop:sidebar-open";
function readSidebarPref(): boolean | null {
  try {
    const raw = localStorage.getItem(SIDEBAR_KEY);
    return raw === null ? null : raw === "1";
  } catch {
    return null;
  }
}

export function MainPage() {
  const session = useSession();
  const viewId = useScreenView("main");
  const isGuest = session.data?.kind !== "member";
  const settings = useSettings(!isGuest);
  const portfolio = usePortfolio(!isGuest);
  const [params, setParams] = useSearchParams();
  const isMobile = useMediaQuery("(max-width: 768px)");
  const wide = useMediaQuery("(min-width: 1600px)");
  const location = useLocation();
  // 지도 복귀(FS044): [그래프로 복귀]가 넘긴 상태 > 이 이력 항목에 저장한 상태 > 없음(화면 맞춤)
  const [restore] = useState(() => (location.state as Partial<GraphRestoreState> | null)?.graphRestore ?? readHistoryEntry(location.key));
  const [view, setView] = useState<ExplorerView>(restore?.view ?? "graph");
  const [hidden, setHidden] = useState<ReadonlySet<LegendKey>>(() => new Set((restore?.hidden ?? []) as LegendKey[]));
  const cameraRef = useRef<Viewport | null>(restore?.camera ?? null);
  const [center, setCenter] = useState<CenterRequest | null>(null);
  const [sidebarPref, setSidebarPref] = useState(readSidebarPref);
  const sidebarOpen = sidebarPref ?? wide;
  const navigate = useNavigate();
  const logout = useLogout();
  // 기업 상세 [지도에서 보기]로 왔으면 그 상세(기간·선택 사건·스크롤)로 돌아가는 링크를 둔다. 지도 안에서 주소가 바뀌어도 유지한다.
  const [returnTo] = useState(() => (location.state as { returnTo?: CompanyReturn } | null)?.returnTo ?? null);

  // 떠날 때(언마운트) 마지막 상태를 저장한다. 렌더마다 최신 값을 ref에 둔다.
  const leaveRef = useRef({ url: "", key: "", view, hidden });
  leaveRef.current = { url: location.pathname + location.search, key: location.key, view, hidden };
  useEffect(
    () => () => {
      const { url, key, view: lastView, hidden: lastHidden } = leaveRef.current;
      const entry: GraphEntry = { url, camera: cameraRef.current ?? undefined, hidden: [...lastHidden], view: lastView };
      saveGraphEntry(entry);
      try {
        sessionStorage.setItem(historyKey(key), JSON.stringify(entry));
      } catch {
        // 저장소를 쓸 수 없으면 뒤로 가기는 주소에 담긴 상태(모드·선택·포커스·경로)만 복원한다.
      }
    },
    [],
  );
  const toggleSidebar = () => {
    const next = !sidebarOpen;
    setSidebarPref(next);
    try {
      localStorage.setItem(SIDEBAR_KEY, next ? "1" : "0");
    } catch {
      // 기억하지 못해도 이번 화면에서는 바뀐다.
    }
  };

  // FS032: ?round=<브리핑 회차 id>면 그 회차를 발행할 당시의 전체 지도다. 개인화·튜토리얼·내 종목 목록은 현재 자료라 쓰지 않는다.
  const round = params.get("round");
  const basis = useBriefingGraphBasis(round);
  const roundReady = round === null || basis.data?.status === "available";
  const modeParam = params.get("mode");
  const requested: GraphMode | null = round ? "all" : modeParam === "all" || modeParam === "personal" ? modeParam : null;
  const locked = isGuest && requested === "personal";
  const watchCount = settings.data?.watchlistIds.length ?? 0;
  const holdingCount = portfolio.data?.holdings.length ?? 0;
  // 기본 모드는 회원의 보유·관심을 알아야 정할 수 있다(설정·계좌 조회가 끝날 때까지 기다린다. 실패하면 전체).
  const personalKnown = (settings.isSuccess || settings.isError) && (portfolio.isSuccess || portfolio.isError);
  const mode: GraphMode = locked ? "personal" : isGuest ? "all" : (requested ?? (watchCount + holdingCount > 0 ? "personal" : "all"));
  const graph = useGraph(mode, session.isSuccess && roundReady && !locked && (isGuest || requested !== null || personalKnown));

  const selectParam = params.get("select");
  const selection: GraphSelection | null = selectParam
    ? { kind: selectParam.startsWith("edge:") ? "edge" : "node", id: selectParam.replace(/^(edge|node):/, "") }
    : null;

  const focusParam = params.get("focus");
  const focus: GraphFocus | null = focusParam ? { id: focusParam, hops: params.get("hops") === "2" ? 2 : 1 } : null;
  const setFocus = (next: GraphFocus | null, options?: { clearSelection?: boolean }) =>
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      if (next) {
        p.set("focus", next.id);
        p.set("hops", String(next.hops));
        p.delete("path");
        p.delete("impact");
      } else {
        p.delete("focus");
        p.delete("hops");
      }
      if (options?.clearSelection) p.delete("select");
      return p;
    });

  const path = parsePathParam(params.get("path"));
  /** 경로 진입은 포커스를 빠져나오고 선택을 지워 상세에 경로 단계가 보이게 한다. */
  const setPath = (next: [string, string] | null) =>
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      if (next) {
        p.set("path", next.join(","));
        p.delete("focus");
        p.delete("hops");
        p.delete("select");
        p.delete("impact");
      } else {
        p.delete("path");
      }
      return p;
    });

  const impact = parsePathParam(params.get("impact"));
  /** 영향 경로(FS022): 기업 패널의 관련 이슈에서 진입한다. 그 기업 선택은 유지하고 포커스·경로에서 나온다.
   *  나갈 때 select를 주면 그 대상을 함께 고른다(주소를 한 번에 바꾼다). */
  const setImpact = (next: [string, string] | null, select?: GraphSelection) =>
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      if (next) {
        p.set("impact", next.join(","));
        p.set("select", `node:${next[0]}`);
        p.delete("focus");
        p.delete("hops");
        p.delete("path");
      } else {
        p.delete("impact");
      }
      if (select) p.set("select", `${select.kind}:${select.id}`);
      return p;
    });

  const setSelection = (next: GraphSelection | null) => {
    if (next && next.id !== ISOLATED_BUNDLE_ID) track({ type: next.kind === "edge" ? "graph_edge_select" : "graph_node_select", targetId: next.id, viewId });
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        if (next) p.set("select", `${next.kind}:${next.id}`);
        else p.delete("select");
        // 지도에서 다른 대상을 고르면 영향 경로 보기는 끝난다.
        p.delete("impact");
        return p;
      },
      { replace: true },
    );
  };

  const setMode = (next: GraphMode) => {
    if (next === mode) return;
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      p.set("mode", next);
      p.delete("select");
      p.delete("focus");
      p.delete("hops");
      p.delete("path");
      p.delete("impact");
      return p;
    });
  };

  /** 사이드바 선택: 그 기업을 고르고 포커스·경로를 풀어 전체 배치에서 그 기업 중심으로 카메라를 옮긴다. */
  const pickCompany = (id: string) => {
    track({ type: "graph_node_select", targetId: id, viewId });
    const leavesMode = params.has("focus") || params.has("path") || params.has("impact");
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        p.set("select", `node:${id}`);
        p.delete("focus");
        p.delete("hops");
        p.delete("path");
        p.delete("impact");
        return p;
      },
      { replace: !leavesMode },
    );
    setCenter((prev) => ({ id, seq: (prev?.seq ?? 0) + 1 }));
  };

  /** 회차 기준 그래프에서 현재 그래프로: 회차만 풀고 선택·포커스는 그대로 둔다(현재 그래프에 없는 대상은 지도가 알아서 해제한다). 뒤로 가기로 회차 기준 그래프에 돌아온다. */
  const showCurrent = () =>
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      p.delete("round");
      p.set("mode", "all");
      return p;
    });

  const tutorialOpen = Boolean(!round && session.data && (params.get("tour") === "1" || session.data.setup?.tutorialCompleted === false));
  const closeTutorial = () =>
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        p.delete("tour");
        return p;
      },
      { replace: true },
    );
  // 튜토리얼은 지도가 그려졌을 때만. 모바일 상세 시트가 열리면 안내를 시트 안으로 옮기고(지도 위 패널은 시트 뒤),
  // 단계 알림은 시트 쪽만 읽는다.
  const showTutorial = tutorialOpen && !locked && graph.isSuccess && graph.data.nodes.length > 0;
  const tutorial = useGraphTutorial(showTutorial, closeTutorial, isGuest, () => goToLogin());
  const sheetOpen = isMobile && (selection !== null || path !== null || impact !== null);
  const hasSidebar = !isMobile && !locked && !showTutorial && !round;
  const toolbar = (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {hasSidebar && (
        // 상단 내비게이션 [내 종목](페이지)·모드 [내 종목]과 이름이 겹치지 않게 '목록'을 붙인다(보이는 글자는 이름 안에 그대로).
        <Button variant="ghost" size="sm" aria-label="내 종목 목록" aria-expanded={sidebarOpen} aria-controls="main-sidebar" onClick={toggleSidebar} className="-ml-2">
          {sidebarOpen ? <PanelLeftClose aria-hidden="true" /> : <PanelLeftOpen aria-hidden="true" />}
          내 종목
        </Button>
      )}
      {returnTo && (
        <Button variant="ghost" size="sm" asChild className="-ml-3">
          <Link to={returnTo.path} state={returnTo.state}>
            <ArrowLeft aria-hidden="true" />
            {returnTo.label} 상세로 돌아가기
          </Link>
        </Button>
      )}
      {!round && (
        <>
          <GraphModeSwitch
            value={mode}
            onValueChange={setMode}
            lockedModes={isGuest ? guestLockedModes : []}
            fill={isMobile}
            className={isMobile ? "w-full" : undefined}
          />
          {mode === "personal" && !isGuest && personalKnown && watchCount + holdingCount > 0 && (
            <PersonalBasis holdingCount={holdingCount} watchCount={watchCount} />
          )}
        </>
      )}
    </div>
  );

  const goToLogin = () => logout.mutate(undefined, { onSettled: () => navigate("/login") });

  let content;
  if (round && !roundReady) {
    content = <BriefingGraphGate query={basis} onShowCurrent={showCurrent} />;
  } else if (locked) {
    content = (
      <>
        {toolbar}
        <EmptyState
          title="로그인하면 내 종목 지도를 볼 수 있어요."
          action={
            <>
              <Button onClick={goToLogin} loading={logout.isPending}>
                로그인
              </Button>
              <Button variant="ghost" onClick={() => setMode("all")}>
                시장 전체 지도 보기
              </Button>
            </>
          }
        />
      </>
    );
  } else if (graph.isPending) {
    content = (
      <>
        {toolbar}
        {view === "list" ? (
          <SkeletonRows count={4} label="지도를 불러오고 있어요" />
        ) : (
          <LoadingBlock label="지도를 불러오고 있어요" className="flex min-h-[360px] flex-1">
            <Skeleton className="flex-1 rounded-none" />
          </LoadingBlock>
        )}
      </>
    );
  } else if (graph.isError) {
    content = (
      <>
        {toolbar}
        <ErrorState error={graph.error} title="지도를 불러오지 못했어요" onRetry={() => void graph.refetch()} />
      </>
    );
  } else if (graph.data.nodes.length === 0) {
    content = (
      <>
        {toolbar}
        <MapEmptyState reason={graph.data.metadata.emptyReason} mode={mode} onMarket={() => setMode("all")} />
      </>
    );
  } else {
    content = (
      <GraphExplorer
        graph={graph.data}
        mapName={round ? "브리핑 회차 기준 지도" : `${modeLabel[mode]} 지도`}
        selection={selection}
        onSelectionChange={setSelection}
        view={view}
        onViewChange={setView}
        focus={focus}
        onFocusChange={setFocus}
        path={path}
        onPathChange={setPath}
        impact={impact}
        onImpactChange={setImpact}
        hidden={hidden}
        onHiddenChange={setHidden}
        centerOn={center}
        initialCamera={restore?.camera ?? null}
        onCameraIdle={(viewport) => void (cameraRef.current = viewport)}
        sheetTop={showTutorial ? <GraphTutorialSheetBar tutorial={tutorial} onCloseSheet={() => setSelection(null)} /> : undefined}
        loading={graph.isPlaceholderData}
        toolbar={toolbar}
        className="flex-1"
      />
    );
  }

  return (
    <div className="mx-auto flex h-[calc(100dvh-3rem-1px-56px-env(safe-area-inset-bottom))] min-h-0 w-full flex-none px-4 py-3 md:h-[calc(100dvh-3.5rem-1px)] md:px-6 md:py-4">
      <h1 className="sr-only">{round ? "브리핑 회차 기준" : modeLabel[mode]} 지도</h1>
      {!isMobile && showTutorial && <GraphTutorialPanel tutorial={tutorial} className="mr-4 w-72 shrink-0 self-start" />}
      {hasSidebar && sidebarOpen && (
        <Sidebar
          isGuest={isGuest}
          settings={settings.data}
          graphNodes={graph.data?.nodes ?? []}
          selectedId={selection?.kind === "node" ? selection.id : null}
          onPick={pickCompany}
          onLogin={goToLogin}
        />
      )}
      <section aria-label="관계 지도" className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
        {isMobile && showTutorial && <GraphTutorialPanel tutorial={tutorial} live={!sheetOpen} className="shrink-0 p-3" />}
        {round && basis.data?.status === "available" && (
          <BriefingGraphBasisBar basis={basis.data} onShowCurrent={showCurrent} className="shrink-0" />
        )}
        {content}
      </section>
    </div>
  );
}

/** 개인화 지도의 기준: 보유가 없으면 관심 종목만으로 만든다는 것을 함께 보인다. */
function PersonalBasis({ holdingCount, watchCount }: { holdingCount: number; watchCount: number }) {
  return (
    <p className="flex items-center gap-2 text-sm text-text-secondary tabular-nums">
      {holdingCount > 0 && (
        <span className="flex items-center gap-1">
          <MarkRing kind="holding" />
          보유 {holdingCount}
        </span>
      )}
      {watchCount > 0 && (
        <span className="flex items-center gap-1">
          <MarkRing kind="watch" />
          관심 {watchCount}
        </span>
      )}
      <span>{holdingCount === 0 ? "기준 · 보유 종목 없음" : "기준"}</span>
    </p>
  );
}

function MapEmptyState({ reason, mode, onMarket }: { reason: string | null; mode: GraphMode; onMarket: () => void }) {
  const message = emptyReasonMessage(reason, mode);
  if (reason === "no_personal_stocks") {
    return (
      <EmptyState
        title={message.title}
        description={message.body}
        action={
          <>
            <Button asChild>
              <Link to="/me/stocks">관심 종목 고르기</Link>
            </Button>
            <Button variant="ghost" onClick={onMarket}>
              시장 전체 지도 보기
            </Button>
          </>
        }
      />
    );
  }
  return (
    <EmptyState
      title={message.title}
      description={message.body}
      action={
        mode !== "all" ? (
          <Button variant="ghost" onClick={onMarket}>
            시장 전체 지도 보기
          </Button>
        ) : undefined
      }
    />
  );
}

function Sidebar({
  isGuest,
  settings,
  graphNodes,
  selectedId,
  onPick,
  onLogin,
}: {
  isGuest: boolean;
  settings: Schemas["SettingsResponse"] | undefined;
  graphNodes: Schemas["GraphNode"][];
  selectedId: string | null;
  onPick: (id: string) => void;
  onLogin: () => void;
}) {
  const location = useLocation();
  const portfolio = usePortfolio(!isGuest);
  const watchIds = settings?.watchlistIds ?? [];
  const watchQueries = useCompanies(watchIds);
  const from = { from: location.pathname + location.search };
  const watchSectionRef = useRef<HTMLElement>(null);
  const previousWatchIds = useRef(watchIds);
  // 관심을 해제하면 그 행이 목록에서 사라져 포커스가 문서 처음으로 떨어진다. 같은 자리의 다음 행 별 버튼
  // (없으면 바로 위 행, 목록이 비면 [관심 종목 고르기])으로 옮긴다. 다른 곳에 포커스가 있으면 건드리지 않는다.
  useLayoutEffect(() => {
    const previous = previousWatchIds.current;
    previousWatchIds.current = watchIds;
    const section = watchSectionRef.current;
    if (!section || watchIds.length >= previous.length) return;
    if (document.activeElement && document.activeElement !== document.body) return;
    const removedAt = previous.findIndex((id) => !watchIds.includes(id));
    // 행마다 마지막 칸이 별 버튼이다(첫 칸 행 버튼도 aria-pressed를 쓰므로 속성으로 고르지 않는다).
    const toggles = [...section.querySelectorAll("li")].map((li) => li.lastElementChild).filter((el): el is HTMLButtonElement => el instanceof HTMLButtonElement);
    const next = toggles[Math.min(Math.max(removedAt, 0), toggles.length - 1)] ?? section.querySelector<HTMLElement>("a[href], button");
    next?.focus();
  }, [watchIds]);

  // 지도에 있는 종목은 지도에서 고르고(그 기업 중심으로 이동), 없는 종목은 기업 상세로 간다.
  // 행 끝 테두리 견본은 지도 노드의 보유(실선)·관심(점선) 표시와 같다. 행 옆 별 버튼은 관심 등록·해제(FS027, 누르면 바로 저장).
  const row = (kind: "holding" | "watch", id: string, name: string, description?: string) => {
    const node = graphNodes.find((n) => n.id === id);
    const leading = <CompanyMark id={id} name={name} brandColor={node?.brandColor} logoUrl={node?.logoUrl} />;
    return (
      <li key={id} className="flex items-center">
        {node ? (
          <ListRow className="min-w-0 flex-1" leading={leading} title={name} description={description} trailing={<MarkRing kind={kind} />} selected={selectedId === id} onClick={() => onPick(id)} />
        ) : (
          <ListRow className="min-w-0 flex-1" leading={leading} title={name} description={description} to={`/companies/${encodeURIComponent(id)}`} state={from} />
        )}
        <WatchToggle companyId={id} companyName={name} variant="icon" className="shrink-0" />
      </li>
    );
  };

  return (
    <aside id="main-sidebar" aria-label="내 종목" className="mr-4 flex w-60 shrink-0 flex-col overflow-y-auto border-r border-border-subtle pr-2">
      {isGuest ? (
        <section aria-labelledby="side-guest" className="flex flex-col gap-3">
          <SectionHeader id="side-guest" title="내 종목" className="pt-0" />
          <p className="px-4 text-base text-text-secondary">로그인하면 내 종목 지도를 볼 수 있어요.</p>
          <Button variant="secondary" className="mx-4 w-fit" onClick={onLogin}>
            로그인
          </Button>
        </section>
      ) : (
        <>
          <section aria-labelledby="side-holdings">
            <SectionHeader id="side-holdings" icon={Wallet} title="보유 종목" className="pt-0" />
            {portfolio.isPending && (
              <div className="px-4">
                <SkeletonLines lines={2} label="보유 종목을 불러오고 있어요" />
              </div>
            )}
            {portfolio.isError && (
              <ErrorState className="px-4" error={portfolio.error} title="보유 종목을 불러오지 못했어요" onRetry={() => void portfolio.refetch()} compact />
            )}
            {portfolio.data &&
              (portfolio.data.holdings.length === 0 ? (
                <div className="flex flex-col items-start gap-1 px-4 py-2">
                  <p className="text-base text-text-secondary">연결된 가상 계좌가 없어요.</p>
                  <Button variant="link" asChild>
                    <Link to="/me/stocks">가상 계좌 연결하기</Link>
                  </Button>
                </div>
              ) : (
                <ul>{portfolio.data.holdings.map((h) => row("holding", h.companyId, h.name, `원가 비중 ${Math.round(h.weight * 100)}%`))}</ul>
              ))}
          </section>
          <section ref={watchSectionRef} aria-labelledby="side-watch">
            <SectionHeader id="side-watch" icon={Star} title="관심 종목" />
            {watchIds.length === 0 ? (
              <div className="flex flex-col items-start gap-1 px-4 py-2">
                <p className="text-base text-text-secondary">고른 관심 종목이 없어요.</p>
                <Button variant="link" asChild>
                  <Link to="/me/stocks">관심 종목 고르기</Link>
                </Button>
              </div>
            ) : (
              <ul>
                {watchIds.map((id, i) => {
                  const q = watchQueries[i];
                  if (!q || q.isPending) {
                    return (
                      <li key={id} className="px-4 py-3">
                        <Skeleton className="h-5 w-24" />
                      </li>
                    );
                  }
                  if (q.isError) {
                    return (
                      <li key={id} className="px-4 py-3 text-sm text-error">
                        종목 정보를 불러오지 못했어요
                      </li>
                    );
                  }
                  return row("watch", id, q.data.name, q.data.ticker ?? undefined);
                })}
              </ul>
            )}
          </section>
        </>
      )}
    </aside>
  );
}
