// UI-03 메인 지도: 데스크톱은 [내 종목 목록 | 지도 | 상세], 모바일은 그래프 기본 + 목록 전환 + 상세 시트.
// 모드는 전체(시장 전체) / 개인화(내 종목: 보유 + 관심) 두 가지(요구 17–19). 주소를 주지 않으면 회원 중 보유·관심이
// 있으면 개인화, 아니면 전체로 연다(요구 6·14).
// 모드·선택·포커스·경로·영향 경로는 주소(?mode=&select=&focus=&hops=&path=&impact=)에 담는다. 모드 전환과 포커스·경로·영향 경로
// 진입·변경·해제는 이력에 쌓고(push, 뒤로 가기로 복귀), 선택은 바꿔 쓴다(replace). 포커스·경로·영향 경로는 함께 두지 않는다.
// 모드 전환(FS019): 대상 모드 지도를 먼저 받고, 성공한 뒤에만 모드 이름·도구 막대·지도를 함께 바꾼다. 받는 동안·실패하면 지금 모드
// 지도를 그대로 두고(실패는 다시 시도), 늦게 온 이전 전환 응답은 쓰지 않는다. 떠나는 모드의 선택·포커스·경로·카메라·범례 필터는
// 모드별로 보관했다가(graph-entry) 그 모드로 돌아오면 복원한다. 새 지도에 없는 선택은 풀고 그렇다고 알린다.
// 지도 조회 실패(FS017): 처음 조회가 실패하면 오류 화면, 이미 지도가 있으면 지도·선택을 그대로 두고 이전 결과라는 안내와 다시 시도를 띄운다.
// 비회원이 잠긴 개인화 모드를 고르면(또는 그 주소로 오면) 시장 전체 지도를 그대로 두고 로그인 안내를 띄운다(FS019, 요구 51).
// 사이드바에서 지도에 있는 기업을 고르면 그 노드를 선택하고 카메라를 그 기업 중심으로 확대·이동한다.
// 데스크톱 사이드바(내 종목)는 도구 막대의 [내 종목]으로 접고 펼친다(넓은 화면은 펼침이 기본, 고른 값은 기억). 접으면 지도가 그 폭을 쓴다.
// 지도 복귀(FS044): 떠날 때 주소·카메라·범례 필터·보기를 저장한다(기업 상세 [그래프로 복귀]용 진입 그래프 + 이 이력 항목).
// 돌아오면 [그래프로 복귀]가 넘긴 state.graphRestore, 없으면 브라우저 뒤로 가기로 돌아온 이력 항목의 저장값으로 복원한다.
// 튜토리얼(요구 15·16): 튜토리얼을 마치지 않은 회원·비회원, 또는 계정 메뉴의 [튜토리얼 다시 보기](?tour=1)에서
// 지도 위 단계형 안내를 띄운다. 데스크톱은 왼쪽 목록 자리, 모바일은 지도 위(문서 흐름 안)에 놓는다.
// 개인화 필터(FS017·FS019·FS026): 내 종목 모드 안에서 전체·보유·관심으로 기준 종목을 좁힌다(lib/personal-filter). 모드와 따로 두고
// 같은 탭 세션 동안 기억한다. 필터를 바꿔 지금 선택·포커스·경로가 지도에서 빠지면 풀고 알린다. 사이드바에서 필터로 빠진 기업을
// 고르면 필터를 바꾸지 않고 안내와 [전체로 보기]를 띄운다.
import { ArrowLeft, CircleAlert, Info, PanelLeftClose, PanelLeftOpen, RotateCw, Star, Wallet, X } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import type { Schemas } from "@/api/client";
import type { CompanyReturn } from "./company-page";
import { graphQuery, useBriefingGraphBasis, useCompanies, useGraph, useLogout, usePortfolio, useSession, useSettings } from "@/api/queries";
import { CompanyMark } from "@/components/domain/company-mark";
import type { CenterRequest, GraphSelection } from "@/components/domain/graph-canvas";
import type { Viewport } from "@/components/domain/graph-layout";
import { GraphModeSwitch, MarkRing, PersonalFilterSwitch } from "@/components/domain/graph-legend";
import { WatchToggle } from "@/components/domain/watch-toggle";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingBlock, Skeleton, SkeletonLines, SkeletonRows } from "@/components/ui/feedback";
import { ListRow } from "@/components/ui/list-row";
import { SectionHeader } from "@/components/ui/section-header";
import { GraphExplorer, type ExplorerView } from "@/features/graph-explorer";
import { GraphTutorialPanel, GraphTutorialSheetBar, useGraphTutorial } from "@/features/graph-tutorial";
import { BriefingGraphBasisBar, BriefingGraphGate } from "@/features/briefing-graph-basis";
import { parsePathParam } from "@/lib/graph-path";
import { readModeEntry, saveGraphEntry, saveModeEntry, type GraphEntry, type GraphRestoreState } from "@/lib/graph-entry";
import { ISOLATED_BUNDLE_ID, type GraphFocus, type LegendKey } from "@/lib/graph-view";
import { filterPersonalGraph, personalFilterLabel, readPersonalFilter, retainTargets, savePersonalFilter, type PersonalFilter } from "@/lib/personal-filter";
import { emptyReasonMessage, modeLabel, type GraphMode } from "@/lib/labels";
import { holdingWeightText } from "@/lib/holding";
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
  // 캔버스가 다음 배치에서 쓸 카메라: 처음엔 지도 복귀(FS044) 값, 모드가 바뀌면 그 모드에 보관한 값(FS019)
  const [modeCamera, setModeCamera] = useState<Viewport | null>(restore?.camera ?? null);
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
  const [guestPrompt, setGuestPrompt] = useState(false);
  const watchCount = settings.data?.watchlistIds.length ?? 0;
  const holdingCount = portfolio.data?.holdings.length ?? 0;
  // 필터 칸의 종목 수: 아직 모르거나 받지 못했으면 숫자를 적지 않는다.
  const knownWatchCount = settings.data ? watchCount : null;
  const knownHoldingCount = portfolio.data ? holdingCount : null;
  // 기본 모드는 회원의 보유·관심을 알아야 정할 수 있다(설정·계좌 조회가 끝날 때까지 기다린다. 실패하면 전체).
  const personalKnown = (settings.isSuccess || settings.isError) && (portfolio.isSuccess || portfolio.isError);
  // 비회원은 개인화 주소로 와도 시장 전체 지도를 본다(로그인 안내만 띄운다).
  const mode: GraphMode = isGuest ? "all" : (requested ?? (watchCount + holdingCount > 0 ? "personal" : "all"));
  const graph = useGraph(mode, session.isSuccess && roundReady && (isGuest || requested !== null || personalKnown));
  const queryClient = useQueryClient();

  // 화면에 보이는 지도: 지금 주소(모드·회차)의 데이터, 아직 없거나 받지 못했으면 마지막으로 보인 지도(뒤로 가기 등으로 주소가 먼저 바뀐 경우).
  // 이름·도구 막대는 보이는 지도의 모드를 따른다(다른 모드 데이터에 새 모드 이름을 붙이지 않는다).
  const lastShownRef = useRef<{ mode: GraphMode; round: string | null; data: Schemas["GraphResponse"] } | null>(null);
  if (graph.data) lastShownRef.current = { mode, round, data: graph.data };
  const shown = lastShownRef.current;

  // 개인화 필터(FS017): 회원의 내 종목 지도만 거른다. 보유·관심이 모두 없는 지도는 거르지 않는다(그 빈 상태를 그대로 보인다).
  const [personalFilter, setPersonalFilter] = useState(readPersonalFilter);
  const filterable = !isGuest && shown?.mode === "personal" && shown.data.metadata.emptyReason !== "no_personal_stocks";
  const shownData = shown?.data;
  const filtered = useMemo(
    () => (filterable && shownData ? filterPersonalGraph(shownData, personalFilter) : null),
    [filterable, shownData, personalFilter],
  );
  const display = filtered?.graph ?? shownData;
  // 사이드바에서 고른 기업이 지금 필터에서 빠져 있을 때(FS026): 필터는 그대로 두고 안내한다.
  const [excludedPick, setExcludedPick] = useState<{ id: string; name: string } | null>(null);

  // 보이는 지도의 모드가 바뀌면(전환 성공·뒤로 가기) 떠난 모드의 상태(주소·카메라·범례 필터)를 보관하고, 돌아온 모드의 필터·카메라를 꺼낸다.
  // 렌더 중에 바로 바꿔(파생 상태) 새 데이터와 같은 화면에 함께 그린다. 처음 그린 모드는 지도 복귀 값을 그대로 쓴다.
  const url = location.pathname + location.search;
  const committedUrlRef = useRef(url);
  useEffect(() => {
    committedUrlRef.current = url;
  });
  const [appliedMode, setAppliedMode] = useState<GraphMode | null>(null);
  if (graph.data && appliedMode !== mode) {
    if (appliedMode !== null) {
      saveModeEntry(appliedMode, { url: committedUrlRef.current, camera: cameraRef.current ?? undefined, hidden: [...hidden] });
      const entry = readModeEntry(mode);
      setHidden(new Set((entry?.hidden ?? []) as LegendKey[]));
      cameraRef.current = entry?.camera ?? null;
      setModeCamera(entry?.camera ?? null);
    }
    setAppliedMode(mode);
  }

  // 진행 중인 모드 전환(대상 모드 조회). 번호가 바뀌면 늦게 온 응답은 버린다.
  const [switching, setSwitching] = useState<{ mode: GraphMode; error: unknown } | null>(null);
  const switchSeqRef = useRef(0);
  const [droppedNotice, setDroppedNotice] = useState<string | null>(null);
  // 주소의 모드·회차가 전환 밖에서 바뀌면(뒤로 가기 등) 진행 중인 전환을 거둔다.
  useEffect(() => {
    switchSeqRef.current += 1;
    setSwitching(null);
  }, [requested, round]);

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

  const shownMode = shown?.mode ?? mode;

  /** 전환이 성공했을 때: 주소의 모드와 그 모드에 보관한 선택·포커스·경로를 한 번에 바꾼다. 새 지도에 없는 대상은 풀고 알린다.
   *  범례 필터·카메라는 새 모드 지도가 보일 때(위 파생 상태) 함께 바뀐다. */
  const applyMode = (next: GraphMode, data: Schemas["GraphResponse"]) => {
    const saved = readModeEntry(next);
    // 개인화 지도는 지금 필터로 거른 지도에 있는 대상만 복원한다.
    const target = next === "personal" && data.metadata.emptyReason !== "no_personal_stocks" ? filterPersonalGraph(data, personalFilter).graph : data;
    const { kept, dropped } = retainTargets(new URLSearchParams(saved?.url.split("?")[1] ?? ""), target);
    setParams((prev) => {
      const p = new URLSearchParams(prev);
      p.set("mode", next);
      for (const key of ["select", "focus", "hops", "path", "impact"]) p.delete(key);
      kept.forEach((value, key) => p.set(key, value));
      return p;
    });
    setSwitching(null);
    setDroppedNotice(dropped ? "전에 고른 대상이 이 지도에 없어서 선택을 풀었어요." : null);
  };

  /** 개인화 필터 전환(FS017·FS019): 모드·주소 이력과 따로 두고 이 탭 세션에 기억한다. 새 범위에 없는 선택·포커스·경로는 풀고 알린다. */
  const changeFilter = (next: PersonalFilter) => {
    setExcludedPick(null);
    if (next === personalFilter) return;
    setPersonalFilter(next);
    savePersonalFilter(next);
    if (!shownData) return;
    const { kept, dropped } = retainTargets(params, filterPersonalGraph(shownData, next).graph);
    setDroppedNotice(dropped ? `고른 대상이 ${personalFilterLabel[next]} 범위에 없어서 선택을 풀었어요.` : null);
    if (dropped)
      setParams(
        (prev) => {
          const p = new URLSearchParams(prev);
          for (const key of ["select", "focus", "hops", "path", "impact"]) p.delete(key);
          kept.forEach((value, key) => p.set(key, value));
          return p;
        },
        { replace: true },
      );
  };

  /** 모드 전환(FS019): 대상 모드 지도를 먼저 받는다. 받는 동안·실패하면 지금 지도와 모드 표시를 그대로 둔다.
   *  다시 누르거나 다른 모드를 고르면 번호가 바뀌어 이전 전환의 늦은 응답은 버린다. 비회원의 개인화는 로그인 안내만 띄운다. */
  const setMode = (next: GraphMode) => {
    setDroppedNotice(null);
    setExcludedPick(null);
    if (isGuest && next === "personal") {
      setGuestPrompt(true);
      return;
    }
    setGuestPrompt(false);
    const seq = ++switchSeqRef.current;
    if (next === shownMode && next === mode) {
      setSwitching(null);
      return;
    }
    setSwitching({ mode: next, error: null });
    queryClient.fetchQuery({ ...graphQuery(next, null), staleTime: 30_000 }).then(
      (data) => {
        if (seq === switchSeqRef.current) applyMode(next, data);
      },
      (error: unknown) => {
        if (seq === switchSeqRef.current) setSwitching({ mode: next, error });
      },
    );
  };
  const closeGuestPrompt = () => {
    setGuestPrompt(false);
    // 개인화 주소로 들어온 비회원이면 주소도 시장 전체로 바꾼다.
    if (locked)
      setParams(
        (prev) => {
          const p = new URLSearchParams(prev);
          p.set("mode", "all");
          return p;
        },
        { replace: true },
      );
  };

  /** 사이드바 선택: 그 기업을 고르고 포커스·경로를 풀어 전체 배치에서 그 기업 중심으로 카메라를 옮긴다. */
  const selectCompany = (id: string) => {
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
  /** 개인화 필터로 빠진 기업이면(FS026) 필터를 자동으로 바꾸지 않고 안내와 [전체로 보기]를 띄운다. */
  const pickCompany = (id: string) => {
    const node = shownData?.nodes.find((n) => n.id === id);
    if (node && filtered && !filtered.graph.nodes.some((n) => n.id === id)) {
      setExcludedPick({ id, name: node.label });
      return;
    }
    setExcludedPick(null);
    selectCompany(id);
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
  const showTutorial = tutorialOpen && (display?.nodes.length ?? 0) > 0;
  const tutorial = useGraphTutorial(showTutorial, closeTutorial, isGuest, () => goToLogin());
  const sheetOpen = isMobile && (selection !== null || path !== null || impact !== null);
  const hasSidebar = !isMobile && !showTutorial && !round;
  const shownName = shown?.round ? "브리핑 회차 기준" : modeLabel[shownMode];
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
            value={shownMode}
            onValueChange={setMode}
            lockedModes={isGuest ? guestLockedModes : []}
            fill={isMobile}
            className={isMobile ? "w-full" : undefined}
          />
          {filterable && (
            <PersonalFilterSwitch
              value={personalFilter}
              onValueChange={changeFilter}
              holdingCount={knownHoldingCount}
              watchCount={knownWatchCount}
              fill={isMobile}
              className={isMobile ? "w-full" : undefined}
            />
          )}
        </>
      )}
    </div>
  );

  const goToLogin = () => logout.mutate(undefined, { onSettled: () => navigate("/login") });

  // 지도 위 안내: 전환 실패 > 주소가 바뀐 지도의 조회 실패 > 지금 지도의 새로 고침 실패 > 비회원 로그인 안내 > 풀린 선택
  const notices: ReactNode[] = [];
  const retry = (
    <Button variant="secondary" size="sm" onClick={() => (switching?.error ? setMode(switching.mode) : void graph.refetch())}>
      <RotateCw aria-hidden="true" />
      다시 시도
    </Button>
  );
  if (switching?.error) {
    notices.push(
      <MapNotice key="switch" tone="error" action={retry} onDismiss={() => setSwitching(null)}>
        {modeLabel[switching.mode]} 지도를 불러오지 못했어요. {shownName} 지도를 그대로 보여드려요.
      </MapNotice>,
    );
  } else if (shown && graph.isError) {
    notices.push(
      <MapNotice key="refresh" tone="error" action={retry}>
        {graph.data
          ? "지도를 새로 불러오지 못했어요. 지금 보이는 지도는 이전에 불러온 결과예요."
          : `${round ? "브리핑 회차 기준" : modeLabel[mode]} 지도를 불러오지 못했어요. 이전에 보던 ${shownName} 지도를 보여드려요.`}
      </MapNotice>,
    );
  }
  if (guestPrompt || locked) {
    notices.push(
      <MapNotice
        key="guest"
        tone="info"
        onDismiss={closeGuestPrompt}
        action={
          <Button size="sm" onClick={goToLogin} loading={logout.isPending}>
            로그인
          </Button>
        }
      >
        로그인하면 내 종목 지도를 볼 수 있어요. 지금은 시장 전체 지도예요.
      </MapNotice>,
    );
  }
  if (excludedPick && filtered) {
    const { id } = excludedPick;
    notices.push(
      <MapNotice
        key="excluded"
        tone="info"
        onDismiss={() => setExcludedPick(null)}
        action={
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              changeFilter("all");
              selectCompany(id);
            }}
          >
            전체로 보기
          </Button>
        }
      >
        지금은 {personalFilterLabel[personalFilter]} 종목만 보고 있어요. {excludedPick.name} 기업은 전체로 볼 때 보여요.
      </MapNotice>,
    );
  }
  if (droppedNotice) {
    notices.push(
      <MapNotice key="dropped" tone="info" onDismiss={() => setDroppedNotice(null)}>
        {droppedNotice}
      </MapNotice>,
    );
  }
  const loadingLabel =
    switching && !switching.error
      ? `${modeLabel[switching.mode]} 지도를 불러오고 있어요`
      : shown && graph.isFetching && (!graph.data || graph.isError)
        ? "지도를 불러오고 있어요"
        : undefined;

  let content;
  if (round && !roundReady) {
    content = <BriefingGraphGate query={basis} onShowCurrent={showCurrent} />;
  } else if (!shown) {
    // 처음 조회: 아직 보일 지도가 없으므로 실패하면 오류 화면이다.
    content = (
      <>
        {toolbar}
        {graph.isError ? (
          <ErrorState error={graph.error} title="지도를 불러오지 못했어요" onRetry={() => void graph.refetch()} />
        ) : view === "list" ? (
          <SkeletonRows count={4} label="지도를 불러오고 있어요" />
        ) : (
          <LoadingBlock label="지도를 불러오고 있어요" className="flex min-h-[360px] flex-1">
            <Skeleton className="flex-1 rounded-none" />
          </LoadingBlock>
        )}
      </>
    );
  } else if (filtered && personalFilter !== "all" && display && (display.nodes.length === 0 || display.edges.length === 0)) {
    // 고른 범위에 기준 종목이 없거나 연결된 사건이 없는 것은 오류가 아니라 빈 결과다(FS017 예외 처리). 다른 범위로 바꿀 수 있게 한다.
    content = (
      <>
        {toolbar}
        {loadingLabel && <p role="status" className="sr-only">{loadingLabel}</p>}
        <FilterEmptyState
          filter={personalFilter}
          count={personalFilter === "holding" ? knownHoldingCount : knownWatchCount}
          otherCount={personalFilter === "holding" ? knownWatchCount : knownHoldingCount}
          loadError={personalFilter === "holding" ? portfolio.error : settings.error}
          onRetry={() => void (personalFilter === "holding" ? portfolio.refetch() : settings.refetch())}
          companies={display.nodes.filter((n) => n.kind === "company").map((n) => n.label)}
          onFilter={changeFilter}
        />
      </>
    );
  } else if (!display || display.nodes.length === 0 || display.edges.length === 0) {
    // 관계 0건은 오류가 아니라 '연결 없음'이다(FS017). 내 종목만 있고 연결이 없으면 그 기업들을 밝힌다.
    content = (
      <>
        {toolbar}
        {loadingLabel && <p role="status" className="sr-only">{loadingLabel}</p>}
        <MapEmptyState
          reason={shown.data.metadata.emptyReason}
          mode={shownMode}
          companies={shown.data.nodes.filter((n) => n.kind === "company").map((n) => n.label)}
          onMarket={() => setMode("all")}
        />
      </>
    );
  } else {
    content = (
      <GraphExplorer
        graph={display}
        mapName={`${shownName} 지도`}
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
        initialCamera={modeCamera}
        onCameraIdle={(viewport) => void (cameraRef.current = viewport)}
        sheetTop={showTutorial ? <GraphTutorialSheetBar tutorial={tutorial} onCloseSheet={() => setSelection(null)} /> : undefined}
        loadingLabel={loadingLabel}
        toolbar={toolbar}
        // 개인화 필터가 보유·관심 고리를 보이므로 범례에서는 빼 도구 막대 줄 수를 늘리지 않는다(§4.9 지도 면적 우선).
        legendMarks={!filterable}
        className="flex-1"
      />
    );
  }

  return (
    <div className="mx-auto flex h-[calc(100dvh-3rem-1px-56px-env(safe-area-inset-bottom))] min-h-0 w-full flex-none px-4 py-3 md:h-[calc(100dvh-3.5rem-1px)] md:px-6 md:py-4">
      <h1 className="sr-only">{shownName} 지도</h1>
      {!isMobile && showTutorial && <GraphTutorialPanel tutorial={tutorial} className="mr-4 w-72 shrink-0 self-start" />}
      {hasSidebar && sidebarOpen && (
        <Sidebar
          isGuest={isGuest}
          settings={settings.data}
          graphNodes={shown?.data.nodes ?? []}
          graphEdges={shown?.data.edges ?? []}
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
        {notices.length > 0 && <div className="flex shrink-0 flex-col gap-2">{notices}</div>}
        {content}
      </section>
    </div>
  );
}

/** 개인화 필터로 고른 범위가 비었을 때(FS017 예외 처리). 오류가 아니라 빈 결과이므로 다른 범위로 바꾸는 길을 둔다.
 *  종목 수를 받지 못했으면 '없음'으로 단정하지 않고 불러오지 못했다고 적는다. */
function FilterEmptyState({
  filter,
  count,
  otherCount,
  loadError,
  onRetry,
  companies,
  onFilter,
}: {
  filter: Exclude<PersonalFilter, "all">;
  count: number | null;
  otherCount: number | null;
  loadError: unknown;
  onRetry: () => void;
  companies: string[];
  onFilter: (filter: PersonalFilter) => void;
}) {
  const label = personalFilterLabel[filter];
  const other = filter === "holding" ? "watch" : "holding";
  const toAll = (
    <Button variant="ghost" onClick={() => onFilter("all")}>
      전체로 보기
    </Button>
  );
  if (count === null && loadError) return <ErrorState error={loadError} title={`${label} 종목을 불러오지 못했어요`} onRetry={onRetry} />;
  if (count === 0) {
    return (
      <EmptyState
        title={`${label} 종목이 없어요`}
        description={filter === "holding" ? "가상 계좌를 연결하면 보유 종목 기준으로 볼 수 있어요." : "관심 종목을 고르면 그 기준으로 볼 수 있어요."}
        action={
          <>
            <Button asChild>
              <Link to="/me/stocks">{filter === "holding" ? "가상 계좌 연결하기" : "관심 종목 고르기"}</Link>
            </Button>
            {(otherCount ?? 0) > 0 && (
              <Button variant="ghost" onClick={() => onFilter(other)}>
                {other === "watch" ? "관심으로 보기" : "보유로 보기"}
              </Button>
            )}
            {toAll}
          </>
        }
      />
    );
  }
  // 기준 종목은 있지만 연결된 공개 관계가 없다(관계 0건). 기준 기업은 밝힌다.
  return (
    <EmptyState
      title={`${label} 종목과 연결된 사건이 아직 없어요`}
      description={
        companies.length > 0
          ? `${companies.slice(0, 3).join(", ")}${companies.length > 3 ? ` 외 ${companies.length - 3}곳` : ""}에 연결된 공개 관계가 아직 없어요.`
          : "확인된 공개 관계가 아직 없어요."
      }
      action={toAll}
    />
  );
}

/** 지도 위 한 줄 안내(오류·정보). 색만으로 구분하지 않도록 아이콘과 문장으로 상태를 밝힌다. */
function MapNotice({ tone, children, action, onDismiss }: { tone: "error" | "info"; children: ReactNode; action?: ReactNode; onDismiss?: () => void }) {
  const Icon = tone === "error" ? CircleAlert : Info;
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-sm border border-border-strong bg-surface-sunken py-2 pr-1 pl-3"
    >
      <p className="flex min-w-0 flex-1 basis-60 items-start gap-2 text-base text-text-primary">
        <Icon className={tone === "error" ? "mt-0.5 size-5 shrink-0 text-error" : "mt-0.5 size-5 shrink-0 text-text-secondary"} aria-hidden="true" />
        {children}
      </p>
      <div className="flex items-center gap-1">
        {action}
        {onDismiss && (
          <Button variant="ghost" size="icon" aria-label="안내 닫기" onClick={onDismiss}>
            <X aria-hidden="true" />
          </Button>
        )}
      </div>
    </div>
  );
}

