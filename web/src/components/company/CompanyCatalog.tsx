import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useParams } from 'react-router-dom';
import { useCompanyResource, type Resource } from '@/hooks/useCompanyResource';
import { useAsyncData } from '@/hooks/useAsyncData';
import { useAuthStore, selectMemberId } from '@/stores/useAuthStore';
import { getSettings } from '@/apis/settings/settings';
import type { GraphResponse } from '@/types/map/graph';
import CompanyCatalogRow, { type CatalogCompany } from './CompanyCatalogRow';

// D-COM-01 · Figma 637:2286. Member lists never use another session's result.
export default function CompanyCatalog({
  graph: graphResource,
  currentCompany,
  portfolio,
}: {
  graph?: Resource<GraphResponse>;
  currentCompany?: CatalogCompany | null;
  portfolio: {
    data: { connected: boolean; holdings: { companyId: string }[] } | null;
    loading: boolean;
    error: string | null;
    retry: () => void;
  };
}) {
  const { id = '' } = useParams();
  const graph = graphResource?.data;
  const location = useLocation();
  const member = useAuthStore(selectMemberId);
  const revision = useAuthStore((s) => s.sessionRevision);
  const owner = `${member ?? 'guest'}:${revision}`;
  const [input, setInput] = useState('');
  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState<string | null>(null);
  const list = useCompanyResource<{
    items: CatalogCompany[];
    nextCursor: string | null;
  }>(
    `/api/v1/companies?${new URLSearchParams({ q: query, limit: '20', ...(cursor ? { cursor } : {}) })}`,
    '',
    false,
  );
  const settings = useAsyncData(
    useCallback(
      () => (member ? getSettings() : Promise.resolve(null)),
      [member],
    ),
  );
  const recentKey = `zoop.company.recent:${owner}`;
  const recent = useMemo(() => {
    let saved: unknown = [];
    try {
      saved = JSON.parse(sessionStorage.getItem(recentKey) ?? '[]');
    } catch {
      /* unavailable storage */
    }
    return [
      ...new Set([
        id,
        ...(Array.isArray(saved)
          ? saved.filter((value): value is string => typeof value === 'string')
          : []),
      ]),
    ]
      .filter(Boolean)
      .slice(0, 5);
  }, [id, recentKey]);
  useEffect(() => {
    try {
      sessionStorage.setItem(recentKey, JSON.stringify(recent));
    } catch {
      /* browsing still works */
    }
  }, [recent, recentKey]);
  const known = new Map((list.data?.items ?? []).map((c) => [c.id, c]));
  // The parent already loads the selected company's detail; do not duplicate it.
  known.set(
    id,
    currentCompany ?? known.get(id) ?? { id, name: id, ticker: null },
  );
  graph?.nodes
    .filter((n) => n.kind === 'company')
    .forEach((n) => {
      known.set(n.id, {
        id: n.id,
        name: n.label,
        ticker: known.get(n.id)?.ticker ?? null,
        logoUrl: n.logoUrl ?? known.get(n.id)?.logoUrl,
      });
    });
  const linkedIds = new Set<string>();
  const incidentIds = new Set(
    graph?.edges
      .filter((e) => e.source === id || e.target === id)
      .flatMap((e) => [e.source, e.target]) ?? [],
  );
  const issueIds = new Set(
    graph?.nodes
      .filter((n) => n.kind === 'issue' && incidentIds.has(n.id))
      .map((n) => n.id),
  );
  graph?.nodes
    .filter((n) => n.kind === 'company' && n.id !== id && incidentIds.has(n.id))
    .forEach((n) => linkedIds.add(n.id));
  for (const edge of graph?.edges ?? []) {
    if (issueIds.has(edge.source) || issueIds.has(edge.target)) {
      for (const candidate of [edge.source, edge.target]) {
        if (
          candidate !== id &&
          graph?.nodes.some((n) => n.id === candidate && n.kind === 'company')
        )
          linkedIds.add(candidate);
      }
    }
  }
  function href(companyId: string) {
    const params = new URLSearchParams(location.search);
    for (const key of [
      'event',
      'bucket',
      'document',
      'evidence',
      'docScope',
      'returnTo',
    ])
      params.delete(key);
    return `/companies/${encodeURIComponent(companyId)}${params.size ? `?${params}` : ''}`;
  }
  function rows(ids: string[]) {
    return (
      <ul className="space-y-1">
        {[...new Set(ids)].map((companyId) => (
          <li key={companyId}>
            <CompanyCatalogRow
              id={companyId}
              company={known.get(companyId)}
              selected={companyId === id}
              to={href(companyId)}
            />
          </li>
        ))}
      </ul>
    );
  }
  const heading =
    'mb-2! block font-mono text-[9px]! font-normal! tracking-[0.12em] text-zoop-muted';
  const holdingIds = portfolio.data?.connected
    ? portfolio.data.holdings.map((h) => h.companyId)
    : [];
  return (
    <aside
      aria-label="기업 선택"
      className="min-w-0 rounded-2xl bg-white p-4 font-panel shadow-sm max-md:max-h-[320px] max-md:overflow-auto [&_section]:py-3!"
    >
      <CompanyCatalogRow
        id={id}
        company={known.get(id)}
        selected={false}
        to={href(id)}
        quote={false}
      />
      <form
        className="my-3"
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(input.trim());
          setCursor(null);
        }}
      >
        <label
          htmlFor="company-search"
          className="mb-1.5 block text-[11px] text-zoop-muted"
        >
          기업 검색
        </label>
        <div className="flex gap-1">
          <input
            id="company-search"
            aria-label="기업명·종목 코드"
            placeholder="종목명"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            className="min-w-0 flex-1 text-[11px]"
          />
          <button className="shrink-0 bg-zoop-ink! px-2! text-[10px]! text-white">
            검색
          </button>
        </div>
      </form>
      {query && (
        <section aria-label="기업 검색 결과">
          <h2 className={heading}>SEARCH · 검색 결과</h2>
          {list.loading ? (
            <p role="status">검색 중…</p>
          ) : list.error ? (
            <p role="alert">
              검색 실패 <button onClick={list.retry}>다시 시도</button>
            </p>
          ) : (
            <>
              {rows(list.data?.items.map((c) => c.id) ?? [])}
              {!list.data?.items.length && <p>검색 결과가 없어요.</p>}
              {list.data?.nextCursor && (
                <button onClick={() => setCursor(list.data!.nextCursor)}>
                  다음 검색 결과
                </button>
              )}
            </>
          )}
        </section>
      )}
      <section aria-label="보유 기업">
        <h2 className={heading}>HOLDINGS · 보유 기업</h2>
        {!member ? (
          <p>로그인 후 확인할 수 있어요.</p>
        ) : portfolio.loading ? (
          <p role="status">보유 기업 확인 중…</p>
        ) : portfolio.error ? (
          <p role="alert">
            보유 조회 실패 <button onClick={portfolio.retry}>다시 시도</button>
          </p>
        ) : holdingIds.length ? (
          rows(holdingIds)
        ) : (
          <p>보유 기업이 없어요.</p>
        )}
      </section>
      <section aria-label="관심 기업">
        <h2 className={heading}>WATCH · 관심 기업</h2>
        {!member ? (
          <p>로그인 후 확인할 수 있어요.</p>
        ) : settings.status === 'loading' ? (
          <p role="status">관심 기업 확인 중…</p>
        ) : settings.status === 'error' ? (
          <p role="alert">
            관심 조회 실패 <button onClick={settings.reload}>다시 시도</button>
          </p>
        ) : settings.data?.watchlistIds.length ? (
          rows(settings.data.watchlistIds)
        ) : (
          <p>관심 기업이 없어요.</p>
        )}
      </section>
      <section aria-label="최근 본 기업">
        <h2 className={heading}>RECENT · 최근 본 기업</h2>
        {rows(recent)}
      </section>
      <section aria-label="연결된 기업">
        <h2 className={heading}>LINKED · 연결된 기업</h2>
        {graphResource?.loading ? (
          <p role="status">연결 기업 확인 중…</p>
        ) : graphResource?.error ? (
          <p role="alert">
            연결 기업 조회 실패{' '}
            <button onClick={graphResource.retry}>다시 시도</button>
          </p>
        ) : linkedIds.size ? (
          rows([...linkedIds])
        ) : !graph ? (
          <p>관계 그래프를 불러오면 연결 기업을 표시해요.</p>
        ) : (
          <p>조회된 연결 기업이 없어요.</p>
        )}
        {graph?.metadata.partial && (
          <p role="status">일부 연결 기업 자료가 누락됐어요.</p>
        )}
        {graph?.metadata.truncated && <p>조회 범위 내 연결 기업만 표시해요.</p>}
      </section>
    </aside>
  );
}
