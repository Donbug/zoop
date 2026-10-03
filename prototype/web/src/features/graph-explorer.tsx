// 지도(그래프 또는 목록) + 상세. 메인 화면이 쓴다.
// - 데스크톱: 지도가 가로 전체를 쓰고, 상세 패널은 고른 대상이 있을 때만 캔버스 오른쪽 위에 겹쳐 연다.
//   캔버스 크기는 패널과 관계없이 그대로이고(배치·카메라가 흔들리지 않음), 맞춤·선택 카메라는 패널에 덮이지 않은 영역을 쓴다.
//   목록 보기에서는 패널이 목록 옆에 자리를 차지한다.
// - 모바일: 그래프가 기본(끌기·핀치·탭), 목록은 전환. 상세는 바텀시트(처음 절반, 위로 끌면 크게)
// - 범례는 Neo4j식 라벨 칩(종류 + 개수). 데스크톱은 도구 막대와 같은 줄, 모바일은 캔버스 위 한 줄. 칩을 누르면 그 종류를 숨기거나 보인다(G5).
// - 그래프에서는 연결 없는 사건을 묶음 하나로 모은다(G1). 목록 보기는 모든 사건을 그대로 보여준다.
// - 포커스 모드(G2): 상세의 [이 노드 중심으로 보기] → 그래프 위 FocusBar. 상태는 부모가 주소에 둔다.
// - 경로 모드(G6): 기업 상세의 [다른 기업과의 연결 보기] → 그래프 위 PathBar + 상세에 단계 목록. 포커스와 함께 두지 않는다.
// - 영향 경로(FS022): 기업 상세의 관련 이슈 → 상세에 단계별 연결·근거, 지도에 그 경로와 함께 연결된 기업을 강조.
// - 지도에서 연 근거 창의 [지도에서 보기]를 누르면 그 근거의 연결선을 강조한다(G4).
import { CircleHelp, List, LoaderCircle, MousePointerClick, Network, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router";
import type { Schemas } from "@/api/client";
import { useEventsByIds } from "@/api/queries";
import { FocusBar } from "@/components/domain/focus-bar";
import { GraphCanvas, type CenterRequest, type GraphSelection } from "@/components/domain/graph-canvas";
import type { Viewport } from "@/components/domain/graph-layout";
import { GraphLegend } from "@/components/domain/graph-legend";
import { PathBar } from "@/components/domain/path-bar";
import { RelationList } from "@/components/domain/relation-list";
import { BottomSheet } from "@/components/ui/bottom-sheet";
import { Button } from "@/components/ui/button";
import { Popover } from "@/components/ui/popover";
import { Segmented } from "@/components/ui/segmented";
import { shortestPath } from "@/lib/graph-path";
import { ISOLATED_BUNDLE_ID, isolatedBundleLabel, isolatedIssues, type GraphFocus, type LegendKey } from "@/lib/graph-view";
import { impactPath } from "@/lib/impact-path";
import { useMediaQuery } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { ImpactDetail } from "./impact-panel";
import { NodeDetail, selectionTitle } from "./node-panel";
import { useOverlays, type EvidenceRequest } from "./overlays";
import { PathDetail } from "./path-panel";

export type ExplorerView = "graph" | "list";

/** 데스크톱 상세 패널 폭(px). 그래프 보기에서는 캔버스 오른쪽을 이만큼 덮는다. */
const PANEL_WIDTH = 380;

interface GraphExplorerProps {
  graph: Schemas["GraphResponse"];
  /** 스크린리더용 지도 이름 (예: "관심 종목 지도") */
  mapName: string;
  selection: GraphSelection | null;
  onSelectionChange: (selection: GraphSelection | null) => void;
  view: ExplorerView;
  onViewChange: (view: ExplorerView) => void;
  /** 지도를 다시 받아오는 중이면 그 안내(예: "내 종목 지도를 불러오고 있어요"). 지금 지도는 그대로 보인다. */
  loadingLabel?: string;
  toolbar?: ReactNode;
  /** false면 범례에서 보유·관심 칩을 뺀다(도구 막대에 개인화 필터가 같은 고리를 보일 때). */
  legendMarks?: boolean;
  /** 포커스 모드(G2). onFocusChange가 없으면 포커스 진입 동작을 두지 않는다. */
  focus?: GraphFocus | null;
  /** clearSelection: 모바일에서 상세 시트를 닫고 포커스한 지도를 보인다(주소를 한 번에 바꾼다). */
  onFocusChange?: (focus: GraphFocus | null, options?: { clearSelection?: boolean }) => void;
  /** 경로 모드(G6): 두 기업 id. onPathChange가 없으면 경로 진입 동작을 두지 않는다. */
  path?: [string, string] | null;
  onPathChange?: (path: [string, string] | null) => void;
  /** 영향 경로(FS022): [기업, 사건]. onImpactChange가 없으면 기업 패널의 이슈는 사건을 선택한다. */
  impact?: [string, string] | null;
  /** select를 주면 영향 경로에서 나오면서 그 대상을 고른다(주소를 한 번에 바꾼다). */
  onImpactChange?: (impact: [string, string] | null, select?: GraphSelection) => void;
  /** 범례로 끈 항목(G5). 부모가 지도 복귀(FS044)를 위해 보관한다. */
  hidden: ReadonlySet<LegendKey>;
  onHiddenChange: (hidden: ReadonlySet<LegendKey>) => void;
  /** 사이드바 기업 선택: 그 기업을 가운데로 확대·이동한다. */
  centerOn?: CenterRequest | null;
  /** 지도 복귀(FS044)·모드 복원(FS019): 다음 배치 뒤 쓸 카메라(값이 바뀌면 다시 쓴다) */
  initialCamera?: Viewport | null;
  onCameraIdle?: (viewport: Viewport) => void;
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
  loadingLabel,
  toolbar,
  legendMarks = true,
  focus,
  onFocusChange,
  path,
  onPathChange,
  impact,
  onImpactChange,
  hidden,
  onHiddenChange,
  centerOn,
  initialCamera,
  onCameraIdle,
  sheetTop,
  className,
}: GraphExplorerProps) {
  const isMobile = useMediaQuery("(max-width: 768px)");
  const location = useLocation();
  const { openEvidence, mapHighlight } = useOverlays();
  const panelHeadingRef = useRef<HTMLHeadingElement>(null);
  const focusBarRef = useRef<HTMLDivElement>(null);

  // 경로: 두 기업이 지금 지도에 있어야 한다. 최단 경로는 지도 데이터 전체(범례로 숨긴 것 포함)에서 찾는다.
  const pathFrom = path ? graph.nodes.find((n) => n.id === path[0] && n.kind === "company") : undefined;
  const pathTo = path ? graph.nodes.find((n) => n.id === path[1] && n.kind === "company") : undefined;
  const pathKey = pathFrom && pathTo ? `${pathFrom.id},${pathTo.id}` : null;
  const route = useMemo(
    () => (pathFrom && pathTo ? shortestPath(graph.nodes, graph.edges, pathFrom.id, pathTo.id) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [graph, pathKey],
  );
  // 영향 경로: 기업과 사건이 지금 지도에 있어야 한다. 경로 모드(G6)와 함께 두지 않는다.
  const impactCompany = impact && !pathKey ? graph.nodes.find((n) => n.id === impact[0] && n.kind === "company") : undefined;
  const impactIssue = impact && impactCompany ? graph.nodes.find((n) => n.id === impact[1] && n.kind === "issue") : undefined;
  const impactKey = impactCompany && impactIssue ? `${impactCompany.id},${impactIssue.id}` : null;
  const impacted = useMemo(
    () => (impactCompany && impactIssue ? impactPath(graph.nodes, graph.edges, impactCompany.id, impactIssue.id) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [graph, impactKey],
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
    impacted?.route && impactCompany && impactIssue ? `${impactCompany.label}과 사건 ${impactIssue.label}의 영향 경로를 강조했어요.` : "",
    "같은 내용을 목록 보기에서 확인할 수 있어요.",
  ].filter(Boolean).join(" ");

  // 포커스는 연결이 있는 노드만(묶음에 들어간 사건이나 지금 지도에 없는 노드면 무시). 경로 모드면 포커스를 두지 않는다.
  const focusNode = focus && !pathKey && !impactKey ? graph.nodes.find((n) => n.id === focus.id && !isolated.some((i) => i.id === n.id)) : undefined;
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
  const focusPanelOrLegend = () => (panelHeadingRef.current ?? document.querySelector<HTMLElement>('[aria-label="그래프 범례"] button'))?.focus();
  const exitFocus = () => {
    onFocusChange?.(null);
    // 나가기 버튼이 사라지므로 상세 제목(없으면 범례)으로 포커스를 옮긴다.
    requestAnimationFrame(focusPanelOrLegend);
  };
  const toggleLegend = (key: LegendKey) => {
    const next = new Set(hidden);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onHiddenChange(next);
  };

  // 데스크톱: 새로 고른 대상·영향 경로의 제목으로 포커스를 옮긴다(NFR-12). 모바일은 시트가 포커스를 가져간다.
  const selectedKey = validSelection ? `${validSelection.kind}:${validSelection.id}` : null;
  useEffect(() => {
    if ((selectedKey || impactKey) && !isMobile) panelHeadingRef.current?.focus({ preventScroll: true });
  }, [selectedKey, impactKey, isMobile]);
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
      focusPanelOrLegend();
    }
  }, [pathKey, isMobile]);
  const exitPath = () => {
    pathExitPendingRef.current = true;
    onPathChange?.(null);
  };
  const exitImpact = () => onImpactChange?.(null);

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
      onImpact={onImpactChange ? (companyId, issueId) => onImpactChange([companyId, issueId]) : undefined}
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
  const impactDetail = impacted && (
    <ImpactDetail
      key={impactKey}
      impact={impacted}
      nodes={graph.nodes}
      asOf={graph.metadata.asOf}
      onSelect={(next) => onImpactChange?.(null, next)}
      onShowEvidence={showEvidence}
    />
  );
  // 상세 영역에 보일 것: 영향 경로 > 선택 상세 > 두 기업 경로
  const panel = impactDetail
    ? { key: `impact:${impactKey}`, title: `${impactCompany!.label} · 영향 경로`, body: impactDetail, closeLabel: "영향 경로 닫기", onClose: exitImpact }
    : validSelection
      ? { key: selectedKey!, title: selectionTitle(validSelection, graph.nodes, graph.edges), body: detail, closeLabel: "상세 닫기", onClose: close }
      : pathDetail
        ? { key: `path:${pathKey}`, title: `${pathFrom!.label} ↔ ${pathTo!.label}`, body: pathDetail, closeLabel: "경로 닫기", onClose: exitPath }
        : null;
  const pathSheetOpen = Boolean(pathDetail) && (!route || stepsOpenKey === pathKey);
  // 그래프 보기의 데스크톱 상세 패널은 캔버스 위에 겹친다.
  const panelOverCanvas = !isMobile && view === "graph" && panel !== null;
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
  const legend = <GraphLegend nodes={graph.nodes} edges={graph.edges} hidden={hidden} onToggle={toggleLegend} marks={legendMarks} className="min-w-0 flex-1" />;
  // 범례와 한 줄이라 범례를 밀어내지 않도록 보이는 것은 아이콘, 글자는 화면 읽기 프로그램과 툴팁에 준다.
  const loadingMark = loadingLabel && (
    <span role="status" title={loadingLabel} className="flex size-7 shrink-0 items-center justify-center text-text-secondary">
      <LoaderCircle className="size-4 motion-safe:animate-spin" aria-hidden="true" />
      <span className="sr-only">{loadingLabel}</span>
    </span>
  );
  const panelView = panel && (
    <div key={panel.key} className="flex min-h-0 flex-1 flex-col motion-page">
      <div className="flex items-start gap-2 py-2 pr-1 pl-4">
        <h2 ref={panelHeadingRef} tabIndex={-1} className="min-w-0 flex-1 pt-2 text-xl leading-snug font-semibold text-text-primary outline-none">
          {panel.title}
        </h2>
        <Button variant="ghost" size="icon" aria-label={panel.closeLabel} onClick={panel.onClose}>
          <X aria-hidden="true" />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">{panel.body}</div>
    </div>
  );
  // 포커스·경로 바는 겹친 상세 패널 아래로 들어가지 않는다.
  const barClass = cn("absolute top-3 left-3 max-md:-right-1 max-md:-left-1", panelOverCanvas ? "md:max-w-[calc(100%-404px)]" : "md:max-w-[calc(100%-24px)]");

  return (
    <div
      className={cn("flex min-h-0 min-w-0", className)}
      onKeyDown={(e) => {
        if (e.key !== "Escape" || e.defaultPrevented) return;
        if (impactKey) {
          e.stopPropagation();
          exitImpact();
        } else if (validSelection) {
          e.stopPropagation();
          close();
        }
      }}
    >
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2 md:gap-3">
        {/* 데스크톱: 도구 막대·범례·보기 전환을 한 줄에 둬 캔버스 높이를 늘린다. 범례와 보기 전환은 한 묶음이라, 도구 막대 옆이
            (범례 20rem + 보기 전환)보다 좁으면 범례를 여러 줄로 쪼개거나 보기 전환만 따로 떨어뜨리지 않고 묶음째 다음 줄로 내린다. */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <div className="min-w-0 max-md:w-full">{toolbar}</div>
          {!isMobile && (
            <div className="flex min-w-0 flex-1 basis-[34rem] items-center gap-x-3">
              {view === "graph" ? legend : <div className="flex-1" />}
              {loadingMark}
              <div className="ml-auto flex items-center gap-1">
                {viewSwitch}
                <KeyboardHelp />
              </div>
            </div>
          )}
        </div>
        {graph.metadata.truncated && (
          <p className="text-sm text-warning">노드가 많아 {graph.metadata.limit}개까지만 보여드려요.</p>
        )}
        {isMobile && (
          <div className="flex min-w-0 items-center gap-2">
            {view === "graph" ? legend : <div className="flex-1" />}
            {loadingMark}
            {viewSwitch}
          </div>
        )}
        {/* 그래프는 목록 보기 중에도 숨겨 둔 채 유지한다(확대 배율·위치 보존). 보이게 되면 크기를 다시 재서 맞춘다. */}
        <div className={cn("relative flex min-h-0 flex-1 flex-col", view !== "graph" && "hidden")} aria-busy={Boolean(loadingLabel) || undefined}>
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
            path={route ?? impacted?.highlight ?? null}
            centerOn={centerOn}
            occludeRight={panelOverCanvas ? PANEL_WIDTH : 0}
            sheetOver={isMobile && (Boolean(validSelection) || Boolean(impactDetail) || pathSheetOpen)}
            initialCamera={initialCamera}
            onCameraIdle={onCameraIdle}
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
              className={barClass}
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
              className={barClass}
            />
          )}
          {panelOverCanvas && (
            <aside
              aria-label="상세"
              style={{ width: PANEL_WIDTH }}
              className="absolute top-px right-px bottom-px flex flex-col border-l border-border-subtle bg-surface-base"
            >
              {panelView}
            </aside>
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
          open={Boolean(validSelection) || Boolean(impactDetail) || pathSheetOpen}
          onOpenChange={(open) => {
            if (open) return;
            if (impactDetail) exitImpact();
            else if (validSelection) close();
            // 이어지지 않는 경로의 안내를 닫으면 경로 모드에서도 나간다(지도에 남는 표시가 없으므로).
            else if (route) setStepsOpenKey(null);
            else exitPath();
          }}
          title={panel?.title ?? ""}
          closeLabel={panel?.closeLabel ?? "닫기"}
          defaultSnap="half"
        >
          {sheetTop}
          <div className="-mx-4 -mt-1">{panel?.body}</div>
        </BottomSheet>
      ) : (
        view === "list" && (
          <aside aria-label="상세" className="ml-4 flex shrink-0 flex-col border-l border-border-subtle" style={{ width: PANEL_WIDTH }}>
            {panelView ?? (
              <p className="flex items-center gap-2 px-4 pt-4 text-base text-text-secondary">
                <MousePointerClick className="size-5 shrink-0" aria-hidden="true" />
                기업이나 사건을 골라 주세요.
              </p>
            )}
          </aside>
        )
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
        <dd>기업·사건, 기업 사이 선(사건 공유), 사건 사이 선(후속 사건) 자세히 보기</dd>
        <dt className="font-medium text-text-primary">관련 이슈</dt>
        <dd>기업 상세에서 사건을 고르면 영향 경로와 근거</dd>
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
