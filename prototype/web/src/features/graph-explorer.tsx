// 지도(그래프 또는 목록) + 상세. 메인 화면과 온보딩 튜토리얼이 함께 쓴다.
// - 데스크톱: 가운데 지도, 오른쪽 평탄한 상세 패널(항상 자리를 차지해 캔버스 크기가 흔들리지 않는다)
// - 모바일: 그래프가 기본(끌기·핀치·탭), 목록은 전환. 상세는 바텀시트(처음 절반, 위로 끌면 크게)
// - 범례는 Neo4j식 라벨 칩(종류 + 개수)으로 캔버스 위에 한 줄. 칩을 누르면 그 종류를 숨기거나 보인다(G5).
// - 그래프에서는 연결 없는 사건을 묶음 하나로 모은다(G1). 목록 보기는 모든 사건을 그대로 보여준다.
// - 포커스 모드(G2): 상세의 [이 노드 중심으로 보기] → 그래프 위 FocusBar. 상태는 부모가 주소에 둔다.
// - 경로 모드(G6): 기업 상세의 [다른 기업과의 연결 보기] → 그래프 위 PathBar + 상세에 단계 목록. 포커스와 함께 두지 않는다.
// - 지도에서 연 근거 창의 [지도에서 보기]를 누르면 그 근거의 연결선을 강조한다(G4).
import { CircleHelp, List, LoaderCircle, MousePointerClick, Network, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router";
import type { Schemas } from "@/api/client";
import { useEventsByIds } from "@/api/queries";
import { FocusBar } from "@/components/domain/focus-bar";
import { GraphCanvas, type CenterRequest, type GraphSelection } from "@/components/domain/graph-canvas";
import { GraphLegend } from "@/components/domain/graph-legend";
import { PathBar } from "@/components/domain/path-bar";
import { RelationList } from "@/components/domain/relation-list";
import { BottomSheet } from "@/components/ui/bottom-sheet";
import { Button } from "@/components/ui/button";
import { Popover } from "@/components/ui/popover";
import { Segmented } from "@/components/ui/segmented";
import { shortestPath } from "@/lib/graph-path";
import { ISOLATED_BUNDLE_ID, isolatedBundleLabel, isolatedIssues, type GraphFocus, type LegendKey } from "@/lib/graph-view";
import { useMediaQuery } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { NodeDetail, selectionTitle } from "./node-panel";
import { useOverlays, type EvidenceRequest } from "./overlays";
import { PathDetail } from "./path-panel";

export type ExplorerView = "graph" | "list";

interface GraphExplorerProps {
  graph: Schemas["GraphResponse"];
  /** 스크린리더용 지도 이름 (예: "관심 종목 지도") */
  mapName: string;
  selection: GraphSelection | null;
  onSelectionChange: (selection: GraphSelection | null) => void;
  view: ExplorerView;
  onViewChange: (view: ExplorerView) => void;
  /** 새 모드의 지도를 받아오는 중(이전 지도를 그대로 보여주는 동안) */
  loading?: boolean;
  toolbar?: ReactNode;
  /** 포커스 모드(G2). onFocusChange가 없으면 포커스 진입 동작을 두지 않는다. */
  focus?: GraphFocus | null;
  /** clearSelection: 모바일에서 상세 시트를 닫고 포커스한 지도를 보인다(주소를 한 번에 바꾼다). */
  onFocusChange?: (focus: GraphFocus | null, options?: { clearSelection?: boolean }) => void;
  /** 경로 모드(G6): 두 기업 id. onPathChange가 없으면 경로 진입 동작을 두지 않는다. */
  path?: [string, string] | null;
  onPathChange?: (path: [string, string] | null) => void;
  /** 사이드바 기업 선택: 그 기업을 가운데로 확대·이동한다. */
  centerOn?: CenterRequest | null;
  /** 모바일 상세 시트 안쪽 맨 위(헤더 아래)에 둘 내용(튜토리얼 안내) */
  sheetTop?: ReactNode;
  className?: string;
}

export function GraphExplorer({
  graph,
  mapName,
  selection,
  onSelectionChange,
  view,
  onViewChange,
  loading,
  toolbar,
  focus,
  onFocusChange,
  path,
  onPathChange,
  centerOn,
  sheetTop,
  className,
}: GraphExplorerProps) {
  const isMobile = useMediaQuery("(max-width: 768px)");
  const location = useLocation();
  const { openEvidence, mapHighlight } = useOverlays();
  const panelHeadingRef = useRef<HTMLHeadingElement>(null);
  const focusBarRef = useRef<HTMLDivElement>(null);
  const [hidden, setHidden] = useState<ReadonlySet<LegendKey>>(() => new Set());

  // 경로: 두 기업이 지금 지도에 있어야 한다. 최단 경로는 지도 데이터 전체(범례로 숨긴 것 포함)에서 찾는다.
  const pathFrom = path ? graph.nodes.find((n) => n.id === path[0] && n.kind === "company") : undefined;
  const pathTo = path ? graph.nodes.find((n) => n.id === path[1] && n.kind === "company") : undefined;
  const pathKey = pathFrom && pathTo ? `${pathFrom.id},${pathTo.id}` : null;
  const route = useMemo(
    () => (pathFrom && pathTo ? shortestPath(graph.nodes, graph.edges, pathFrom.id, pathTo.id) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [graph, pathKey],
  );
  // 모바일: 경로가 있으면 지도를 가리지 않도록 단계 시트는 경로 바의 [경로 단계 보기]로 연다(연 경로의 키).
  // 이어지지 않으면 경로 바가 없으므로 안내 시트를 바로 연다.
  const [stepsOpenKey, setStepsOpenKey] = useState<string | null>(null);

  const companies = graph.nodes.filter((n) => n.kind === "company");
  const issueIds = graph.nodes.filter((n) => n.kind === "issue").map((n) => n.id);
  const isolated = isolatedIssues(graph.nodes, graph.edges);
  const centered = companies.find((n) => n.isFocus);
  const ariaLabel = [
    `${centered ? `${centered.label} 중심 ` : ""}${mapName}. 기업 ${companies.length}곳, 사건 ${issueIds.length}건, 연결선 ${graph.edges.length}개.`,
    isolated.length > 0 ? `${isolatedBundleLabel(isolated.length)}은 묶음 하나로 모았어요.` : "",
    route && pathFrom && pathTo ? `${pathFrom.label}에서 ${pathTo.label}까지 ${route.edgeIds.length}단계 경로를 강조했어요.` : "",
    "같은 내용을 목록 보기에서 확인할 수 있어요.",
  ].filter(Boolean).join(" ");

  // 포커스는 연결이 있는 노드만(묶음에 들어간 사건이나 지금 지도에 없는 노드면 무시). 경로 모드면 포커스를 두지 않는다.
  const focusNode = focus && !pathKey ? graph.nodes.find((n) => n.id === focus.id && !isolated.some((i) => i.id === n.id)) : undefined;
  const validFocus = focus && focusNode ? focus : null;

  // 목록의 사건 행마다 [근거 N건]을 바로 열 수 있도록 사건 상세(근거 id)를 불러온다. 전체 연결 지도는 사건이 많으므로 목록을 볼 때만.
  const events = useEventsByIds(view === "list" ? issueIds : []);
  const evidenceByIssue = new Map(events.flatMap((q) => (q.data ? [[q.data.id, q.data.evidenceIds] as const] : [])));

  // 선택이 가리키는 요소가 지금 데이터에 없으면(모드 전환 등) 상세를 열지 않는다.
  const validSelection =
    selection &&
    (selection.id === ISOLATED_BUNDLE_ID
      ? isolated.length > 0
      : selection.kind === "node"
        ? graph.nodes.some((n) => n.id === selection.id)
        : graph.edges.some((e) => e.id === selection.id))
      ? selection
      : null;
  const linkState = { from: location.pathname + location.search };

  // 그래프 보기에서 연 근거 창은 인용을 지도에서 강조할 수 있다(사건 id는 해당 연결선이 없을 때 대신 강조).
  const showEvidence = (request: EvidenceRequest) => {
    openEvidence(view === "graph" ? { ...request, map: { issueId: request.eventId } } : request);
  };

  // 상세에서 포커스로 들어가면 새로 나타난 포커스 바로 키보드 포커스를 옮긴다(데스크톱).
  const barFocusPendingRef = useRef(false);
  const enterFocus = (id: string) => {
    barFocusPendingRef.current = !isMobile;
    onFocusChange?.({ id, hops: validFocus?.hops ?? 1 }, { clearSelection: isMobile });
  };
  useEffect(() => {
    if (!validFocus || !barFocusPendingRef.current) return;
    barFocusPendingRef.current = false;
    focusBarRef.current?.focus();
  }, [validFocus?.id]);
  const exitFocus = () => {
    onFocusChange?.(null);
    // 나가기 버튼이 사라지므로 상세 제목(없으면 범례)으로 포커스를 옮긴다.
    requestAnimationFrame(() => (panelHeadingRef.current ?? document.querySelector<HTMLElement>('[aria-label="그래프 범례"] button'))?.focus());
  };
  const toggleLegend = (key: LegendKey) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  // 데스크톱: 새로 고른 대상의 제목으로 포커스를 옮긴다(NFR-12). 모바일은 시트가 포커스를 가져간다.
  const selectedKey = validSelection ? `${validSelection.kind}:${validSelection.id}` : null;
  useEffect(() => {
    if (selectedKey && !isMobile) panelHeadingRef.current?.focus({ preventScroll: true });
  }, [selectedKey, isMobile]);
  // 경로를 고르면 새로 나타난 경로 제목(데스크톱 상세) 또는 경로 바(모바일)로 옮긴다.
  // 나가면 경로 제목·나가기 버튼이 사라지므로, 주소가 바뀐 뒤 상세 제목(없으면 범례)으로 옮긴다.
  const pathExitPendingRef = useRef(false);
  const pathBarRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (pathKey) {
      if (isMobile) pathBarRef.current?.focus({ preventScroll: true });
      else panelHeadingRef.current?.focus({ preventScroll: true });
    } else if (pathExitPendingRef.current) {
      pathExitPendingRef.current = false;
      (panelHeadingRef.current ?? document.querySelector<HTMLElement>('[aria-label="그래프 범례"] button'))?.focus();
    }
  }, [pathKey, isMobile]);
  const exitPath = () => {
    pathExitPendingRef.current = true;
    onPathChange?.(null);
  };

  const close = () => {
    const previous = validSelection;
    onSelectionChange(null);
    // 목록에서 고른 경우 원래 항목으로 포커스를 되돌린다.
    if (previous && !isMobile) {
      requestAnimationFrame(() => {
        // 기업 행은 행 자체가 버튼이고, 사건 행은 행(li) 안의 첫 버튼(제목)이 복귀 대상이다.
        const row = document.querySelector<HTMLElement>(`[data-selection-id="${CSS.escape(previous.id)}"]`);
        (row?.matches("button, a") ? row : row?.querySelector<HTMLElement>("button"))?.focus();
      });
    }
  };

  const detail = validSelection && (
    <NodeDetail
      selection={validSelection}
      nodes={graph.nodes}
      edges={graph.edges}
      onSelect={onSelectionChange}
      onShowEvidence={showEvidence}
      linkState={linkState}
      isolated={isolated}
      onFocusNode={onFocusChange && view === "graph" ? enterFocus : undefined}
      focusId={validFocus?.id ?? null}
      onPathTo={onPathChange && view === "graph" ? (from, to) => onPathChange([from, to]) : undefined}
    />
  );
  const pathDetail = pathFrom && pathTo && onPathChange && (
    <PathDetail
      from={pathFrom}
      path={route}
      nodes={graph.nodes}
      edges={graph.edges}
      onSelect={onSelectionChange}
      onShowEvidence={showEvidence}
      onRepick={(toId) => onPathChange([pathFrom.id, toId])}
    />
  );
  const title = validSelection ? selectionTitle(validSelection, graph.nodes, graph.edges) : pathFrom && pathTo ? `${pathFrom.label} ↔ ${pathTo.label}` : "";
  const pathSheetOpen = Boolean(pathDetail) && (!route || stepsOpenKey === pathKey);
  const viewSwitch = (
    <Segmented
      aria-label="보기 방식"
      value={view}
      onValueChange={onViewChange}
      options={[
        { value: "graph", label: <><Network aria-hidden="true" /><span className="max-md:sr-only">그래프</span></>, ariaLabel: "그래프로 보기" },
        { value: "list", label: <><List aria-hidden="true" /><span className="max-md:sr-only">목록</span></>, ariaLabel: "목록으로 보기" },
      ]}
    />
  );

  return (
    <div
      className={cn("flex min-h-0 min-w-0", className)}
      onKeyDown={(e) => {
        if (e.key === "Escape" && validSelection && !e.defaultPrevented) {
          e.stopPropagation();
          close();
        }
      }}
    >
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2 md:gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="min-w-0 max-md:w-full">{toolbar}</div>
          {!isMobile && (
            <div className="ml-auto flex items-center gap-1">
              {viewSwitch}
              <KeyboardHelp />
            </div>
          )}
        </div>
        {graph.metadata.truncated && (
          <p className="text-sm text-warning">노드가 많아 {graph.metadata.limit}개까지만 보여드려요.</p>
        )}
        {(view === "graph" || isMobile) && (
          <div className="flex min-w-0 items-center gap-2">
            {view === "graph" ? (
              <GraphLegend nodes={graph.nodes} edges={graph.edges} hidden={hidden} onToggle={toggleLegend} className="min-w-0 flex-1" />
            ) : (
              <div className="flex-1" />
            )}
            {loading && (
              <span role="status" aria-label="지도를 새로 불러오고 있어요" className="flex size-7 items-center justify-center text-text-secondary">
                <LoaderCircle className="size-4 motion-safe:animate-spin" aria-hidden="true" />
              </span>
            )}
            {isMobile && viewSwitch}
          </div>
        )}
        {/* 그래프는 목록 보기 중에도 숨겨 둔 채 유지한다(확대 배율·위치 보존). 보이게 되면 크기를 다시 재서 맞춘다. */}
        <div className={cn("relative flex min-h-0 flex-1 flex-col", view !== "graph" && "hidden")} aria-busy={loading || undefined}>
          <GraphCanvas
            nodes={graph.nodes}
            edges={graph.edges}
            selection={validSelection}
            onSelect={onSelectionChange}
            ariaLabel={ariaLabel}
            groupIsolated
            focus={validFocus}
            hidden={hidden}
            evidence={mapHighlight}
            path={route}
            centerOn={centerOn}
            className="min-h-[320px] flex-1 border border-border-subtle max-md:-mx-4 max-md:border-x-0"
          />
          {validFocus && focusNode && onFocusChange && (
            <FocusBar
              ref={focusBarRef}
              node={focusNode}
              hops={validFocus.hops}
              onHopsChange={(hops) => onFocusChange({ id: validFocus.id, hops })}
              onExit={exitFocus}
              compact={isMobile}
              className="absolute top-3 left-3 max-md:-right-1 max-md:-left-1 md:max-w-[calc(100%-24px)]"
            />
          )}
          {route && pathFrom && pathTo && onPathChange && (
            <PathBar
              ref={pathBarRef}
              from={pathFrom}
              to={pathTo}
              steps={route.edgeIds.length}
              onExit={exitPath}
              onShowSteps={isMobile ? () => setStepsOpenKey(pathKey) : undefined}
              compact={isMobile}
              className="absolute top-3 left-3 max-md:-right-1 max-md:-left-1 md:max-w-[calc(100%-24px)]"
            />
          )}
        </div>
        {view === "list" && (
          <RelationList
            nodes={graph.nodes}
            edges={graph.edges}
            selection={validSelection}
            onSelect={onSelectionChange}
            label={`${mapName}의 기업과 사건 목록`}
            evidenceByIssue={evidenceByIssue}
            onShowEvidence={(issue) => showEvidence({ title: issue.title, evidenceIds: issue.evidenceIds })}
            linkState={linkState}
            className="relative -mx-4 min-h-0 flex-1 md:mx-0"
          />
        )}
      </div>

      {isMobile ? (
        <BottomSheet
          open={Boolean(validSelection) || pathSheetOpen}
          onOpenChange={(open) => {
            if (open) return;
            if (validSelection) close();
            // 이어지지 않는 경로의 안내를 닫으면 경로 모드에서도 나간다(지도에 남는 표시가 없으므로).
            else if (route) setStepsOpenKey(null);
            else exitPath();
          }}
          title={title}
          closeLabel={validSelection ? "상세 닫기" : route ? "경로 단계 닫기" : "경로 닫기"}
          defaultSnap="half"
        >
          {sheetTop}
          <div className="-mx-4 -mt-1">{detail || pathDetail}</div>
        </BottomSheet>
      ) : (
        <aside aria-label="상세" className="ml-4 flex w-[380px] shrink-0 flex-col border-l border-border-subtle">
          {validSelection ? (
            <div key={selectedKey} className="flex min-h-0 flex-1 flex-col motion-page">
              <div className="flex items-start gap-2 py-2 pr-1 pl-4">
                <h2 ref={panelHeadingRef} tabIndex={-1} className="min-w-0 flex-1 pt-2 text-xl leading-snug font-semibold text-text-primary outline-none">
                  {title}
                </h2>
                <Button variant="ghost" size="icon" aria-label="상세 닫기" onClick={close}>
                  <X aria-hidden="true" />
                </Button>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto">{detail}</div>
            </div>
          ) : pathDetail ? (
            <div key={pathKey} className="flex min-h-0 flex-1 flex-col motion-page">
              <div className="flex items-start gap-2 py-2 pr-1 pl-4">
                <h2 ref={panelHeadingRef} tabIndex={-1} className="min-w-0 flex-1 pt-2 text-xl leading-snug font-semibold text-text-primary outline-none">
                  {title}
                </h2>
                <Button variant="ghost" size="icon" aria-label="경로 닫기" onClick={exitPath}>
                  <X aria-hidden="true" />
                </Button>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto">{pathDetail}</div>
            </div>
          ) : (
            <p className="flex items-center gap-2 px-4 pt-4 text-base text-text-secondary">
              <MousePointerClick className="size-5 shrink-0" aria-hidden="true" />
              기업이나 사건을 골라 주세요.
            </p>
          )}
        </aside>
      )}
    </div>
  );
}

function KeyboardHelp() {
  return (
    <Popover
      label="조작 도움말"
      trigger={
        <Button variant="ghost" size="icon" aria-label="조작 도움말">
          <CircleHelp aria-hidden="true" />
        </Button>
      }
    >
      <p className="font-semibold text-text-primary">지도 둘러보기</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <dt className="font-medium text-text-primary">누르기</dt>
        <dd>기업·사건·연결선 자세히 보기</dd>
        <dt className="font-medium text-text-primary">두 번 누르기</dt>
        <dd>그 대상과 이웃으로 확대</dd>
        <dt className="font-medium text-text-primary">끌기</dt>
        <dd>노드 옮기기, 빈 곳은 화면 이동</dd>
        <dt className="font-medium text-text-primary">Tab</dt>
        <dd>목록 보기의 기업·사건으로 이동</dd>
        <dt className="font-medium text-text-primary">Esc</dt>
        <dd>선택 해제</dd>
      </dl>
    </Popover>
  );
}
