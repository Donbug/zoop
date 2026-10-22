import { useContext, useEffect, useMemo, useRef, useState } from 'react';
import {
  GraphAppearanceContext,
  type GraphAppearance,
} from '@/components/graph/graph-appearance';
import { mapAppearanceStyles } from '@/components/common/map-appearance-styles';
import HoldingsSidebar from '@/components/graph/HoldingsSidebar';
import { companyLogo } from '@/util/company-logo';
import { Link } from 'react-router-dom';
import ServiceHeader from '@/components/common/ServiceHeader';
import GraphCanvas from '@/components/graph/GraphCanvas';
import GraphIcon from '@/components/graph/GraphIcon';
import GraphTutorial from '@/components/graph/GraphTutorial';
import GraphFocusControls from '@/components/graph/GraphFocusControls';
import CompanyPathPanel from '@/components/graph/CompanyPathPanel';
import { companyPath } from '@/components/graph/company-path';
import ImpactPathPanel from '@/components/graph/ImpactPathPanel';
import CompanyDetailPanel from '@/components/graph/CompanyDetailPanel';
import RelationDetailPanel from '@/components/graph/RelationDetailPanel';
import type { RelationDetail } from '@/types/map/relation';
import EventDetailPanel, {
  type EventAction,
} from '@/components/graph/EventDetailPanel';
import AiChatDrawer from '@/components/ai/AiChatDrawer';
import BriefingSnapshotBanner from '@/components/graph/BriefingSnapshotBanner';
import EvidenceDrawer from '@/components/evidence/EvidenceDrawer';
import { graphSummary } from '@/components/graph/graph-model';
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
} from '@/types/map';
import '@/components/graph/relationship-map.css';

const FILTER_KEY = 'zoop.graph.personal-filter';
// Same-session preference only; cleared on sign-in/out.
useAuthStore.subscribe((next, previous) => {
  if (Boolean(next.member) !== Boolean(previous.member))
    sessionStorage.removeItem(FILTER_KEY);
});
function readFilter(value: string | null): PersonalScope {
  return value === 'holdings' || value === 'watchlist' ? value : 'all';
}

// WBS 6.6.21~6.6.23 · D-GRP-01/01b + D-GRP-02/03.
export default function MapPage() {
  const inherited = useContext(GraphAppearanceContext);
  const theme =
    document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
  const appearance = useMemo<GraphAppearance>(
    () => inherited ?? { variant: 'improved', theme },
    [inherited, theme],
  );
  return (
    <GraphAppearanceContext value={appearance}>
      <MapWorkspace appearance={appearance} />
    </GraphAppearanceContext>
  );
}

