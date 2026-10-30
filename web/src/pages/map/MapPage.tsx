import BriefingRoundIssuePanel from '@/components/graph/BriefingRoundIssuePanel';
import {
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import {
  GraphAppearanceContext,
  type GraphAppearance,
} from '@/components/graph/graph-appearance';
import { mapAppearanceStyles } from '@/components/common/map-appearance-styles';
import { useTutorialInteractionLock } from '@/components/graph/tutorial/useTutorialInteractionLock';
import HoldingsSidebar from '@/components/graph/HoldingsSidebar';
import { companyLogo } from '@/util/company-logo';
import { Link } from 'react-router-dom';
import ServiceHeader from '@/components/common/ServiceHeader';
import SkipLink from '@/components/common/SkipLink';
import GraphCanvas from '@/components/graph/GraphCanvas';
import GraphIcon from '@/components/graph/GraphIcon';
import GraphTutorial from '@/components/graph/GraphTutorial';
import { tutorialTarget } from '@/components/graph/tutorial/tutorial-target';
import GraphFocusControls from '@/components/graph/GraphFocusControls';
import CompanyLogo from '@/components/common/CompanyLogo';
import CompanyPathPanel from '@/components/graph/CompanyPathPanel';
import { companyPath } from '@/components/graph/company-path';
import ImpactPathPanel from '@/components/graph/ImpactPathPanel';
import CompanyDetailPanel from '@/components/graph/CompanyDetailPanel';
import RelationDetailPanel from '@/components/graph/RelationDetailPanel';
import type {
  RelationDetail,
  StructuralSupplyLink,
} from '@/types/map/relation';
import EventDetailPanel, {
  type EventAction,
} from '@/components/graph/EventDetailPanel';
import AiChatDrawer from '@/components/ai/AiChatDrawer';
import type { AnswerMapTarget } from '@/components/ai/ChatJobCard';
import BriefingSnapshotBanner from '@/components/graph/BriefingSnapshotBanner';
import EvidenceDrawer from '@/components/evidence/EvidenceDrawer';
import {
  focusNeighborhood,
  graphSummary,
} from '@/components/graph/graph-model';
import {
  useGraphData,
  graphRequestKey,
  type GraphPrefetch,
} from '@/hooks/useGraphData';
import { getGraph } from '@/apis/graph/graph';
import {
  emptyView,
  isolatedIssues,
  readModeEntry,
  saveModeEntry,
  restoreTargets,
} from '@/components/graph/graph-view';
import IsolatedIssuesPanel from '@/components/graph/IsolatedIssuesPanel';
import MapDetailSheet from '@/components/graph/MapDetailSheet';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import { useCompanyResource } from '@/hooks/useCompanyResource';
import { useImpactPath } from '@/hooks/useImpactPath';
import { companyUrl } from '@/apis/company/company';
import { setTutorialCompleted } from '@/apis/graph/tutorial';
import { impactEdges, exactTime } from '@/components/company/detail-model';
import { companyDetailRouteFromMap } from '@/util/company-detail-route';
import type { Impact } from '@/types/company/detail';
import { useAuth } from '@/hooks/useAuth';
import { selectMemberId, useAuthStore } from '@/stores/useAuthStore';
import { track, useScreenView } from '@/util/track';
import { useAiChatStore } from '@/stores/useAiChatStore';
import { useGraphUiStore } from '@/stores/useGraphUiStore';
import type { EventDetail } from '@/types/map/event';
import type {
  GraphTarget,
  GraphTutorialStep,
  MapMode,
  PersonalScope,
  WatchSync,
} from '@/types/map';
import '@/components/graph/relationship-map.css';
import { useColorTheme } from '@/util/theme-color';
import { readSocialLinkResult } from '@/components/common/socialLinkResult';

// Same-session preference only. useAuthStore clears it when the member changes
// and keeps it when the same member's session is restored after a reload.
const FILTER_KEY = 'zoop.graph.personal-filter';
const SIDEBAR_KEY = 'zoop:sidebar-open';
const COMPANY_PANEL_WIDTH_KEY = 'zoop:graph-company-panel-width';
const COMPANY_PANEL_MIN_WIDTH = 280;
const COMPANY_PANEL_DEFAULT_WIDTH = 320;
const COMPANY_PANEL_MAX_WIDTH = 560;
function readCompanyPanelWidth() {
  try {
    const saved = Number(localStorage.getItem(COMPANY_PANEL_WIDTH_KEY));
    return Number.isFinite(saved) &&
      saved >= COMPANY_PANEL_MIN_WIDTH &&
      saved <= COMPANY_PANEL_MAX_WIDTH
      ? saved
      : COMPANY_PANEL_DEFAULT_WIDTH;
  } catch {
    return COMPANY_PANEL_DEFAULT_WIDTH;
  }
}
function readSidebarPreference(): boolean | null {
  try {
    const saved = localStorage.getItem(SIDEBAR_KEY);
    if (saved === '1' || saved === '0') return saved === '1';
  } catch {
    // The viewport default still works when storage is unavailable.
  }
  return null;
}
function readFilter(value: string | null): PersonalScope {
  return value === 'holdings' || value === 'watchlist' ? value : 'all';
}

// WBS 6.6.21~6.6.23 · D-GRP-01/01b + D-GRP-02/03.
export default function MapPage() {
  const { params, updateQuery } = useRouteQuery();
  const owner = useAuthStore(
    (state) => `${selectMemberId(state) ?? 'guest'}:${state.sessionRevision}`,
  );
  const tour = params.get('tour') === '1';
  const [tutorialRun, setTutorialRun] = useState(0);
  const entryKey = `${owner}:${tour}:${tutorialRun}`;
  const [readyEntry, setReadyEntry] = useState<string | null>(null);
  useEffect(() => {
    if (readyEntry === entryKey) return;
    let active = true;
    if (tour) {
      // Gate the workspace before mounting any stale detail/mobile modal.
      useGraphUiStore.getState().closeEvidence();
      useGraphUiStore.getState().setTutorialStep(1);
      useAiChatStore.getState().close();
      // 소셜 계정 연결에서 돌아온 결과(?social=)는 알려진 값만 남겨 튜토리얼 중·뒤에도 계정 메뉴가 알린다.
      const social = readSocialLinkResult(`?${params}`);
      const tourQuery: Record<string, string> = {
        mode: 'all',
        tour: '1',
        ...(social ? { social } : {}),
      };
      const normalized =
        [...params.keys()].length === Object.keys(tourQuery).length &&
        Object.entries(tourQuery).every(
          ([key, value]) => params.getAll(key).join() === value,
        );
      if (!normalized)
        updateQuery(
          {
            ...Object.fromEntries([...params.keys()].map((key) => [key, null])),
            ...tourQuery,
          },
          { replace: true },
        );
    }
    void Promise.resolve().then(() => {
      if (active) setReadyEntry(entryKey);
    });
    return () => {
      active = false;
    };
  }, [entryKey, readyEntry, tour, params, updateQuery]);
  const inherited = useContext(GraphAppearanceContext);
  const theme = useColorTheme();
  const appearance = useMemo<GraphAppearance>(
    () => inherited ?? { variant: 'improved', theme },
    [inherited, theme],
  );
  return (
    <GraphAppearanceContext value={appearance}>
      {tour && readyEntry !== entryKey ? (
        <p role="status">튜토리얼 지도를 준비하고 있어요.</p>
      ) : (
        <MapWorkspace
          appearance={appearance}
          onStartTutorial={() => {
            setTutorialRun((run) => run + 1);
            updateQuery({ tour: '1' });
          }}
        />
      )}
    </GraphAppearanceContext>
  );
}

function MapWorkspace({
  appearance,
  onStartTutorial,
}: {
  appearance: GraphAppearance;
  onStartTutorial: () => void;
}) {
  const { params, updateQuery } = useRouteQuery();
  // FS065 계측: 메인 지도 노출 1회와 노드 선택. 노출 중 선택 여부는 viewId로 묶는다.
  const viewId = useScreenView('main');
  // 회원 세션의 회원 ID(쿠키 세션). 비회원·세션 없음은 null
  const { checking } = useAuth();
  const token = useAuthStore(selectMemberId);
  const revision = useAuthStore((state) => state.sessionRevision);
  const memoryOwner = `${token ?? 'guest'}:${revision}`;
  const prefetch = useRef<GraphPrefetch | null>(null);
  const modeSequence = useRef(0);
  const [switching, setSwitching] = useState<MapMode | null>(null);
  const [transitionNotice, setTransitionNotice] = useState('');
  const evidenceTarget = useGraphUiStore((state) => state.evidenceTarget);
  const evidenceOpen = Boolean(evidenceTarget);
  const [evidenceSelection, setEvidenceSelection] = useState<{
    target: GraphTarget;
    evidenceId: string;
    eventIds: string[];
  } | null>(null);
  // 근거 창이 닫히면 지도에서 보기 선택도 버린다. 같은 대상을 다시 열어도 예전 강조가 살아나지 않는다.
  if (!evidenceTarget && evidenceSelection) setEvidenceSelection(null);
  const [centeredEvidence, setCenteredEvidence] = useState<string | null>(null);
  const isolatedOpen = params.get('select') === 'bundle:isolated';
  const paramsKey = params.toString();
  useEffect(() => {
    const sequence = ++modeSequence.current;
    void Promise.resolve().then(() => {
      if (sequence === modeSequence.current) setSwitching(null);
    });
    return () => {
      modeSequence.current += 1;
    };
  }, [paramsKey, memoryOwner]);
  const [retry, setRetry] = useState(0);
  const [notice, setNotice] = useState('');
  const [sidebarPreference, setSidebarPreference] = useState(
    readSidebarPreference,
  );
  const [companyPanelWidth, setCompanyPanelWidth] = useState(
    readCompanyPanelWidth,
  );
  const [wideViewport, setWideViewport] = useState(
    () =>
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(min-width: 1600px)').matches,
  );
  const sidebarOpen = sidebarPreference ?? wideViewport;
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia('(min-width: 1600px)');
    const changed = (event: MediaQueryListEvent) =>
      setWideViewport(event.matches);
    query.addEventListener?.('change', changed);
    return () => query.removeEventListener?.('change', changed);
  }, []);
  const [watchSync, setWatchSync] = useState<WatchSync | null>(null);
  const [missingCompany, setMissingCompany] = useState<{
    id: string;
    owner: string;
  } | null>(null);
  function changeSidebar(open: boolean) {
    setSidebarPreference(open);
    try {
      localStorage.setItem(SIDEBAR_KEY, open ? '1' : '0');
    } catch {
      /* Keep this visit's preference. */
    }
  }
  function maxCompanyPanelWidth(handle: HTMLElement) {
    const bodyWidth = handle.parentElement?.getBoundingClientRect().width ?? 0;
    if (bodyWidth === 0) return COMPANY_PANEL_MAX_WIDTH;
    const holdingsWidth =
      document.getElementById('holdings-sidebar')?.getBoundingClientRect()
        .width ?? 0;
    return Math.max(
      COMPANY_PANEL_MIN_WIDTH,
      Math.min(COMPANY_PANEL_MAX_WIDTH, bodyWidth - holdingsWidth - 300),
    );
  }
  function changeCompanyPanelWidth(
    width: number,
    max = COMPANY_PANEL_MAX_WIDTH,
  ) {
    const next = Math.round(
      Math.min(max, Math.max(COMPANY_PANEL_MIN_WIDTH, width)),
    );
    setCompanyPanelWidth(next);
    try {
      localStorage.setItem(COMPANY_PANEL_WIDTH_KEY, String(next));
    } catch {
      /* Keep this visit's preference. */
    }
  }
  function resizeCompanyPanel(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.buttons === 0) return;
    const body = event.currentTarget.parentElement;
    if (!body) return;
    changeCompanyPanelWidth(
      body.getBoundingClientRect().right - event.clientX,
      maxCompanyPanelWidth(event.currentTarget),
    );
  }
  function handleCompanyPanelResizeKeyDown(
    event: ReactKeyboardEvent<HTMLDivElement>,
  ) {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    const delta = event.key === 'ArrowLeft' ? 16 : -16;
    changeCompanyPanelWidth(
      companyPanelWidth + delta,
      maxCompanyPanelWidth(event.currentTarget),
    );
  }
  const [collapsedPath, setCollapsedPath] = useState<string | null>(null);
  const [filterHost, setFilterHost] = useState<HTMLDivElement | null>(null);
  const [centerRequest, setCenterRequest] = useState<{
    id: string;
    seq: number;
  } | null>(null);
  const [tutorialSaving, setTutorialSaving] = useState(false);
  const [tutorialError, setTutorialError] = useState('');
  const openAi = useAiChatStore((state) => state.open);
  const tutorialStep = useGraphUiStore((state) => state.tutorialStep);
  const setTutorialStep = useGraphUiStore((state) => state.setTutorialStep);
  const tutorialOpen = params.get('tour') === '1';
  // MapPage gates and remounts this workspace for every tutorial entry.
  // Keeping the practice flag local therefore resets it without a render-time
  // or effect-driven state update.
  const [tutorialPanReady, setTutorialPanReady] = useState(false);
  useTutorialInteractionLock(
    tutorialOpen ? tutorialStep : null,
    tutorialPanReady,
  );
  const desiredMode: MapMode =
    params.get('mode') === 'personal' ? 'personal' : 'all';
  const requestedMode = tutorialOpen
    ? 'all'
    : desiredMode === 'personal' && !token
      ? 'all'
      : desiredMode;
  const filter = tutorialOpen
    ? 'all'
    : readFilter(params.get('scope') ?? sessionStorage.getItem(FILTER_KEY));
  const companyId = params.get('companyId') ?? undefined;
  const historical =
    !tutorialOpen && companyId && exactTime(params.get('asOf'));
  const asOf = historical ? params.get('asOf')! : undefined;
  const graphVersion = historical
    ? (params.get('graphVersion') ?? undefined)
    : undefined;
  const detailEventId = params.get('event');
  const historicalImpact = useCompanyResource<Impact>(
    historical && detailEventId
      ? companyUrl(
          companyId!,
          `/issues/${encodeURIComponent(detailEventId)}/impact`,
          { asOf, graphVersion },
        )
      : null,
  );
  const impactParts = params.get('impact')?.split(',') ?? [];
  const impactCompanyId = impactParts.length === 2 ? impactParts[0] : null;
  const impactIssueId = impactParts.length === 2 ? impactParts[1] : null;
  const returnTo = params.get('returnTo');
  const round =
    !tutorialOpen && requestedMode === 'all'
      ? (params.get('round') ?? undefined)
      : undefined;
  const { data, error, loading, unavailableReason } = useGraphData(
    {
      mode: requestedMode,
      personalFilter: filter,
      companyId: tutorialOpen ? undefined : companyId,
      asOf: tutorialOpen ? undefined : asOf,
      graphVersion: tutorialOpen ? undefined : graphVersion,
      depth: tutorialOpen ? 1 : params.get('depth') === '2' ? 2 : 1,
      round: tutorialOpen ? undefined : round,
    },
    token,
    retry,
    prefetch,
  );
  // 저장본을 일시적으로 읽지 못한 경우만 다시 확인할 수 있다. 미기록·중단·
  // 미발행·대상 비공개는 같은 요청을 반복해도 달라지지 않는 회차 상태다.
  const graphErrorRetryable =
    !unavailableReason || unavailableReason === 'snapshot_unavailable';
  const appliedMode = data?.metadata.mode ?? 'all';
  const target = useMemo(
    () =>
      tutorialOpen && !loading && !error ? tutorialTarget(data, true) : null,
    [tutorialOpen, loading, error, data],
  );
  const tutorialInstruction =
    !data || loading
      ? '실제 관계 지도를 불러오고 있어요.'
      : error
        ? '지도를 불러오지 못했어요. 아래 다시 시도로 실제 데이터를 불러오거나 건너뛰어 주세요.'
        : !target
          ? '현재 실제 지도에 안내할 기업·사건 연결이 없어요. 다시 불러오거나 튜토리얼을 건너뛸 수 있어요.'
          : tutorialStep === 1
            ? tutorialPanReady
              ? '이동했어요! 휠을 움직이거나 왼쪽 아래 확대·축소 버튼을 눌러 보세요.'
              : '점선으로 강조된 빈 공간을 누른 채 끌어 지도를 이동해 보세요.'
            : tutorialStep === 2
              ? `지도를 드래그하거나 확대·축소하며 살펴본 뒤 강조된 ${target.company.label} 기업 노드를 선택하세요.`
              : tutorialStep === 3
                ? `지도에서 강조된 「${target.issue.label}」 사건을 누르세요. ${target.company.label} 상세의 같은 사건을 눌러도 영향 경로를 열 수 있어요.`
                : tutorialStep === 4
                  ? '영향 경로 패널의 강조된 「근거 N건 보기」를 눌러 실제 기사·공시를 확인하세요.'
                  : '「AI에게 질문」 버튼으로 선택한 기업·사건을 질문에 연결할 수 있어요. 강조된 버튼을 누르면 AI 창을 열지 않고 튜토리얼을 마쳐요.';

  useEffect(() => {
    if (
      tutorialOpen ||
      !data ||
      loading ||
      error ||
      data.metadata.mode !== requestedMode ||
      round
    )
      return;
    const saved = readModeEntry(memoryOwner, data.metadata.mode);
    saveModeEntry(memoryOwner, data.metadata.mode, {
      url: `/?${paramsKey}`,
      view: saved?.view ?? emptyView(),
    });
  }, [
    data,
    loading,
    error,
    requestedMode,
    memoryOwner,
    paramsKey,
    round,
    tutorialOpen,
  ]);
  const stats = data ? graphSummary(data) : null;
  const rawSelection = params.get('select');
  const pathParts = params.get('path')?.split(',') ?? [];
  const pathFrom = pathParts[0] || null;
  const pathTo = pathParts.length === 2 ? pathParts[1] || null : null;
  const pathIsCollapsed =
    !tutorialOpen && Boolean(pathFrom) && collapsedPath === params.get('path');
  const displayedPath =
    data && !loading && !error && pathFrom && pathTo
      ? companyPath(data, pathFrom, pathTo)
      : null;
  const activeEvidence =
    evidenceSelection?.target === evidenceTarget &&
    data &&
    (!evidenceTarget?.mapContext?.graphVersion ||
      evidenceTarget.mapContext.graphVersion === data.metadata.graphVersion) &&
    (!evidenceTarget?.mapContext?.asOf ||
      Date.parse(evidenceTarget.mapContext.asOf) ===
        Date.parse(data.metadata.asOf))
      ? evidenceSelection
      : null;
  const evidenceEdges =
    activeEvidence && data
      ? data.edges
          .filter((edge) =>
            edge.evidenceIds.includes(activeEvidence.evidenceId),
          )
          .map((edge) => edge.id)
      : [];
  const evidenceFallback =
    activeEvidence && !evidenceEdges.length
      ? (activeEvidence.eventIds.find((id) =>
          data?.nodes.some((node) => node.id === id),
        ) ?? null)
      : null;
  const edgeId = rawSelection?.startsWith('edge:')
    ? rawSelection.slice(5) || null
    : null;
  const selectedId = rawSelection?.startsWith('node:')
    ? rawSelection.slice(5) || null
    : null;
  const selectedNode =
    data?.nodes.find((node) => node.id === selectedId) ?? null;
  const companyNode = selectedNode?.kind === 'company' ? selectedNode : null;
  const eventId =
    selectedId &&
    (data || (!round && !loading)) &&
    selectedNode?.kind !== 'company'
      ? selectedId
      : null;
  const mapRegion = useRef<HTMLElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const previousEvent = useRef<string | null>(null);
  const selectedPanel =
    (isolatedOpen ? '__isolated__' : null) ??
    pathFrom ??
    impactIssueId ??
    eventId ??
    edgeId ??
    companyNode?.id ??
    null;
  const focusId = params.get('focus');
  // D-GRP-01 [흐름 순으로 정렬]. 주소(?arrange=flow)에 남겨 새로 고침·공유에도 유지한다.
  const flowOrder = params.get('arrange') === 'flow';
  const focusHops: 1 | 2 = params.get('hops') === '2' ? 2 : 1;
  const focusNode = data?.nodes.find((node) => node.id === focusId) ?? null;
  // 15번: 근거 강조는 보고 있던 중심 보기를 유지하되, 강조할 선·사건이 중심 보기 밖이면
  // 강조하는 동안만 전체 지도로 보인다. 주소의 focus는 그대로라 창을 닫으면 중심 보기로 돌아온다.
  const evidenceEdgeNodes = data
    ? data.edges
        .filter((edge) => evidenceEdges.includes(edge.id))
        .flatMap((edge) => [edge.source, edge.target])
    : [];
  const evidenceNodes = evidenceFallback
    ? [evidenceFallback]
    : evidenceEdgeNodes;
  const focusShown =
    data && !pathFrom && focusId
      ? focusNeighborhood(data, focusId, focusHops)
      : null;
  const evidenceOutsideFocus = Boolean(
    focusShown?.size && evidenceNodes.some((id) => !focusShown.has(id)),
  );
  // 강조한 선이 화면 밖에 있을 수 있어 첫 선으로 지도를 옮긴다(사건만 강조하면 선택이 옮긴다).
  const evidenceCenter = evidenceEdgeNodes[0] ?? null;
  const evidenceKey = activeEvidence
    ? `${activeEvidence.evidenceId}:${evidenceOutsideFocus}`
    : null;
  if (evidenceKey !== centeredEvidence) {
    setCenteredEvidence(evidenceKey);
    if (evidenceKey && evidenceCenter)
      setCenterRequest((old) => ({
        id: evidenceCenter,
        seq: (old?.seq ?? 0) + 1,
      }));
  }
  const logoOf = (companyId: string) =>
    data?.nodes.find((node) => node.id === companyId)?.logoUrl;
  useEffect(() => {
    if (tutorialOpen && tutorialStep === null) setTutorialStep(1);
    if (!tutorialOpen && tutorialStep !== null) setTutorialStep(null);
  }, [setTutorialStep, tutorialOpen, tutorialStep]);
  const tutorialOwner = useRef(memoryOwner);
  useEffect(() => {
    if (tutorialOwner.current === memoryOwner) return;
    tutorialOwner.current = memoryOwner;
    setTutorialStep(tutorialOpen ? 1 : null);
    if (tutorialOpen)
      updateQuery({ select: null, impact: null, path: null, focus: null });
  }, [memoryOwner, tutorialOpen, setTutorialStep, updateQuery]);
  // FS015: 튜토리얼을 마치거나 건너뛰지 않은 회원은 지도에 들어오면 한 번 자동으로 연다.
  // 완료·건너뛰기는 PUT /api/v1/auth/tutorial로 계정에 저장되어 다음부터는 열지 않는다.
  const tutorialPending = useAuthStore(
    (state) =>
      state.session?.kind === 'member' &&
      state.session.setup?.tutorialCompleted === false,
  );
  const tutorialMemberId = useAuthStore(selectMemberId);
  const autoTutorial = useRef({ memberId: tutorialMemberId, opened: false });
  useEffect(() => {
    if (autoTutorial.current.memberId !== tutorialMemberId)
      autoTutorial.current = { memberId: tutorialMemberId, opened: false };
    // 이번 방문에 이미 열렸던 튜토리얼(주소의 tour=1 포함)은 닫은 뒤 다시 자동으로 열지 않는다.
    if (tutorialOpen) autoTutorial.current.opened = true;
    if (!tutorialPending || autoTutorial.current.opened) return;
    autoTutorial.current.opened = true;
    updateQuery({ tour: '1' }, { replace: true });
  }, [tutorialMemberId, tutorialPending, tutorialOpen, updateQuery]);
  useEffect(() => {
    if (previousEvent.current && !selectedPanel) {
      (opener.current?.isConnected
        ? opener.current
        : mapRegion.current
      )?.focus();
    }
    previousEvent.current = selectedPanel;
  }, [selectedPanel]);
  const relatedCompanies = useMemo(() => {
    if (!data || !companyNode) return [];
    const counts = new Map<string, number>();
    data.edges.forEach((edge) => {
      if (edge.relationType !== 'SHARES_ISSUE') return;
      const otherId =
        edge.source === companyNode.id
          ? edge.target
          : edge.target === companyNode.id
            ? edge.source
            : null;
      if (
        otherId &&
        data.nodes.some(
          (node) => node.id === otherId && node.kind === 'company',
        )
      )
        counts.set(otherId, new Set(edge.via).size);
    });
    return [...counts.entries()]
      .map(([id, sharedIssueCount]) => ({
        id,
        name: data.nodes.find((node) => node.id === id)?.label ?? id,
        sharedIssueCount,
      }))
      .sort((a, b) => b.sharedIssueCount - a.sharedIssueCount);
  }, [companyNode, data]);
  const selectNode = (id: string | null) => {
    if (tutorialOpen && tutorialStep && tutorialStep < 5) {
      if (!id) return;
      else {
        if (tutorialStep === 3 && target && id === target.issue.id) {
          openImpact(target.company.id, target.issue.id);
          return;
        }
        if (tutorialStep === 1 || id !== target?.company.id) return;
        if (tutorialStep === 2) {
          setTutorialStep(3);
          setCenterRequest((old) => ({ id, seq: (old?.seq ?? 0) + 1 }));
        }
      }
    }
    if (pathFrom && !id) {
      updateQuery({ path: null, select: null });
      return;
    }
    if (
      pathFrom &&
      id &&
      data?.nodes.some((node) => node.id === id && node.kind === 'company')
    ) {
      if (id !== pathFrom)
        updateQuery({ path: `${pathFrom},${id}`, select: null });
      return;
    }
    if (
      id &&
      document.activeElement instanceof HTMLElement &&
      !document.activeElement.closest('.event-panel')
    )
      opener.current = mapRegion.current?.contains(document.activeElement)
        ? document.activeElement
        : null;
    updateQuery({
      select: id ? `node:${id}` : null,
      id: null,
      impact: null,
    });
    if (id) track({ type: 'graph_node_select', targetId: id, viewId });
  };
  const eventContext = {
    round: tutorialOpen ? undefined : round,
    graphVersion: data?.metadata.graphVersion ?? undefined,
    asOf: data?.metadata.asOf ?? undefined,
  };
  const impact = useImpactPath(
    data && !loading && !error ? impactCompanyId : null,
    data && !loading && !error ? impactIssueId : null,
    eventContext,
    tutorialOpen &&
      target?.company.id === impactCompanyId &&
      target?.issue.id === impactIssueId
      ? target.edge.id
      : undefined,
  );
  function selectEdge(id: string) {
    if (
      document.activeElement instanceof HTMLElement &&
      mapRegion.current?.contains(document.activeElement)
    )
      opener.current = document.activeElement;
    updateQuery({ select: `edge:${id}`, id: null, impact: null, path: null });
    track({ type: 'graph_edge_select', targetId: id, viewId });
  }
  useEffect(() => {
    if (
      tutorialOpen &&
      tutorialStep === 3 &&
      impactCompanyId === target?.company.id &&
      impactIssueId === target?.issue.id &&
      !impact.loading &&
      !impact.error &&
      impact.data?.companyId === target?.company.id &&
      impact.data?.issueId === target?.issue.id &&
      impact.data?.steps.some((step) => step.id === target?.company.id) &&
      impact.data?.steps.some((step) => step.id === target?.issue.id)
    )
      setTutorialStep(4);
  }, [
    tutorialOpen,
    tutorialStep,
    impactCompanyId,
    impactIssueId,
    target,
    impact.loading,
    impact.error,
    impact.data,
    setTutorialStep,
  ]);
  function relationAction(
    action: 'evidence' | 'ai',
    relation: RelationDetail,
    issueId?: string,
    supplyLink?: StructuralSupplyLink,
  ) {
    const issue = relation.via.find((item) => item.id === issueId);
    const target: GraphTarget = {
      kind: issue ? 'issue' : 'edge',
      id: issue?.id ?? relation.id,
      label:
        issue?.title ?? `${relation.source.label} – ${relation.target.label}`,
      evidenceIds:
        supplyLink?.evidenceIds ?? issue?.evidenceIds ?? relation.evidenceIds,
      verifiedAt: supplyLink
        ? supplyLink.verifiedAt
        : issue
          ? null
          : (relation.basis
              .map((basis) => basis.verifiedAt)
              .filter((value): value is string => Boolean(value))
              .sort()
              .at(-1) ?? null),
      mapContext: {
        ...eventContext,
        graphVersion: relation.metadata.graphVersion ?? undefined,
        asOf: relation.metadata.asOf,
        url: `/?${params}`,
      },
    };
    if (action === 'evidence') useGraphUiStore.getState().openEvidence(target);
    else openAi(target);
  }
  /**
   * D-AI-02 "지도에서 보기": 답변을 만든 스냅샷(그래프 버전과 질문에 명시된 기준 시각)으로 연다.
   * - 지금 지도가 같은 버전·같은 기준 시각이고 대상 노드가 있으면 그 자리에서 초점을 맞춘다.
   * - 아니면 기업 대상이고 명시된 시각이 있을 때만 그 버전·시각의 기업 지도로 이동하며, 이전 사건·영향·회차 선택은 지운다.
   * - 그 밖(사건·관계, 시각 없이 버전만 고정된 답변)은 지금 지도가 그 스냅샷을 열 수 없으므로 false: 시각을 지어내지 않는다.
   */
  function viewAnswerTarget(target: AnswerMapTarget) {
    const shownVersion = data?.metadata.graphVersion ?? null;
    const sameSnapshot =
      (!target.graphVersion || target.graphVersion === shownVersion) &&
      (target.asOf ?? null) === (asOf ?? null);
    if (sameSnapshot) {
      if (!data?.nodes.some((node) => node.id === target.id)) return false;
      updateQuery({ focus: target.id, hops: '1', path: null });
      return true;
    }
    if (target.kind === 'company' && target.graphVersion && target.asOf) {
      updateQuery({
        companyId: target.id,
        asOf: target.asOf,
        graphVersion: target.graphVersion,
        select: `node:${target.id}`,
        focus: null,
        hops: null,
        path: null,
        event: null,
        impact: null,
        round: null,
        id: null,
      });
      return true;
    }
    return false;
  }
  function eventAction(action: EventAction, event: EventDetail) {
    const target: GraphTarget = {
      kind: 'issue',
      id: event.id,
      label: event.title,
      evidenceIds: event.evidenceIds,
      mapContext: {
        ...eventContext,
        graphVersion: event.metadata.graphVersion ?? undefined,
        asOf: event.metadata.asOf,
        url: `/?${params}`,
      },
    };
    if (action === 'evidence') useGraphUiStore.getState().openEvidence(target);
    if (action === 'ai') useAiChatStore.getState().open(target);
    if (action === 'focus') updateQuery({ focus: event.id, hops: '1' });
  }
  function openImpact(companyId: string, issueId: string) {
    if (
      tutorialOpen &&
      tutorialStep === 3 &&
      (companyId !== target?.company.id || issueId !== target?.issue.id)
    )
      return;
    updateQuery({
      select: `node:${companyId}`,
      impact: `${companyId},${issueId}`,
      focus: null,
      hops: null,
    });
  }
  function impactTarget(evidenceIds?: string[]): GraphTarget {
    return {
      kind: 'path',
      id: `${impactCompanyId},${impactIssueId}`,
      label: `${focusNode?.label ?? companyNode?.label ?? impactCompanyId} 영향 경로`,
      evidenceIds,
      mapContext: { ...eventContext, url: `/?${params}` },
    };
  }
  async function closeTutorial() {
    if (tutorialSaving) return;
    setTutorialError('');
    if (token) {
      setTutorialSaving(true);
      try {
        await setTutorialCompleted(true);
      } catch {
        setTutorialError('튜토리얼 완료 상태를 저장하지 못했습니다.');
        setTutorialSaving(false);
        return;
      }
      setTutorialSaving(false);
    }
    setTutorialStep(null);
    updateQuery({ tour: null });
  }
  const loginNeeded =
    !tutorialOpen &&
    !checking &&
    !token &&
    (desiredMode === 'personal' || notice === 'login');
  async function changeMode(mode: MapMode, targetCompany?: string) {
    if (mode === 'personal' && !token) {
      setNotice('login');
      return;
    }
    if (mode === appliedMode && !switching) return;
    const sequence = ++modeSequence.current;
    const sessionRevision = useAuthStore.getState().sessionRevision;
    const savedCurrent = readModeEntry(memoryOwner, appliedMode);
    saveModeEntry(memoryOwner, appliedMode, {
      url: `/?${params}`,
      view: savedCurrent?.view ?? emptyView(),
    });
    const saved = readModeEntry(memoryOwner, mode);
    const storedParams = saved
      ? new URL(saved.url, 'http://localhost').searchParams
      : null;
    const nextFilter = readFilter(
      storedParams?.get('scope') ?? sessionStorage.getItem(FILTER_KEY),
    );
    const request = { mode, personalFilter: nextFilter, depth: 1 as const };
    setSwitching(mode);
    setTransitionNotice('');
    try {
      const nextGraph = await getGraph(request);
      if (
        nextGraph.metadata.mode !== mode ||
        (mode === 'personal' &&
          nextGraph.metadata.personalFilter !== nextFilter)
      )
        throw new Error('요청한 모드와 범위가 다른 응답입니다.');
      if (
        sequence !== modeSequence.current ||
        sessionRevision !== useAuthStore.getState().sessionRevision
      )
        return;
      const restored = restoreTargets(saved, nextGraph);
      const targetFound =
        targetCompany &&
        nextGraph.nodes.some(
          (node) => node.id === targetCompany && node.kind === 'company',
        );
      prefetch.current = {
        key: graphRequestKey(request, token),
        data: nextGraph,
      };
      setNotice(targetCompany && !targetFound ? 'holding-missing-all' : '');
      setSwitching(null);
      setTransitionNotice(
        restored.dropped
          ? '전에 고른 대상이 이 지도에 없어 해당 선택을 해제했습니다.'
          : '',
      );
      updateQuery({
        mode,
        scope: mode === 'personal' ? nextFilter : null,
        ...restored.changes,
        ...(targetCompany
          ? {
              select: targetFound ? `node:${targetCompany}` : null,
              focus: null,
              hops: null,
              path: null,
              impact: null,
            }
          : {}),
        id: null,
        round: null,
        companyId: null,
        asOf: null,
        graphVersion: null,
        event: null,
        tour: null,
      });
      if (targetFound)
        setCenterRequest((request) => ({
          id: targetCompany!,
          seq: (request?.seq ?? 0) + 1,
        }));
    } catch (failure) {
      if (
        sequence !== modeSequence.current ||
        sessionRevision !== useAuthStore.getState().sessionRevision
      )
        return;
      setSwitching(null);
      setTransitionNotice(
        `지도 전환 실패. 현재 지도와 선택을 유지합니다. ${failure instanceof Error ? failure.message : ''}`,
      );
    }
  }
  // FS027: 사이드바·기업 상세 어느 쪽에서 관심을 저장해도 두 화면을 같은 목록으로 맞추고,
  // 개인화 지도는 저장 뒤 목록으로 다시 조회한다. 저장 전에 받아 둔 개인화 응답은 쓰지 않는다.
  function watchSaved(watchlistIds: string[]) {
    setWatchSync((sync) => ({ ids: watchlistIds, seq: (sync?.seq ?? 0) + 1 }));
    prefetch.current = null;
    // 개인화 전환 조회가 진행 중이면 그 응답을 버리고 저장 뒤 목록으로 다시 전환한다.
    if (switching === 'personal') {
      void changeMode('personal');
      return;
    }
    if (appliedMode === 'personal' || requestedMode === 'personal')
      setRetry((value) => value + 1);
  }
  function changeFilter(scope: PersonalScope) {
    sessionStorage.setItem(FILTER_KEY, scope);
    updateQuery({
      mode: 'personal',
      scope,
      select: null,
      id: null,
      impact: null,
      path: null,
    });
  }
  return (
    <div
      data-tutorial-ai-focus={tutorialOpen && tutorialStep === 5}
      className={`${mapAppearanceStyles(appearance)} relationship-map min-w-0! max-md:[&_.relationship-graph-filters_button]:min-h-10! max-md:[&_.relationship-graph-filters_button]:min-w-10! [&_.relationship-toolbar]:overflow-x-auto [&_.relationship-toolbar]:max-w-full max-md:min-h-0! max-md:[&_.relationship-header]:h-auto! max-md:[&_.relationship-header]:flex-wrap! max-md:[&_.relationship-header]:gap-2! max-md:[&_.relationship-header]:px-3.5! max-md:[&_.relationship-header]:py-2! max-md:[&_.relationship-header_nav]:order-last max-md:[&_.relationship-header_nav]:w-full max-md:[&_.relationship-header_nav]:h-10! max-md:[&_.relationship-header_nav]:flex! max-md:[&_.relationship-header_nav]:overflow-y-hidden! max-md:[&_.relationship-header_nav>*]:shrink-0 max-md:[&_.relationship-header_nav]:overflow-x-auto max-md:[&_.relationship-toolbar]:max-w-full max-md:[&_.relationship-toolbar]:overflow-x-auto [&_.relationship-canvas]:min-h-0! max-md:[&_.relationship-body]:min-h-0! max-md:[&_.relationship-body]:px-1!`}
    >
      <SkipLink />
      {/* 지도는 화면 제목을 보이지 않게 둔다. 다른 메뉴 화면처럼 h1으로 화면 이름을 알린다. */}
      <h1 className="sr-only">지도</h1>
      <ServiceHeader />
      {tutorialOpen && (
        <p className="border-b border-zoop-line bg-zoop-soft px-4 py-2 text-xs max-md:hidden">
          실제 시장 전체 지도 · 삼성전자를 중심으로 안내합니다.
        </p>
      )}
      {returnTo?.startsWith('/companies/') && (
        <Link to={returnTo}>기업 상세로 돌아가기</Link>
      )}
      {historical && (
        <p className="border-l-2 border-zoop-faint bg-zoop-soft p-2 text-xs">
          기업 상세에서 선택한 시점 · {asOf} · {graphVersion ?? '버전 미제공'}
        </p>
      )}
      {historicalImpact.error && (
        <p role="alert">
          {historicalImpact.errorCode === 'VERSION_UNAVAILABLE'
            ? '사건 시점의 그래프 버전을 사용할 수 없어요. 관계를 임의 강조하지 않았어요.'
            : '영향 경로 조회 실패. 관계를 임의 강조하지 않았어요.'}
          {historicalImpact.errorRetryable !== false &&
            historicalImpact.errorCode !== 'VERSION_UNAVAILABLE' && (
              <button onClick={historicalImpact.retry}>
                영향 경로 다시 조회
              </button>
            )}
        </p>
      )}
      {round && <BriefingSnapshotBanner roundId={round} />}
      <main
        id="service-main"
        tabIndex={-1}
        className="relationship-main motion-safe:animate-service-enter"
      >
        <section
          ref={mapRegion}
          tabIndex={-1}
          aria-label="관계 지도"
          className="relationship-view"
          data-screen-id={
            tutorialOpen
              ? `D-GRP-T${tutorialStep && tutorialStep > 1 ? tutorialStep : ''}`
              : pathFrom
                ? 'D-GRP-07'
                : impactIssueId
                  ? 'D-GRP-06'
                  : focusNode?.kind === 'company'
                    ? 'D-GRP-07b'
                    : edgeId
                      ? 'D-GRP-04'
                      : eventId
                        ? 'D-GRP-02'
                        : companyNode
                          ? 'D-GRP-03'
                          : appliedMode === 'personal'
                            ? 'D-GRP-01b'
                            : round
                              ? 'D-BRF-04'
                              : 'D-GRP-01'
          }
        >
          <div className="relationship-toolbar h-auto! min-h-12 overflow-y-hidden! py-1! [&>*]:shrink-0">
            <button
              className="relationship-sidebar-toggle"
              aria-expanded={sidebarOpen}
              aria-controls="holdings-sidebar"
              onClick={() => changeSidebar(!sidebarOpen)}
              title="보유·관심 종목 목록 보기"
              aria-label="내 종목 목록"
            >
              <GraphIcon name="sidebar" inheritColor />내 종목
            </button>
            <div className="relationship-mode" aria-label="그래프 모드">
              <button
                aria-pressed={appliedMode === 'all'}
                onClick={() => void changeMode('all')}
              >
                <GraphIcon name="globe" inheritColor />
                시장 전체
              </button>
              <button
                aria-pressed={appliedMode === 'personal'}
                onClick={() => void changeMode('personal')}
              >
                <GraphIcon name="personal" inheritColor />내 종목
              </button>
            </div>
            <span className="relationship-divider" />
            {appliedMode === 'personal' && (
              <div
                className="relationship-filters"
                aria-label="개인화 종목 범위"
              >
                {(['all', 'holdings', 'watchlist'] as const).map((scope, i) => (
                  <button
                    key={scope}
                    aria-pressed={filter === scope}
                    onClick={() => changeFilter(scope)}
                  >
                    {i > 0 && (
                      <GraphIcon
                        name={i === 1 ? 'holding' : 'watch'}
                        size={11}
                      />
                    )}
                    {['전체', '보유', '관심'][i]}
                    {i > 0 && (
                      <span>
                        {i === 1
                          ? (stats?.holding ?? '—')
                          : (stats?.watch ?? '—')}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}
            <div ref={setFilterHost} className="contents" />
            {appliedMode === 'all' && (
              <>
                <div
                  className="relationship-count"
                  title="전체 조회에는 개인 정보가 포함되지 않습니다."
                >
                  <GraphIcon name="holding" size={10} />
                  보유<span>—</span>
                </div>
                <div
                  className="relationship-count"
                  title="전체 조회에는 개인 정보가 포함되지 않습니다."
                >
                  <GraphIcon name="watch" size={11} />
                  관심<span>—</span>
                </div>
              </>
            )}
            <div className="relationship-toolbar-help">
              <button
                onClick={() => setNotice(notice === 'info' ? '' : 'info')}
                aria-label="지도 데이터 안내"
                className="max-md:min-h-10 max-md:min-w-10"
              >
                <GraphIcon name="info" size={19} />
              </button>
              <button
                onClick={onStartTutorial}
                aria-label="튜토리얼 다시 보기"
                className="max-md:min-h-10 max-md:min-w-10"
              >
                <GraphIcon name="help" size={19} />
              </button>
            </div>
          </div>
          <div
            className={`relationship-body${selectedPanel ? ` has-company-panel ${pathIsCollapsed ? '' : 'max-md:pb-[48dvh]!'}` : ''}${tutorialOpen || sidebarOpen ? ' flex! gap-3! max-sm:flex-col [&>.relationship-canvas]:min-w-0 [&>.relationship-canvas]:flex-1 [&>.relationship-canvas]:w-auto' : ''}`}
            aria-busy={loading}
          >
            {sidebarOpen && (
              <div id="holdings-sidebar" className="flex min-h-0 max-sm:w-full">
                <HoldingsSidebar
                  key={memoryOwner}
                  member={Boolean(token)}
                  graph={!loading && !error ? data : null}
                  watchSync={watchSync}
                  onWatchChanged={watchSaved}
                  logoOf={(id) =>
                    companyLogo(
                      id,
                      data?.nodes.find((node) => node.id === id)?.logoUrl,
                    )
                  }
                  onPick={(id) => {
                    if (!data || loading || error) {
                      setNotice('graph-not-ready');
                      return;
                    }
                    if (!data?.nodes.some((node) => node.id === id)) {
                      setMissingCompany({ id, owner: memoryOwner });
                      setNotice('holding-missing');
                      return;
                    }
                    setNotice('');
                    if (tutorialOpen) {
                      selectNode(id);
                      return;
                    }
                    // 상세를 닫으면 고른 사이드바 행으로 포커스를 돌려준다.
                    if (document.activeElement instanceof HTMLElement)
                      opener.current = document.activeElement;
                    updateQuery({
                      select: `node:${id}`,
                      id: null,
                      focus: null,
                      hops: null,
                      path: null,
                      impact: null,
                    });
                    track({ type: 'graph_node_select', targetId: id, viewId });
                    setCenterRequest((request) => ({
                      id,
                      seq: (request?.seq ?? 0) + 1,
                    }));
                  }}
                  onClose={() => changeSidebar(false)}
                />
              </div>
            )}
            {data ? (
              <GraphCanvas
                data={data}
                onPersonalFilter={changeFilter}
                onMarket={() => void changeMode('all')}
                filterHost={filterHost}
                tutorialLocked={Boolean(
                  tutorialOpen && tutorialStep && tutorialStep < 5,
                )}
                tutorialCameraEnabled={tutorialOpen && tutorialStep === 2}
                tutorialShowNeighborhood={tutorialOpen && tutorialStep === 3}
                centerRequest={centerRequest}
                tutorialCenterId={tutorialOpen ? target?.company.id : undefined}
                memoryOwner={
                  tutorialOpen
                    ? `${memoryOwner}:tutorial`
                    : round
                      ? `${memoryOwner}:round:${round}`
                      : historical
                        ? `${memoryOwner}:asOf:${asOf}`
                        : memoryOwner
                }
                tutorialPhase={
                  tutorialOpen && tutorialStep === 1
                    ? tutorialPanReady
                      ? 'zoom'
                      : 'pan'
                    : undefined
                }
                tutorialTargetId={
                  tutorialOpen && tutorialStep === 2
                    ? target?.company.id
                    : tutorialOpen && tutorialStep === 3
                      ? target?.issue.id
                      : undefined
                }
                onTutorialAction={(action) => {
                  if (!tutorialOpen || tutorialStep !== 1) return;
                  if (action === 'pan') setTutorialPanReady(true);
                  if (action === 'zoom' && tutorialPanReady) {
                    setTutorialStep(2);
                  }
                }}
                onOpenIsolated={() => {
                  updateQuery({
                    select: 'bundle:isolated',
                    impact: null,
                    path: null,
                  });
                }}
                selectedId={
                  activeEvidence
                    ? evidenceFallback
                    : (pathFrom ?? selectedId ?? detailEventId ?? companyId)
                }
                connectionPath={Boolean(pathFrom) && !activeEvidence}
                highlightedEdgeIds={
                  activeEvidence
                    ? evidenceEdges
                    : pathFrom
                      ? (displayedPath?.edgeIds ?? [])
                      : impactEdges(data, impact.data ?? historicalImpact.data)
                }
                selectedEdgeId={activeEvidence ? null : edgeId}
                isolateSelection={Boolean(activeEvidence && evidenceFallback)}
                evidenceMode={Boolean(activeEvidence)}
                onSelectEdge={selectEdge}
                onSelect={selectNode}
                focusId={
                  pathFrom || evidenceOutsideFocus
                    ? null
                    : (focusId ??
                      (historical ? (detailEventId ?? companyId) : null))
                }
                focusHops={focusHops}
                focusLayout={
                  !pathFrom && !evidenceOutsideFocus && Boolean(focusId)
                }
                flow={flowOrder}
                onFlowChange={(next) =>
                  updateQuery({ arrange: next ? 'flow' : null })
                }
              />
            ) : (
              <div className="relationship-canvas">
                <p className="relationship-message" role="status">
                  {loading
                    ? '관계 지도를 불러오는 중입니다.'
                    : unavailableReason === 'snapshot_not_recorded'
                      ? '이 회차의 그래프 저장본이 없습니다.'
                      : unavailableReason && !graphErrorRetryable
                        ? '이 회차의 관계 지도는 아직 제공하지 않아요.'
                        : '관계 지도를 불러오지 못했습니다.'}
                </p>
              </div>
            )}
            {pathFrom && (pathIsCollapsed || Boolean(displayedPath)) && (
              <div
                role="group"
                aria-label="지도 경로"
                data-screen-id="D-GRP-07"
                className={`absolute top-2 left-2 z-20 flex max-w-[calc(100%-1rem)] flex-wrap items-center gap-1 rounded-lg border border-zoop-line bg-zoop-paper p-2 text-[13px] text-zoop-ink ${pathIsCollapsed ? '' : 'max-md:hidden'}`}
              >
                {data?.nodes
                  .filter((n) => n.id === pathFrom)
                  .map((n) => (
                    <CompanyLogo
                      key={n.id}
                      name={n.label}
                      logoUrl={n.logoUrl}
                      className="size-6 rounded-full bg-zoop-ink text-xs text-zoop-paper"
                    />
                  ))}
                <strong className="min-w-0 flex-1 truncate">
                  {data?.nodes.find((n) => n.id === pathFrom)?.label ??
                    '첫 기업'}{' '}
                  ⇆{' '}
                  {data?.nodes.find((n) => n.id === pathTo)?.label ??
                    '기업 선택'}
                  {displayedPath
                    ? ` · ${displayedPath.edgeIds.length}단계`
                    : ''}
                </strong>
                {data?.nodes
                  .filter((n) => n.id === pathTo)
                  .map((n) => (
                    <CompanyLogo
                      key={n.id}
                      name={n.label}
                      logoUrl={n.logoUrl}
                      className="size-6 rounded-full bg-zoop-ink text-xs text-zoop-paper"
                    />
                  ))}
                <button
                  className="min-h-11 rounded border border-zoop-line px-2"
                  onClick={() => {
                    setCollapsedPath(null);
                    requestAnimationFrame(() =>
                      document
                        .querySelector<HTMLElement>(
                          'aside[aria-label="두 기업 사이 경로"] h2',
                        )
                        ?.focus(),
                    );
                  }}
                >
                  경로 단계 보기
                </button>
                <button
                  className="min-h-11 rounded border border-zoop-line px-2"
                  onClick={() => updateQuery({ path: null })}
                >
                  경로 나가기
                </button>
              </div>
            )}
            {focusNode && !pathFrom && !evidenceOutsideFocus && (
              <GraphFocusControls
                label={focusNode.label}
                hops={focusHops}
                onHopsChange={(hops) => updateQuery({ hops: String(hops) })}
                onClear={() => updateQuery({ focus: null, hops: null })}
              />
            )}
            {tutorialOpen && tutorialStep && (
              <div
                className={`order-first shrink-0 ${selectedPanel ? 'max-md:hidden' : ''}`}
              >
                <GraphTutorial
                  step={tutorialStep}
                  practice
                  instruction={tutorialInstruction}
                  onReload={
                    !loading && data && !target
                      ? () => setRetry((v) => v + 1)
                      : undefined
                  }
                  saving={tutorialSaving}
                  error={tutorialError}
                  onStepChange={(step: GraphTutorialStep) => {
                    setTutorialError('');
                    setTutorialStep(step);
                  }}
                  onFinish={() => void closeTutorial()}
                  onSkip={() => void closeTutorial()}
                  onRetry={() => void closeTutorial()}
                />
              </div>
            )}
            {companyNode &&
              !impactIssueId &&
              !pathFrom &&
              !pathIsCollapsed &&
              !tutorialOpen && (
                <div
                  role="separator"
                  aria-label="기업 패널 너비 조절"
                  aria-controls="company-detail-panel"
                  aria-orientation="vertical"
                  aria-valuemin={COMPANY_PANEL_MIN_WIDTH}
                  aria-valuemax={COMPANY_PANEL_MAX_WIDTH}
                  aria-valuenow={companyPanelWidth}
                  aria-valuetext={`${companyPanelWidth}픽셀`}
                  tabIndex={0}
                  className="company-panel-resizer"
                  onPointerDown={(event) =>
                    event.currentTarget.setPointerCapture(event.pointerId)
                  }
                  onPointerMove={resizeCompanyPanel}
                  onKeyDown={handleCompanyPanelResizeKeyDown}
                />
              )}
            <MapDetailSheet
              tutorialLocked={Boolean(
                tutorialOpen && tutorialStep && tutorialStep < 5,
              )}
              open={Boolean(selectedPanel)}
              suspended={evidenceOpen || pathIsCollapsed}
              tutorial={
                tutorialOpen &&
                tutorialStep && (
                  <div className="shrink-0 border-b border-panel-line">
                    <GraphTutorial
                      compact
                      step={tutorialStep}
                      practice
                      instruction={tutorialInstruction}
                      onReload={
                        !loading && data && !target
                          ? () => setRetry((v) => v + 1)
                          : undefined
                      }
                      saving={tutorialSaving}
                      error={tutorialError}
                      onStepChange={(step: GraphTutorialStep) => {
                        setTutorialError('');
                        setTutorialStep(step);
                      }}
                      onFinish={() => void closeTutorial()}
                      onSkip={() => void closeTutorial()}
                      onRetry={() => void closeTutorial()}
                    />
                  </div>
                )
              }
              onClose={() => {
                selectNode(null);
                updateQuery({ select: null, impact: null, path: null });
              }}
            >
              {isolatedOpen && data && (
                <IsolatedIssuesPanel
                  issues={isolatedIssues(data)}
                  onClose={() => selectNode(null)}
                  onSelect={(id) => {
                    selectNode(id);
                  }}
                />
              )}
              {companyNode && !impactIssueId && !pathFrom && (
                <CompanyDetailPanel
                  key={companyNode.id}
                  companyId={companyNode.id}
                  panelWidth={companyPanelWidth}
                  companyDetailHref={(id) =>
                    companyDetailRouteFromMap(id, params.toString())
                  }
                  context={round || tutorialOpen ? eventContext : undefined}
                  fallback={companyNode}
                  relatedCompanies={relatedCompanies}
                  token={token}
                  watchSync={watchSync}
                  onWatchSaved={watchSaved}
                  onClose={() => selectNode(null)}
                  tutorialIssueId={
                    tutorialOpen && tutorialStep === 3
                      ? target?.issue.id
                      : undefined
                  }
                  onSelectIssue={(issueId) =>
                    openImpact(companyNode.id, issueId)
                  }
                  onFocus={() =>
                    updateQuery({ focus: companyNode.id, hops: '1' })
                  }
                  onSelectRelation={(companyId) => {
                    const edge = data?.edges.find(
                      (item) =>
                        item.relationType === 'SHARES_ISSUE' &&
                        ((item.source === companyNode.id &&
                          item.target === companyId) ||
                          (item.target === companyNode.id &&
                            item.source === companyId)),
                    );
                    if (edge) selectEdge(edge.id);
                  }}
                  onAskAi={() =>
                    tutorialOpen && tutorialStep === 5
                      ? void closeTutorial()
                      : openAi({
                          kind: 'company',
                          id: companyNode.id,
                          label: companyNode.label,
                          mapContext: { ...eventContext, url: `/?${params}` },
                        })
                  }
                  tutorialAi={tutorialOpen && tutorialStep === 5}
                  tutorialSaving={tutorialSaving}
                />
              )}
              {pathFrom && !tutorialOpen && (
                <button
                  className="min-h-11 w-full border-b border-zoop-line bg-zoop-paper px-4 text-left text-[13px] text-zoop-ink md:hidden"
                  onClick={() => setCollapsedPath(params.get('path'))}
                >
                  지도로 접기
                </button>
              )}
              {pathFrom && (
                <CompanyPathPanel
                  graph={data}
                  from={pathFrom}
                  to={pathTo}
                  loading={loading}
                  error={error}
                  unavailable={Boolean(error) && !graphErrorRetryable}
                  onRetry={() => setRetry((v) => v + 1)}
                  onClose={() => updateQuery({ path: null })}
                  onPick={(id) =>
                    updateQuery({
                      path: id ? `${pathFrom},${id}` : pathFrom,
                      select: null,
                    })
                  }
                  onSelectCompany={(id) =>
                    updateQuery({
                      path: null,
                      focus: null,
                      hops: null,
                      select: `node:${id}`,
                    })
                  }
                  onEvidence={(id) => {
                    const node = data?.nodes.find((n) => n.id === id);
                    const evidenceIds = [
                      ...new Set(
                        data?.edges
                          .filter((e) => e.source === id || e.target === id)
                          .flatMap((e) => e.evidenceIds) ?? [],
                      ),
                    ];
                    useGraphUiStore.getState().openEvidence({
                      kind: 'issue',
                      id,
                      label: node?.label ?? id,
                      evidenceIds,
                      mapContext: { ...eventContext, url: `/?${params}` },
                    });
                  }}
                />
              )}
              {data && impactCompanyId && impactIssueId && !pathFrom && (
                <ImpactPathPanel
                  companyId={impactCompanyId}
                  issueId={impactIssueId}
                  context={eventContext}
                  graph={data}
                  impact={impact.data}
                  loading={impact.loading}
                  error={impact.error}
                  errorCode={impact.errorCode}
                  errorStatus={impact.errorStatus}
                  retryable={impact.retryable}
                  onRetry={impact.retry}
                  onClose={() => {
                    if (tutorialOpen && tutorialStep === 4) setTutorialStep(3);
                    updateQuery({ impact: null });
                  }}
                  onViewIssue={() =>
                    updateQuery({
                      select: `node:${impactIssueId}`,
                      impact: null,
                    })
                  }
                  tutorialEvidence={tutorialOpen && tutorialStep === 4}
                  tutorialAi={tutorialOpen && tutorialStep === 5}
                  tutorialSaving={tutorialSaving}
                  onEvidence={(evidenceIds) =>
                    useGraphUiStore
                      .getState()
                      .openEvidence(impactTarget(evidenceIds))
                  }
                  onAskAi={() =>
                    tutorialOpen && tutorialStep === 5
                      ? void closeTutorial()
                      : openAi(impactTarget())
                  }
                />
              )}
              {eventId &&
                !pathFrom &&
                (round ? (
                  <BriefingRoundIssuePanel
                    key={`${round}:${eventId}`}
                    roundId={round}
                    eventId={eventId}
                    graphVersion={data?.metadata.graphVersion ?? null}
                    onClose={() => selectNode(null)}
                  />
                ) : (
                  <EventDetailPanel
                    key={eventId}
                    id={eventId}
                    companyDetailHref={(id) =>
                      companyDetailRouteFromMap(id, params.toString())
                    }
                    context={eventContext}
                    geography={selectedNode?.geography ?? null}
                    logoOf={logoOf}
                    onClose={() => selectNode(null)}
                    onAction={eventAction}
                  />
                ))}
              {edgeId && !pathFrom && (
                <RelationDetailPanel
                  key={edgeId}
                  id={edgeId}
                  context={eventContext}
                  logoOf={logoOf}
                  onClose={() => selectNode(null)}
                  onSelectNode={selectNode}
                  onAction={relationAction}
                />
              )}
            </MapDetailSheet>
            {(loading ||
              switching ||
              transitionNotice ||
              error ||
              loginNeeded ||
              notice ||
              data?.metadata.partial ||
              data?.metadata.truncated) && (
              <div
                className="relationship-notice"
                role={error && graphErrorRetryable ? 'alert' : 'status'}
              >
                {switching && (
                  <p role="status">
                    {switching === 'all' ? '시장 전체' : '내 종목'} 지도 전환
                    중… 현재 지도를 유지합니다.
                  </p>
                )}
                {transitionNotice && (
                  <p>
                    {transitionNotice}{' '}
                    <button onClick={() => setTransitionNotice('')}>
                      안내 닫기
                    </button>
                  </p>
                )}
                {loading && <p>선택한 그래프 조회 중…</p>}
                {error && (
                  <p>
                    {unavailableReason ? error : `조회 실패: ${error}`}
                    {data && ' 직전 정상 그래프를 표시합니다.'}{' '}
                    {graphErrorRetryable && (
                      <button
                        data-tutorial-action="retry"
                        onClick={() => setRetry((v) => v + 1)}
                      >
                        다시 시도
                      </button>
                    )}
                  </p>
                )}
                {loginNeeded && (
                  <p>
                    내 종목 지도는 로그인이 필요합니다. 전체 지도를 유지합니다.{' '}
                    <Link to="/login">로그인</Link>
                  </p>
                )}
                {notice === 'holding-missing' && (
                  <p>
                    이 종목은 지금 지도에 없어요. 시장 전체 지도에서 찾아보세요.
                    {appliedMode === 'personal' &&
                      missingCompany?.owner === memoryOwner && (
                        <button
                          type="button"
                          onClick={() =>
                            void changeMode('all', missingCompany.id)
                          }
                        >
                          전체로 보기
                        </button>
                      )}
                  </p>
                )}
                {notice === 'holding-missing-all' && (
                  <p>시장 전체 지도에서도 이 종목을 찾지 못했어요.</p>
                )}
                {notice === 'graph-not-ready' && (
                  <p>지도를 확인한 뒤 종목을 다시 선택해 주세요.</p>
                )}
                {notice === 'info' && (
                  <p>
                    기업·공유 사건과 관계를 표시합니다. 개별 사건은 ϟ 숫자로
                    접어 표시합니다. MOCK 표시는 실제 시장 정보가 아닌 개발용
                    가상 데이터입니다.
                  </p>
                )}
                {data?.metadata.partial && (
                  <p>
                    일부 데이터를 조회하지 못했습니다.{' '}
                    <button
                      data-tutorial-action="retry"
                      onClick={() => setRetry((v) => v + 1)}
                    >
                      다시 시도
                    </button>
                  </p>
                )}
                {data?.metadata.truncated && (
                  <p>조회 상한으로 그래프 일부만 표시됩니다.</p>
                )}
                {notice && (
                  <button onClick={() => setNotice('')} aria-label="안내 닫기">
                    닫기
                  </button>
                )}
              </div>
            )}
          </div>
          <AiChatDrawer
            onViewOnMap={viewAnswerTarget}
            returnFocusTo={mapRegion}
          />
          <EvidenceDrawer
            key={evidenceTarget?.id ?? 'closed'}
            onTutorialSkip={
              tutorialOpen && tutorialStep && tutorialStep < 5
                ? () => {
                    useGraphUiStore.getState().closeEvidence();
                    void closeTutorial();
                  }
                : undefined
            }
            onClosed={() => {
              // 근거를 불러오지 못한 경우에도 창을 확인하고 닫으면 다음 단계로 이어 간다.
              if (tutorialOpen && tutorialStep === 4) setTutorialStep(5);
            }}
            onReady={(id) => {
              if (
                tutorialOpen &&
                tutorialStep === 4 &&
                target &&
                id === `${target.company.id},${target.issue.id}`
              )
                setTutorialStep(5);
            }}
            mapResult={
              activeEvidence
                ? evidenceEdges.length
                  ? 'edges'
                  : evidenceFallback
                    ? 'event'
                    : 'none'
                : null
            }
            onViewOnMap={(selection) =>
              setEvidenceSelection(
                selection && evidenceTarget
                  ? { target: evidenceTarget, ...selection }
                  : null,
              )
            }
          />
        </section>
      </main>
    </div>
  );
}
