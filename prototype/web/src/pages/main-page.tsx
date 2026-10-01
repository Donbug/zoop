// UI-03 메인 지도: 데스크톱은 [내 종목 목록 | 지도 | 상세], 모바일은 그래프 기본 + 목록 전환 + 상세 시트.
// 모드는 전체(시장 전체) / 개인화(내 종목: 보유 + 관심) 두 가지(요구 17–19). 주소를 주지 않으면 회원 중 보유·관심이
// 있으면 개인화, 아니면 전체로 연다(요구 6·14).
// 모드·선택·포커스·경로는 주소(?mode=&select=&focus=&hops=&path=)에 담는다. 모드 전환과 포커스·경로 진입·변경·해제는
// 이력에 쌓고(push, 뒤로 가기로 복귀), 선택은 바꿔 쓴다(replace). 포커스와 경로는 함께 두지 않는다.
// 비회원이 잠긴 개인화 모드를 누르면 그 모드 주소로 이동해 로그인 안내를 보여준다(요구 51, 뒤로가기로 전체 복귀).
// 사이드바에서 지도에 있는 기업을 고르면 그 노드를 선택하고 카메라를 그 기업 중심으로 확대·이동한다.
// 튜토리얼(요구 15·16): 튜토리얼을 마치지 않은 회원·비회원, 또는 계정 메뉴의 [튜토리얼 다시 보기](?tour=1)에서
// 지도 위 단계형 안내를 띄운다. 데스크톱은 왼쪽 목록 자리, 모바일은 지도 위(문서 흐름 안)에 놓는다.
import { ArrowLeft, Star, Wallet } from "lucide-react";
import { useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import type { Schemas } from "@/api/client";
import type { CompanyReturn } from "./company-page";
import { useCompanies, useGraph, useLogout, usePortfolio, useSession, useSettings } from "@/api/queries";
import { CompanyMark } from "@/components/domain/company-mark";
import type { CenterRequest, GraphSelection } from "@/components/domain/graph-canvas";
import { GraphModeSwitch, MarkRing } from "@/components/domain/graph-legend";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingBlock, Skeleton, SkeletonLines, SkeletonRows } from "@/components/ui/feedback";
import { ListRow } from "@/components/ui/list-row";
import { SectionHeader } from "@/components/ui/section-header";
import { GraphExplorer, type ExplorerView } from "@/features/graph-explorer";
import { GraphTutorialPanel, GraphTutorialSheetBar, useGraphTutorial } from "@/features/graph-tutorial";
import { parsePathParam } from "@/lib/graph-path";
import { ISOLATED_BUNDLE_ID, type GraphFocus } from "@/lib/graph-view";
import { emptyReasonMessage, modeLabel, type GraphMode } from "@/lib/labels";
import { useMediaQuery } from "@/lib/theme";
import { track, useScreenView } from "@/lib/track";

const guestLockedModes: GraphMode[] = ["personal"];

