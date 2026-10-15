import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useCompanyResource } from '@/hooks/useCompanyResource';
export default function CompanyCatalog() {
  const [input, setInput] = useState(''),
    [query, setQuery] = useState('');
  const location = useLocation();
  const list = useCompanyResource<{
    items: { id: string; name: string; ticker: string | null }[];
    nextCursor: string | null;
  }>(`/api/v1/companies?${new URLSearchParams({ q: query })}`, '', true);
  return (
    <aside
      className="min-w-0 border-r border-[var(--zoop-line)] p-4 [&_input]:w-full [&_label]:text-xs [&_li]:border-b [&_li]:border-[var(--zoop-line)] [&_li]:py-2.5 [&_small]:block [&_small]:text-[var(--zoop-faint)] max-md:max-h-[220px] max-md:overflow-auto max-md:border-r-0 max-md:border-b"
      aria-label="기업 선택"
    >
      <h2>기업 검색</h2>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(input.trim());
        }}
      >
        <label htmlFor="company-search">기업명·종목 코드</label>
        <input
          id="company-search"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button>검색</button>
      </form>
      {list.loading && <p role="status">기업 목록을 불러오고 있어요.</p>}
      {list.error && (
        <p role="alert">
          기업 목록을 불러오지 못했어요.
          <button onClick={list.retry}>기업 목록 다시 조회</button>
        </p>
      )}
      {list.data && !list.data.items.length && <p>검색 결과가 없어요.</p>}
      <ul>
        {list.data?.items.map((c) => {
          const params = new URLSearchParams(location.search);
          params.delete('event');
          params.delete('bucket');
          params.delete('returnTo');
          return (
            <li key={c.id}>
              <Link
                to={`/companies/${encodeURIComponent(c.id)}${params.size ? `?${params}` : ''}`}
              >
                {c.name}
                <small>{c.ticker ?? '코드 미제공'}</small>
              </Link>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
