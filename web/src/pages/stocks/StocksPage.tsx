import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import ErrorNotice from '@/components/common/ErrorNotice';
import GraphIcon from '@/components/graph/GraphIcon';
import StockList from '@/components/stocks/StockList';
import StockSearchForm from '@/components/stocks/StockSearchForm';
import { getCompanyBrief, searchCompanies } from '@/apis/companies/companies';
import { getPortfolio } from '@/apis/portfolio/portfolio';
import { getSettings } from '@/apis/settings/settings';
import { setWatched } from '@/apis/watchlist/watchlist';
import { useAsyncData } from '@/hooks/useAsyncData';
import { useAuth } from '@/hooks/useAuth';
import type { CompanyBrief, CompanySummary, StockScope } from '@/types/company';

type WatchChange = { companyId: string; name: string; watched: boolean };

type MorePages = {
  query: string;
  items: CompanySummary[];
  nextCursor: string | null;
};

function toBrief(company: CompanySummary): CompanyBrief {
  return {
    id: company.id,
    name: company.name,
    ticker: company.ticker,
    logoUrl: company.logoUrl,
    issueCount: company.issueCount,
  };
}

function matches(row: CompanyBrief, query: string) {
  if (!query) return true;
  const needle = query.toLowerCase();
  return (
    row.name.toLowerCase().includes(needle) ||
    (row.ticker ?? '').toLowerCase().includes(needle) ||
    row.id.toLowerCase().includes(needle)
  );
}

function rememberedPersonalFilter() {
  try {
    return sessionStorage.getItem('zoop.stocks.personal-filter');
  } catch {
    return null;
  }
}

// D-STK-01 종목 (FS037·FS027)
// - 상단 메뉴 [종목]: 들어오면 전체 종목을 이름순으로 보여 주고, 기업명·영문명·티커로 명시적 검색한다.
// - 검색어(q)와 범위(scope)는 주소에 남겨 상세에서 돌아와도 그대로 보인다.
// - [시장 전체]는 검색 결과(더 보기로 다음 페이지), [내 종목]은 보유·관심 종목만 보여 준다.
// - ☆는 회원만 즉시 저장한다(응답 전 먼저 반영, 실패하면 되돌리고 다시 시도). 비회원은 로그인 안내.
export default function StocksPage() {
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const { isAuthenticated, member, status } = useAuth();
  const confirmedMember = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    // D-STK-01: only an actual member change resets the URL-owned filter.
    // Initial session restoration and a recheck of the same member keep it.
    if (status !== 'ready') return;
    const current = isAuthenticated ? (member?.id ?? null) : null;
    const previous = confirmedMember.current;
    confirmedMember.current = current;
    if (
      previous === undefined ||
      previous === current ||
      !params.has('personal')
    )
      return;
    setParams(
      (value) => {
        const next = new URLSearchParams(value);
        next.delete('personal');
        return next;
      },
      { replace: true, preventScrollReset: true, state: location.state },
    );
  }, [status, isAuthenticated, member?.id, params, setParams, location.state]);
  // A member change must also discard old list/cache/pending-write state.
  // A checking session retains member.id, so same-member rechecks do not remount.
  return <StocksSession key={member?.id ?? 'nonmember'} />;
}

