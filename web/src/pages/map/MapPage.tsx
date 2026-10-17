import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import ServiceHeader from '@/components/common/ServiceHeader';
import GraphCanvas from '@/components/graph/GraphCanvas';
import GraphIcon from '@/components/graph/GraphIcon';
import GraphTutorial from '@/components/graph/GraphTutorial';
import GraphFocusControls from '@/components/graph/GraphFocusControls';
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
import { useGraphData } from '@/hooks/useGraphData';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import { useCompanyResource } from '@/hooks/useCompanyResource';
import { useImpactPath } from '@/hooks/useImpactPath';
import { companyUrl } from '@/apis/company/company';
import { setTutorialCompleted } from '@/apis/graph/tutorial';
import { impactEdges, exactTime } from '@/components/company/detail-model';
import type { Impact } from '@/types/company/detail';
import { useAuth } from '@/hooks/useAuth';
import { selectMemberId, useAuthStore } from '@/stores/useAuthStore';
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
  const { params, updateQuery } = useRouteQuery();
  // 회원 세션의 회원 ID(쿠키 세션). 비회원·세션 없음은 null
  const { checking } = useAuth();
  const token = useAuthStore(selectMemberId);
  const [retry, setRetry] = useState(0);
  const [notice, setNotice] = useState('');
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
  const { data, error, loading } = useGraphData(
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
  );
  const appliedMode = data?.metadata.mode ?? 'all';
  const stats = data ? graphSummary(data) : null;
  const rawSelection = params.get('select');
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
    impactIssueId ?? eventId ?? edgeId ?? companyNode?.id ?? null;
  const focusId = params.get('focus');
  const focusHops: 1 | 2 = params.get('hops') === '2' ? 2 : 1;
  const focusNode = data?.nodes.find((node) => node.id === focusId) ?? null;
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
  const autoTutorial = useRef(false);
  useEffect(() => {
    if (!tutorialPending || autoTutorial.current || tutorialOpen) return;
    autoTutorial.current = true;
    updateQuery({ tour: '1' }, { replace: true });
  }, [tutorialPending, tutorialOpen, updateQuery]);
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
  const selectNode = useCallback(
    (id: string | null) => {
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
    },
    [updateQuery],
  );
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
    updateQuery({ select: `edge:${id}`, id: null, impact: null });
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
  function changeMode(mode: MapMode) {
    if (mode === 'personal' && !token) {
      setNotice('login');
      return;
    }
    setNotice('');
    updateQuery({
      mode,
      scope:
        mode === 'personal'
          ? (sessionStorage.getItem(FILTER_KEY) ?? 'all')
          : null,
      select: null,
      id: null,
      round: null,
      focus: null,
      hops: null,
      tour: null,
      impact: null,
    });
  }
  function changeFilter(scope: PersonalScope) {
    sessionStorage.setItem(FILTER_KEY, scope);
    updateQuery({
      mode: 'personal',
      scope,
      select: null,
      id: null,
      impact: null,
    });
  }
  return (
    <div
      className={
        round
          ? 'relationship-map min-w-0! max-sm:[&_.relationship-header]:h-auto! max-sm:[&_.relationship-header]:flex-wrap! max-sm:[&_.relationship-header]:gap-2! max-sm:[&_.relationship-header]:py-2! max-sm:[&_.relationship-header_nav]:order-last max-sm:[&_.relationship-header_nav]:w-full max-sm:[&_.relationship-header_nav]:overflow-x-auto max-sm:[&_.relationship-toolbar]:max-w-full max-sm:[&_.relationship-toolbar]:overflow-x-auto'
          : 'relationship-map'
      }
    >
      <ServiceHeader />
      {returnTo?.startsWith('/companies/') && (
        <Link to={returnTo}>기업 상세로 돌아가기</Link>
      )}
      {historical && (
        <p className="border-l-2 border-[var(--zoop-faint)] bg-[var(--zoop-soft)] p-2 text-xs">
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
          <div className="relationship-toolbar">
            <button
              className="relationship-sidebar-toggle"
              onClick={() => setNotice('sidebar')}
              title="내 종목 사이드바 디자인 확인 대기"
            >
              <GraphIcon name="sidebar" />내 종목
            </button>
            <div className="relationship-mode" aria-label="그래프 모드">
              <button
                aria-pressed={appliedMode === 'all'}
                onClick={() => changeMode('all')}
              >
                <GraphIcon name="globe" />
                시장 전체
              </button>
              <button
                aria-pressed={appliedMode === 'personal'}
                onClick={() => changeMode('personal')}
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
            <div className="relationship-count">
              <GraphIcon name="company" size={12} />
              기업<span>{stats?.company ?? '—'}</span>
            </div>
            <div className="relationship-count">
              <GraphIcon name="issue" size={12} />
              사건<span>{stats?.issue ?? '—'}</span>
            </div>
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
            <div className="relationship-count">
              <b className="legend-line" />
              직접 관련<span>{stats?.direct ?? '—'}</span>
            </div>
            <div className="relationship-count">
              <b className="legend-line follows" />
              후속 사건<span>{stats?.follows ?? '—'}</span>
            </div>
            <div className="relationship-count">
              <b className="legend-line dashed" />
              사건 공유<span>{stats?.shared ?? '—'}</span>
            </div>
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
            className={`relationship-body${selectedPanel ? ' has-company-panel' : ''}`}
            aria-busy={loading}
          >
            {data ? (
              <GraphCanvas
                data={data}
                selectedId={selectedId ?? detailEventId ?? companyId}
                highlightedEdgeIds={impactEdges(
                  data,
                  impact.data ?? historicalImpact.data,
                )}
                selectedEdgeId={edgeId}
                onSelectEdge={selectEdge}
                onSelect={selectNode}
                focusId={
                  focusId ?? (historical ? (detailEventId ?? companyId) : null)
                }
                focusHops={focusHops}
              />
            ) : (
              <div className="relationship-canvas">
                <p className="relationship-message" role="status">
                  {loading
                    ? '관계 지도를 불러오는 중입니다.'
                    : '관계 지도를 불러오지 못했습니다.'}
                </p>
              </div>
            )}
            {focusNode?.kind === 'company' && (
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
            {companyNode && !impactIssueId && (
              <CompanyDetailPanel
                key={companyNode.id}
                companyId={companyNode.id}
                context={round ? eventContext : undefined}
                fallback={companyNode}
                relatedCompanies={relatedCompanies}
                token={token}
                onClose={() => selectNode(null)}
                onSelectIssue={(issueId) => openImpact(companyNode.id, issueId)}
                onFocus={() =>
                  updateQuery({ focus: companyNode.id, hops: '1' })
                }
                onConnections={() => {
                  updateQuery({ path: companyNode.id });
                  setNotice('connections');
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
                onAskAi={() => openAi({ kind: 'company', id: companyNode.id })}
              />
            )}
            {data && impactCompanyId && impactIssueId && (
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
            {eventId && (
              <EventDetailPanel
                key={eventId}
                id={eventId}
                context={eventContext}
                geography={selectedNode?.geography ?? null}
                onClose={() => selectNode(null)}
                onAction={eventAction}
              />
            )}
            {edgeId && (
              <RelationDetailPanel
                key={edgeId}
                id={edgeId}
                context={eventContext}
                onClose={() => selectNode(null)}
                onSelectNode={selectNode}
                onAction={relationAction}
              />
            )}
            {(loading ||
              error ||
              loginNeeded ||
              notice ||
              data?.metadata.partial ||
              data?.metadata.truncated) && (
              <div
                className="relationship-notice"
                role={error ? 'alert' : 'status'}
              >
                {loading && <p>선택한 그래프 조회 중…</p>}
                {error && (
                  <p>
                    조회 실패: {error}
                    {data && ' 직전 정상 그래프를 표시합니다.'}{' '}
                    <button onClick={() => setRetry((v) => v + 1)}>
                      다시 시도
                    </button>
                  </p>
                )}
                {loginNeeded && (
                  <p>
                    내 종목 지도는 로그인이 필요합니다. 전체 지도를 유지합니다.{' '}
                    <Link to="/login">로그인</Link>
                  </p>
                )}
                {notice === 'sidebar' && (
                  <p>
                    내 종목 목록 사이드바는 Figma 프레임 확인 대기 중입니다.
                    임의 UI는 구현하지 않았습니다.
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
                {notice === 'connections' && (
                  <p>
                    연결 탐색의 시작 기업을 저장했습니다. 지도에서 비교할 기업을
                    선택해 주세요.
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
            onViewOnMap={(id) => updateQuery({ focus: id, hops: '1' })}
          />
        </section>
      </main>
    </div>
  );
}