export function MainPage() {
  const session = useSession();
  const viewId = useScreenView("main");
  const isGuest = session.data?.kind !== "member";
  const settings = useSettings(!isGuest);
  const portfolio = usePortfolio(!isGuest);
  const [params, setParams] = useSearchParams();
  const isMobile = useMediaQuery("(max-width: 768px)");
  const [view, setView] = useState<ExplorerView>("graph");
  const [center, setCenter] = useState<CenterRequest | null>(null);
  const navigate = useNavigate();
  const logout = useLogout();
  // 기업 상세 [지도에서 보기]로 왔으면 그 상세(기간·선택 사건·스크롤)로 돌아가는 링크를 둔다. 지도 안에서 주소가 바뀌어도 유지한다.
  const location = useLocation();
  const [returnTo] = useState(() => (location.state as { returnTo?: CompanyReturn } | null)?.returnTo ?? null);

  const modeParam = params.get("mode");
  const requested: GraphMode | null = modeParam === "all" || modeParam === "personal" ? modeParam : null;
  const locked = isGuest && requested === "personal";
  const watchCount = settings.data?.watchlistIds.length ?? 0;
  const holdingCount = portfolio.data?.holdings.length ?? 0;
  // 기본 모드는 회원의 보유·관심을 알아야 정할 수 있다(설정·계좌 조회가 끝날 때까지 기다린다. 실패하면 전체).
  const personalKnown = (settings.isSuccess || settings.isError) && (portfolio.isSuccess || portfolio.isError);
  const mode: GraphMode = locked ? "personal" : isGuest ? "all" : (requested ?? (watchCount + holdingCount > 0 ? "personal" : "all"));
  const graph = useGraph(mode, session.isSuccess && !locked && (isGuest || requested !== null || personalKnown));

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
      } else {
        p.delete("path");
      }
      return p;
    });

  const setSelection = (next: GraphSelection | null) => {
    if (next && next.id !== ISOLATED_BUNDLE_ID) track({ type: next.kind === "edge" ? "graph_edge_select" : "graph_node_select", targetId: next.id, viewId });
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        if (next) p.set("select", `${next.kind}:${next.id}`);
        else p.delete("select");
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
      return p;
    });
  };

  /** 사이드바 선택: 그 기업을 고르고 포커스·경로를 풀어 전체 배치에서 그 기업 중심으로 카메라를 옮긴다. */
  const pickCompany = (id: string) => {
    track({ type: "graph_node_select", targetId: id, viewId });
    const leavesMode = params.has("focus") || params.has("path");
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        p.set("select", `node:${id}`);
        p.delete("focus");
        p.delete("hops");
        p.delete("path");
        return p;
      },
      { replace: !leavesMode },
    );
    setCenter((prev) => ({ id, seq: (prev?.seq ?? 0) + 1 }));
  };

  const tutorialOpen = Boolean(session.data && (params.get("tour") === "1" || session.data.setup?.tutorialCompleted === false));
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
  const tutorial = useGraphTutorial(showTutorial, closeTutorial);
  const sheetOpen = isMobile && (selection !== null || path !== null);
  const toolbar = (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {returnTo && (
        <Button variant="ghost" size="sm" asChild className="-ml-3">
          <Link to={returnTo.path} state={returnTo.state}>
            <ArrowLeft aria-hidden="true" />
            {returnTo.label} 상세로 돌아가기
          </Link>
        </Button>
      )}
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
    </div>
  );

  const goToLogin = () => logout.mutate(undefined, { onSettled: () => navigate("/login") });

  let content;
  if (locked) {
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
        mapName={`${modeLabel[mode]} 지도`}
        selection={selection}
        onSelectionChange={setSelection}
        view={view}
        onViewChange={setView}
        focus={focus}
        onFocusChange={setFocus}
        path={path}
        onPathChange={setPath}
        centerOn={center}
        sheetTop={showTutorial ? <GraphTutorialSheetBar tutorial={tutorial} onCloseSheet={() => setSelection(null)} /> : undefined}
        loading={graph.isPlaceholderData}
        toolbar={toolbar}
        className="flex-1"
      />
    );
  }

  return (
    <div className="mx-auto flex h-[calc(100dvh-3rem-1px-56px-env(safe-area-inset-bottom))] min-h-0 w-full max-w-[1440px] flex-none px-4 py-3 md:h-[calc(100dvh-3.5rem-1px)] md:px-6 md:py-4">
      <h1 className="sr-only">{modeLabel[mode]} 지도</h1>
      {!isMobile && showTutorial && <GraphTutorialPanel tutorial={tutorial} className="mr-4 w-72 shrink-0 self-start" />}
      {!isMobile && !locked && !showTutorial && (
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

  // 지도에 있는 종목은 지도에서 고르고(그 기업 중심으로 이동), 없는 종목은 기업 상세로 간다.
  // 행 끝 테두리 견본은 지도 노드의 보유(실선)·관심(점선) 표시와 같다.
  const row = (kind: "holding" | "watch", id: string, name: string, description?: string) => {
    const node = graphNodes.find((n) => n.id === id);
    const leading = <CompanyMark id={id} name={name} brandColor={node?.brandColor} logoUrl={node?.logoUrl} />;
    return (
      <li key={id}>
        {node ? (
          <ListRow leading={leading} title={name} description={description} trailing={<MarkRing kind={kind} />} selected={selectedId === id} onClick={() => onPick(id)} />
        ) : (
          <ListRow leading={leading} title={name} description={description} to={`/companies/${encodeURIComponent(id)}`} state={from} />
        )}
      </li>
    );
  };

  return (
    <aside aria-label="내 종목" className="mr-4 flex w-60 shrink-0 flex-col overflow-y-auto border-r border-border-subtle pr-2">
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
          <section aria-labelledby="side-watch">
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