function StocksSession() {
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const query = params.get('q') ?? '';
  const scope: StockScope = params.get('scope') === 'mine' ? 'mine' : 'all';
  const requestedPersonal =
    params.get('personal') ?? rememberedPersonalFilter();
  const personal =
    requestedPersonal === 'held'
      ? 'held'
      : requestedPersonal === 'watch'
        ? 'watch'
        : 'all';
  const { checking, isAuthenticated } = useAuth();

  // 주소의 검색어가 바뀌면(뒤로 가기 포함) 입력칸도 맞춘다.
  const [draft, setDraft] = useState(query);
  const [syncedQuery, setSyncedQuery] = useState(query);
  if (syncedQuery !== query) {
    setSyncedQuery(query);
    setDraft(query);
  }

  // 시장 전체: 첫 페이지 + [더 보기]로 이어 붙인 페이지
  const loadFirst = useCallback(() => searchCompanies(query), [query]);
  const first = useAsyncData(loadFirst);
  const [more, setMore] = useState<MorePages | null>(null);
  const [moreState, setMoreState] = useState<'idle' | 'loading' | 'error'>(
    'idle',
  );
  const extra = more?.query === query ? more : null;
  const allRows = [...(first.data?.items ?? []), ...(extra?.items ?? [])];
  const nextCursor = extra
    ? extra.nextCursor
    : (first.data?.nextCursor ?? null);

  const loadMore = async () => {
    if (!nextCursor || moreState === 'loading') return;
    setMoreState('loading');
    try {
      const page = await searchCompanies(query, nextCursor);
      setMore((previous) => ({
        query,
        items: [
          ...(previous?.query === query ? previous.items : []),
          ...page.items,
        ],
        nextCursor: page.nextCursor,
      }));
      setMoreState('idle');
    } catch {
      setMoreState('error');
    }
  };

  // 회원의 관심·보유. 회원이 아니면 조회하지 않는다.
  const loadSettings = useCallback(
    () => (isAuthenticated ? getSettings() : Promise.resolve(null)),
    [isAuthenticated],
  );
  const loadPortfolio = useCallback(
    () => (isAuthenticated ? getPortfolio() : Promise.resolve(null)),
    [isAuthenticated],
  );
  const settings = useAsyncData(loadSettings);
  const portfolio = useAsyncData(loadPortfolio);
  const { setData: setSettings } = settings;

  const [pending, setPending] = useState<WatchChange | null>(null);
  const [failed, setFailed] = useState<WatchChange | null>(null);
  const [loginNeeded, setLoginNeeded] = useState(false);

  const savedWatch = settings.data?.watchlistIds ?? [];
  const watchedIds = new Set(
    pending
      ? pending.watched
        ? [...savedWatch, pending.companyId]
        : savedWatch.filter((id) => id !== pending.companyId)
      : savedWatch,
  );
  const heldIds = new Set(
    portfolio.data?.connected
      ? portfolio.data.holdings.map((holding) => holding.companyId)
      : [],
  );

  // 내 종목: 보유·관심 기업. 검색 결과에 없던 기업은 기업 요약을 한 번 받아 둔다.
  const [briefs, setBriefs] = useState<Record<string, CompanyBrief | 'error'>>(
    {},
  );
  const [briefAttempt, setBriefAttempt] = useState(0);
  const requested = useRef(new Set<string>());
  const mineIds = [...new Set([...watchedIds, ...heldIds])];
  const mineKey = scope === 'mine' ? mineIds.join('\n') : '';
  useEffect(() => {
    if (!mineKey) return;
    for (const id of mineKey.split('\n')) {
      if (requested.current.has(id)) continue;
      requested.current.add(id);
      getCompanyBrief(id).then(
        (brief) => setBriefs((previous) => ({ ...previous, [id]: brief })),
        () => setBriefs((previous) => ({ ...previous, [id]: 'error' })),
      );
    }
  }, [briefAttempt, mineKey]);
  const knownBrief = (id: string): CompanyBrief | null => {
    const fromSearch = allRows.find((row) => row.id === id);
    if (fromSearch) return toBrief(fromSearch);
    const cached = briefs[id];
    return cached && cached !== 'error' ? cached : null;
  };
  const mineRows = mineIds
    .map(knownBrief)
    .filter((row): row is CompanyBrief => row !== null)
    .filter((row) => matches(row, query));
  const mineWaiting = mineIds.some(
    (id) => !knownBrief(id) && briefs[id] !== 'error',
  );
  const mineFailed = mineIds.some(
    (id) => !allRows.some((row) => row.id === id) && briefs[id] === 'error',
  );

  const retryMineBriefs = () => {
    const failedIds = mineIds.filter((id) => briefs[id] === 'error');
    requested.current = new Set(
      [...requested.current].filter((id) => !failedIds.includes(id)),
    );
    setBriefs((previous) => {
      const next = { ...previous };
      for (const id of failedIds) delete next[id];
      return next;
    });
    setBriefAttempt((attempt) => attempt + 1);
  };

  const changeWatch = async (next: WatchChange) => {
    if (pending) return;
    setPending(next);
    setFailed(null);
    try {
      setSettings(await setWatched(next.companyId, next.watched));
    } catch {
      setFailed(next);
    } finally {
      setPending(null);
    }
  };

  const toggleWatch = (row: CompanyBrief) => {
    if (!isAuthenticated) {
      setLoginNeeded(true);
      return;
    }
    if (
      scope === 'mine' &&
      watchedIds.has(row.id) &&
      (personal === 'watch' || !heldIds.has(row.id))
    ) {
      const active = document.activeElement;
      const next = active
        ?.closest('li')
        ?.nextElementSibling?.querySelector<HTMLElement>('a');
      (next ?? document.getElementById('stock-search'))?.focus();
    }
    // 내 종목에 바로 보이도록 행 정보를 남겨 둔다.
    if (!briefs[row.id])
      setBriefs((previous) => ({ ...previous, [row.id]: row }));
    void changeWatch({
      companyId: row.id,
      name: row.name,
      watched: !watchedIds.has(row.id),
    });
  };

  const search = (next: string) => {
    if (next === query) {
      first.reload();
      setMore(null);
      return;
    }
    const nextParams = new URLSearchParams();
    if (next) nextParams.set('q', next);
    if (scope === 'mine') nextParams.set('scope', 'mine');
    if (personal !== 'all') nextParams.set('personal', personal);
    setParams(nextParams);
  };

  const changeScope = (next: StockScope) => {
    const nextParams = new URLSearchParams();
    if (query) nextParams.set('q', query);
    if (next === 'mine') nextParams.set('scope', 'mine');
    if (personal !== 'all') nextParams.set('personal', personal);
    setParams(nextParams, { replace: true });
  };

  const memberDataFailed =
    isAuthenticated &&
    (settings.status === 'error' || portfolio.status === 'error');
  const watchReady =
    !checking &&
    (!isAuthenticated ||
      (settings.status === 'success' && portfolio.status === 'success'));

  const rows =
    scope === 'mine'
      ? mineRows.filter(
          (row) =>
            personal === 'all' ||
            (personal === 'held'
              ? heldIds.has(row.id)
              : watchedIds.has(row.id)),
        )
      : allRows.map(toBrief);
  const listLoading =
    scope === 'mine'
      ? isAuthenticated &&
        (settings.status === 'loading' ||
          portfolio.status === 'loading' ||
          mineWaiting)
      : first.status === 'loading';

  return (
    <section
      className="mx-auto w-full max-w-[800px] text-zoop-ink"
      data-screen-id="D-STK-01"
    >
      <h1 className="flex items-center gap-2.5 text-[28px] font-[750] tracking-[-0.045em]">
        <GraphIcon name="search" size={24} />
        종목
      </h1>
      <StockSearchForm
        draft={draft}
        onDraftChange={setDraft}
        onSearch={search}
      />

      <div
        role="group"
        aria-label="종목 범위"
        className="mt-4 inline-flex h-[38px] rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-soft p-[3px]"
      >
        {(
          [
            ['all', '시장 전체'],
            ['mine', '내 종목'],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            aria-pressed={scope === value}
            onClick={() => changeScope(value)}
            className="min-w-[76px] rounded-[2px] text-xs font-semibold text-zoop-muted aria-pressed:bg-zoop-paper aria-pressed:text-zoop-ink aria-pressed:shadow-[0_0_0_0.5px_#1a1a1a14]"
          >
            {label}
          </button>
        ))}
      </div>

      {scope === 'mine' &&
        isAuthenticated &&
        !memberDataFailed &&
        !mineFailed &&
        !listLoading && (
          <div
            role="group"
            aria-label="내 종목 필터"
            className="mt-3 flex gap-2"
          >
            {(
              [
                ['all', '전체'],
                ['held', '보유'],
                ['watch', '관심'],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={personal === value}
                className="rounded-panel border border-zoop-line px-3 py-2 text-xs aria-pressed:bg-zoop-ink aria-pressed:text-zoop-paper"
                onClick={() => {
                  const next = new URLSearchParams(params);
                  try {
                    sessionStorage.setItem(
                      'zoop.stocks.personal-filter',
                      value,
                    );
                  } catch {
                    // The URL still keeps the selection when storage is unavailable.
                  }
                  if (value === 'all') next.delete('personal');
                  else next.set('personal', value);
                  setParams(next, { replace: true });
                }}
              >
                {label}{' '}
                {
                  mineRows.filter(
                    (row) =>
                      value === 'all' ||
                      (value === 'held'
                        ? heldIds.has(row.id)
                        : watchedIds.has(row.id)),
                  ).length
                }
              </button>
            ))}
          </div>
        )}

      {loginNeeded && !isAuthenticated && (
        <p
          role="alert"
          className="mt-5 rounded-[3px] border-[0.667px] border-dashed border-zoop-line bg-zoop-wash p-[18px] text-[11px] leading-relaxed text-zoop-muted [&_a]:font-bold [&_a]:text-zoop-ink [&_a]:underline"
        >
          로그인하면 관심 종목을 저장할 수 있어요.{' '}
          <Link to="/login" state={{ from: location }}>
            로그인
          </Link>
        </p>
      )}
      {memberDataFailed && (
        <div className="mt-5 text-xs text-zoop-muted">
          <ErrorNotice
            title="관심·보유 종목을 불러오지 못했어요"
            message="다시 불러오기 전에는 관심 종목을 바꿀 수 없어요."
            onRetry={() => {
              settings.reload();
              portfolio.reload();
            }}
          />
        </div>
      )}

      {scope === 'mine' && !checking && !isAuthenticated ? (
        <p className="mt-5 rounded-[3px] border-[0.667px] border-dashed border-zoop-line bg-zoop-wash p-[18px] text-[11px] leading-relaxed text-zoop-muted [&_a]:font-bold [&_a]:text-zoop-ink [&_a]:underline">
          로그인하면 보유·관심 종목만 모아 볼 수 있어요.{' '}
          <Link to="/login" state={{ from: location }}>
            로그인
          </Link>
        </p>
      ) : listLoading ? (
        <p role="status" className="mt-5 text-xs text-zoop-muted">
          종목을 불러오고 있어요
        </p>
      ) : scope === 'all' && first.status === 'error' ? (
        <div className="mt-5 text-xs text-zoop-muted">
          <ErrorNotice
            title="종목을 불러오지 못했어요"
            onRetry={first.reload}
          />
        </div>
      ) : scope === 'mine' && mineFailed ? (
        <div className="mt-5 text-xs text-zoop-muted">
          <ErrorNotice
            title="일부 종목 정보를 불러오지 못했어요"
            message="목록을 비어 있는 것으로 표시하지 않고 다시 불러올 수 있어요."
            onRetry={retryMineBriefs}
          />
        </div>
      ) : rows.length === 0 ? (
        <p className="mt-5 rounded-[3px] border-[0.667px] border-dashed border-zoop-line bg-zoop-wash p-[18px] text-[11px] leading-relaxed text-zoop-muted">
          {scope === 'mine'
            ? personal === 'held'
              ? '표시할 보유 종목이 없어요.'
              : personal === 'watch'
                ? '표시할 관심 종목이 없어요.'
                : query
                  ? `'${query}'에 맞는 보유·관심 종목이 없어요.`
                  : '보유·관심 종목이 없어요. 시장 전체에서 ☆로 관심 종목을 추가해 보세요.'
            : query
              ? `'${query}' 검색 결과가 없어요.`
              : '표시할 종목이 없어요.'}
        </p>
      ) : (
        <>
          <p className="mt-5 mb-2 font-num text-[11px] text-zoop-muted">
            {rows.length}개 종목
          </p>
          <StockList
            rows={rows}
            heldIds={heldIds}
            watchedIds={watchedIds}
            pendingId={pending?.companyId ?? null}
            watchDisabled={
              Boolean(pending) ||
              (isAuthenticated && !watchReady) ||
              memberDataFailed
            }
            onToggleWatch={toggleWatch}
          />
          {scope === 'all' && nextCursor && (
            <button
              type="button"
              className="mx-auto mt-4 block h-9 min-w-[120px] rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-paper text-xs font-semibold text-zoop-ink disabled:cursor-progress disabled:opacity-50"
              disabled={moreState === 'loading'}
              onClick={() => void loadMore()}
            >
              {moreState === 'loading' ? '불러오고 있어요' : '더 보기'}
            </button>
          )}
          {scope === 'all' && moreState === 'error' && (
            <div className="mt-5 text-xs text-zoop-muted">
              <ErrorNotice
                title="다음 종목을 불러오지 못했어요"
                onRetry={() => void loadMore()}
              />
            </div>
          )}
        </>
      )}

      {failed && (
        <div className="fixed inset-x-0 bottom-20 z-40 mx-auto w-[min(32rem,calc(100%-2rem))] md:bottom-6">
          <ErrorNotice
            title="관심 종목을 저장하지 못했어요"
            message={`${failed.name}을(를) 이전 상태로 되돌렸어요.`}
            onRetry={() => void changeWatch(failed)}
            retryDisabled={Boolean(pending)}
          />
        </div>
      )}
    </section>
  );
}