function MapWorkspace({ appearance }: { appearance: GraphAppearance }) {
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
  const evidenceOpen = useGraphUiStore((state) =>
    Boolean(state.evidenceTarget),
  );
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
  const [sidebarOpen, setSidebarOpen] = useState(false);
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
  const desiredMode: MapMode =
    params.get('mode') === 'personal' ? 'personal' : 'all';
  const requestedMode =
    desiredMode === 'personal' && !token ? 'all' : desiredMode;
  const filter = readFilter(
    params.get('scope') ?? sessionStorage.getItem(FILTER_KEY),
  );
  const companyId = params.get('companyId') ?? undefined;
  const historical = companyId && exactTime(params.get('asOf'));
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
    requestedMode === 'all' ? (params.get('round') ?? undefined) : undefined;
  const { data, error, loading, unavailableReason } = useGraphData(
    {
      mode: requestedMode,
      personalFilter: filter,
      companyId,
      asOf,
      graphVersion,
      depth: params.get('depth') === '2' ? 2 : 1,
      round,
    },
    token,
    retry,
    prefetch,
  );
  const appliedMode = data?.metadata.mode ?? 'all';
  useEffect(() => {
    if (
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
  }, [data, loading, error, requestedMode, memoryOwner, paramsKey, round]);
  const stats = data ? graphSummary(data) : null;
  const rawSelection = params.get('select');
  const pathParts = params.get('path')?.split(',') ?? [];
  const pathFrom = pathParts[0] || null;
  const pathTo = pathParts.length === 2 ? pathParts[1] || null : null;
  const displayedPath =
    data && !loading && !error && pathFrom && pathTo
      ? companyPath(data, pathFrom, pathTo)
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
  const focusHops: 1 | 2 = params.get('hops') === '2' ? 2 : 1;
  const focusNode = data?.nodes.find((node) => node.id === focusId) ?? null;
  const logoOf = (companyId: string) =>
    data?.nodes.find((node) => node.id === companyId)?.logoUrl;
  const tutorialOpen = params.get('tour') === '1';
  useEffect(() => {
    if (tutorialOpen && tutorialStep === null) setTutorialStep(1);
    if (!tutorialOpen && tutorialStep !== null) setTutorialStep(null);
  }, [setTutorialStep, tutorialOpen, tutorialStep]);
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
    round,
    graphVersion:
      params.get('graphVersion') ?? data?.metadata.graphVersion ?? undefined,
    asOf: params.get('asOf') ?? data?.metadata.asOf ?? undefined,
  };
  const impact = useImpactPath(
    round && !data ? null : impactCompanyId,
    round && !data ? null : impactIssueId,
    round ? eventContext : undefined,
  );
  function selectEdge(id: string) {
    if (
      document.activeElement instanceof HTMLElement &&
      mapRegion.current?.contains(document.activeElement)
    )
      opener.current = document.activeElement;
    updateQuery({ select: `edge:${id}`, id: null, impact: null, path: null });
  }
  function relationAction(
    action: 'evidence' | 'ai',
    relation: RelationDetail,
    issueId?: string,
  ) {
    const issue = relation.via.find((item) => item.id === issueId);
    const target: GraphTarget = {
      kind: issue ? 'issue' : 'edge',
      id: issue?.id ?? relation.id,
      label:
        issue?.title ?? `${relation.source.label} – ${relation.target.label}`,
      evidenceIds: issue?.evidenceIds ?? relation.evidenceIds,
      verifiedAt: issue
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
    !checking && !token && (desiredMode === 'personal' || notice === 'login');
  async function changeMode(mode: MapMode) {
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
      prefetch.current = {
        key: graphRequestKey(request, token),
        data: nextGraph,
      };
      setNotice('');
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
        id: null,
        round: null,
        companyId: null,
        asOf: null,
        graphVersion: null,
        event: null,
        tour: null,
      });
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
      className={`${mapAppearanceStyles(appearance)} relationship-map min-w-0! [&_.relationship-toolbar]:overflow-x-auto [&_.relationship-toolbar]:max-w-full max-md:min-h-0! max-md:[&_.relationship-header]:h-auto! max-md:[&_.relationship-header]:flex-wrap! max-md:[&_.relationship-header]:gap-2! max-md:[&_.relationship-header]:px-2! max-md:[&_.relationship-header]:py-2! max-md:[&_.relationship-header_nav]:order-last max-md:[&_.relationship-header_nav]:w-full max-md:[&_.relationship-header_nav]:h-10! max-md:[&_.relationship-header_nav]:flex! max-md:[&_.relationship-header_nav]:overflow-y-hidden! max-md:[&_.relationship-header_nav>*]:shrink-0 max-md:[&_.relationship-header_nav]:overflow-x-auto max-md:[&_.relationship-toolbar]:max-w-full max-md:[&_.relationship-toolbar]:overflow-x-auto [&_.relationship-canvas]:min-h-0! max-md:[&_.relationship-body]:min-h-0! max-md:[&_.relationship-body]:px-1!`}
    >
      <ServiceHeader />
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
          영향 경로 조회 실패. 관계를 임의 강조하지 않았어요.
          <button onClick={historicalImpact.retry}>영향 경로 다시 조회</button>
        </p>
      )}
      {round && <BriefingSnapshotBanner roundId={round} />}
      <main className="relationship-main">
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
              onClick={() => setSidebarOpen((open) => !open)}
              title="내가 보유 중인 종목 보기"
            >
              <GraphIcon name="sidebar" />내 종목
            </button>
            <div className="relationship-mode" aria-label="그래프 모드">
              <button
                aria-pressed={appliedMode === 'all'}
                onClick={() => void changeMode('all')}
              >
                <GraphIcon name="globe" />
                시장 전체
              </button>
              <button
                aria-pressed={appliedMode === 'personal'}
                onClick={() => void changeMode('personal')}
              >
                <GraphIcon name="personal" />내 종목
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
              >
                <GraphIcon name="info" size={15} />
              </button>
              <button
                onClick={() => {
                  setTutorialStep(1);
                  updateQuery({ tour: '1' });
                }}
                aria-label="튜토리얼 다시 보기"
              >
                <GraphIcon name="help" size={15} />
              </button>
            </div>
          </div>
          <div
            className={`relationship-body${selectedPanel ? ' has-company-panel max-md:pb-[48dvh]!' : ''}${tutorialOpen || sidebarOpen ? ' flex! gap-3! max-sm:flex-col [&>.relationship-canvas]:min-w-0 [&>.relationship-canvas]:flex-1 [&>.relationship-canvas]:w-auto' : ''}`}
            aria-busy={loading}
          >
            {sidebarOpen && (
              <div id="holdings-sidebar" className="flex min-h-0 max-sm:w-full">
                <HoldingsSidebar
                  member={Boolean(token)}
                  logoOf={(id) =>
                    companyLogo(
                      id,
                      data?.nodes.find((node) => node.id === id)?.logoUrl,
                    )
                  }
                  onPick={(id) => {
                    if (!data?.nodes.some((node) => node.id === id)) {
                      setNotice('holding-missing');
                      return;
                    }
                    setNotice('');
                    selectNode(id);
                    setCenterRequest((request) => ({
                      id,
                      seq: (request?.seq ?? 0) + 1,
                    }));
                  }}
                  onClose={() => setSidebarOpen(false)}
                />
              </div>
            )}
            {data ? (
              <GraphCanvas
                data={data}
                filterHost={filterHost}
                centerRequest={centerRequest}
                memoryOwner={memoryOwner}
                onOpenIsolated={() => {
                  updateQuery({
                    select: 'bundle:isolated',
                    impact: null,
                    path: null,
                  });
                }}
                selectedId={
                  pathFrom ?? selectedId ?? detailEventId ?? companyId
                }
                connectionPath={Boolean(pathFrom)}
                highlightedEdgeIds={
                  pathFrom
                    ? (displayedPath?.edgeIds ?? [])
                    : impactEdges(data, impact.data ?? historicalImpact.data)
                }
                selectedEdgeId={edgeId}
                onSelectEdge={selectEdge}
                onSelect={selectNode}
                focusId={
                  pathFrom
                    ? null
                    : (focusId ??
                      (historical ? (detailEventId ?? companyId) : null))
                }
                focusHops={focusHops}
              />
            ) : (
              <div className="relationship-canvas">
                <p className="relationship-message" role="status">
                  {loading
                    ? '관계 지도를 불러오는 중입니다.'
                    : unavailableReason === 'snapshot_not_recorded'
                      ? '이 회차의 그래프 저장본이 없습니다.'
                      : '관계 지도를 불러오지 못했습니다.'}
                </p>
              </div>
            )}
            {focusNode?.kind === 'company' && !pathFrom && (
              <GraphFocusControls
                label={focusNode.label}
                hops={focusHops}
                onHopsChange={(hops) => updateQuery({ hops: String(hops) })}
                onClear={() => updateQuery({ focus: null, hops: null })}
              />
            )}
            {tutorialOpen && tutorialStep && (
              <GraphTutorial
                step={tutorialStep}
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
            )}
            <MapDetailSheet
              open={Boolean(selectedPanel)}
              suspended={evidenceOpen}
              onClose={() => {
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
                  context={round ? eventContext : undefined}
                  fallback={companyNode}
                  relatedCompanies={relatedCompanies}
                  token={token}
                  onClose={() => selectNode(null)}
                  onSelectIssue={(issueId) =>
                    openImpact(companyNode.id, issueId)
                  }
                  onFocus={() =>
                    updateQuery({ focus: companyNode.id, hops: '1' })
                  }
                  onConnections={() => {
                    updateQuery({
                      path: companyNode.id,
                      select: null,
                      focus: null,
                      hops: null,
                      impact: null,
                    });
                  }}
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
                    openAi({ kind: 'company', id: companyNode.id })
                  }
                />
              )}
              {pathFrom && (
                <CompanyPathPanel
                  graph={data}
                  from={pathFrom}
                  to={pathTo}
                  loading={loading}
                  error={error}
                  onRetry={() => setRetry((v) => v + 1)}
                  onClose={() => updateQuery({ path: null })}
                  onPick={(id) =>
                    updateQuery({
                      path: id ? `${pathFrom},${id}` : pathFrom,
                      select: null,
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
                  graph={data}
                  impact={impact.data}
                  loading={impact.loading}
                  error={impact.error}
                  onRetry={impact.retry}
                  onClose={() => updateQuery({ impact: null })}
                  onViewIssue={() =>
                    updateQuery({
                      select: `node:${impactIssueId}`,
                      impact: null,
                    })
                  }
                  onEvidence={(evidenceIds) =>
                    useGraphUiStore
                      .getState()
                      .openEvidence(impactTarget(evidenceIds))
                  }
                  onAskAi={() => openAi(impactTarget())}
                />
              )}
              {eventId && !pathFrom && (
                <EventDetailPanel
                  key={eventId}
                  id={eventId}
                  context={eventContext}
                  geography={selectedNode?.geography ?? null}
                  logoOf={logoOf}
                  onClose={() => selectNode(null)}
                  onAction={eventAction}
                />
              )}
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
                role={error ? 'alert' : 'status'}
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
                    {unavailableReason !== 'snapshot_not_recorded' && (
                      <button onClick={() => setRetry((v) => v + 1)}>
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
                  </p>
                )}
                {notice === 'info' && (
                  <p>
                    기업·공유 사건과 관계를 표시합니다. 개별 사건은 ϟ 숫자로
                    접어 표시합니다. MOCK 표시는 실제 시장 정보가 아닌 개발용
                    가상 데이터입니다.
                  </p>
                )}
                {notice === 'help' && (
                  <p>
                    빈 영역 드래그로 이동 · 휠 또는 +/−로 확대 · 맞춤 버튼으로
                    전체 보기 · 기업 또는 사건 선택으로 상세 확인 · Tab으로 노드
                    및 연결선 이동 · Enter로 선택 · Escape로 상세 닫기.
                  </p>
                )}
                {data?.metadata.partial && (
                  <p>
                    일부 데이터를 조회하지 못했습니다.{' '}
                    <button onClick={() => setRetry((v) => v + 1)}>
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
          <AiChatDrawer />
          <EvidenceDrawer
            onViewOnMap={(id) =>
              updateQuery({ focus: id, hops: '1', path: null })
            }
          />
        </section>
      </main>
    </div>
  );
}