function MapEmptyState({ reason, mode, companies, onMarket }: { reason: string | null; mode: GraphMode; companies: string[]; onMarket: () => void }) {
  // 내 종목은 있지만 공개 관계가 없으면(FS017) 어느 기업인지 밝힌다.
  const message =
    mode === "personal" && reason === "no_related_issues" && companies.length > 0
      ? {
          title: "내 종목과 연결된 사건이 아직 없어요",
          body: `${companies.slice(0, 3).join(", ")}${companies.length > 3 ? ` 외 ${companies.length - 3}곳` : ""}에 연결된 공개 관계가 아직 없어요. 시장 전체 지도를 살펴보세요.`,
        }
      : emptyReasonMessage(reason, mode);
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
  graphEdges,
  selectedId,
  onPick,
  onLogin,
}: {
  isGuest: boolean;
  settings: Schemas["SettingsResponse"] | undefined;
  graphNodes: Schemas["GraphNode"][];
  graphEdges: Schemas["GraphEdge"][];
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
  // 지도에 있지만 연결선이 없는 종목은 '연결된 사건 없음'을 붙인다(FS017 관계 없음).
  const linked = new Set(graphEdges.flatMap((e) => [e.source, e.target]));
  const row = (kind: "holding" | "watch", id: string, name: string, detail?: string) => {
    const node = graphNodes.find((n) => n.id === id);
    const description = node && !linked.has(id) ? [detail, "연결된 사건 없음"].filter(Boolean).join(" · ") : detail;
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
                <ul>{portfolio.data.holdings.map((h) => row("holding", h.companyId, h.name, holdingWeightText(h)))}</ul>
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
