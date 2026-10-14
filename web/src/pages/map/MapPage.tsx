import { useCallback, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import ServiceHeader from '@/components/common/ServiceHeader';
import GraphCanvas from '@/components/graph/GraphCanvas';
import GraphIcon from '@/components/graph/GraphIcon';
import CompanyDetailPanel from '@/components/graph/CompanyDetailPanel';
import AiChatDrawer from '@/components/ai/AiChatDrawer';
import { graphSummary } from '@/components/graph/graph-model';
import { useGraphData } from '@/hooks/useGraphData';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import { useAuthStore } from '@/stores/useAuthStore';
import { useAiChatStore } from '@/stores/useAiChatStore';
import type { MapMode, PersonalScope } from '@/types/map';
import '@/components/graph/relationship-map.css';

const FILTER_KEY = 'zoop.graph.personal-filter';
// Same-session preference only; cleared on sign-in/out, not access-token refresh.
useAuthStore.subscribe((next, previous) => {
  if (Boolean(next.accessToken) !== Boolean(previous.accessToken))
    sessionStorage.removeItem(FILTER_KEY);
});
function readFilter(value: string | null): PersonalScope {
  return value === 'holdings' || value === 'watchlist' ? value : 'all';
}

// WBS 6.6.21 · 김도현 · D-GRP-01/01b only. Detail/AI/tutorial/round panels excluded.
export default function MapPage() {
  const { params, updateQuery } = useRouteQuery();
  const token = useAuthStore((s) => s.accessToken);
  const [retry, setRetry] = useState(0);
  const [notice, setNotice] = useState('');
  const openAi = useAiChatStore((state) => state.open);
  const desiredMode: MapMode =
    params.get('mode') === 'personal' ? 'personal' : 'all';
  const requestedMode =
    desiredMode === 'personal' && !token ? 'all' : desiredMode;
  const filter = readFilter(
    params.get('scope') ?? sessionStorage.getItem(FILTER_KEY),
  );
  const { data, error, loading } = useGraphData(
    { mode: requestedMode, personalFilter: filter },
    token,
    retry,
  );
  const appliedMode = data?.metadata.mode ?? 'all';
  const stats = data ? graphSummary(data) : null;
  const rawSelection = params.get('select');
  const selectedId = rawSelection?.startsWith('node:')
    ? rawSelection.slice(5)
    : null;
  const selectedNode =
    data?.nodes.find((node) => node.id === selectedId) ?? null;
  const companyNode = selectedNode?.kind === 'company' ? selectedNode : null;
  const relatedCompanies = useMemo(() => {
    if (!data || !companyNode) return [];
    const issueIds = new Set(
      data.edges
        .filter((edge) => edge.target === companyNode.id && !edge.derived)
        .map((edge) => edge.source),
    );
    const counts = new Map<string, number>();
    data.edges.forEach((edge) => {
      if (
        !edge.derived &&
        issueIds.has(edge.source) &&
        edge.target !== companyNode.id
      )
        counts.set(edge.target, (counts.get(edge.target) ?? 0) + 1);
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
    (id: string | null) =>
      updateQuery({ select: id ? `node:${id}` : null, id: null }),
    [updateQuery],
  );
  const loginNeeded =
    !token && (desiredMode === 'personal' || notice === 'login');
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
    });
  }
  function changeFilter(scope: PersonalScope) {
    sessionStorage.setItem(FILTER_KEY, scope);
    updateQuery({ mode: 'personal', scope, select: null, id: null });
  }
  return (
    <div className="relationship-map">
      <ServiceHeader />
      <main className="relationship-main">
        <section
          className="relationship-view"
          data-screen-id={
            companyNode
              ? 'D-GRP-03'
              : appliedMode === 'personal'
                ? 'D-GRP-01b'
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
                onClick={() => setNotice(notice === 'help' ? '' : 'help')}
                aria-label="지도 조작 안내"
              >
                <GraphIcon name="help" size={15} />
              </button>
            </div>
          </div>
          <div
            className={`relationship-body${companyNode ? ' has-company-panel' : ''}`}
            aria-busy={loading}
          >
            {data ? (
              <GraphCanvas
                data={data}
                selectedId={selectedId}
                onSelect={selectNode}
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
            {companyNode && (
              <CompanyDetailPanel
                key={companyNode.id}
                companyId={companyNode.id}
                fallback={companyNode}
                relatedCompanies={relatedCompanies}
                token={token}
                onClose={() => selectNode(null)}
                onSelectIssue={selectNode}
                onFocus={() =>
                  updateQuery({ focus: companyNode.id, hops: '1' })
                }
                onConnections={() => {
                  updateQuery({ path: companyNode.id });
                  setNotice('connections');
                }}
                onAskAi={() => openAi({ kind: 'company', id: companyNode.id })}
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
                    전체 보기 · 노드 선택으로 이름 확인. 상세 패널은 별도 WBS
                    범위입니다.
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
        </section>
      </main>
    </div>
  );
}
