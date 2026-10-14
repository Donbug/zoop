import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/stores/useAuthStore';
import { useOnboardingStore } from '@/stores/useOnboardingStore';
import {
  getInitialSettings,
  getInitialPortfolio,
  searchWatchlistCompanies,
  completeInitialSettings,
} from '@/apis/onboarding/watchlist';
import type {
  InitialPortfolio,
  InitialSettings,
  WatchlistCompany,
} from '@/types/onboarding/watchlist';
import './watchlist.css';

function currentSessionOwner() {
  const auth = useAuthStore.getState();
  return auth.member?.id ?? auth.accessToken;
}

// Issue #11 · WBS 6.4.5 · D-WAT-01 (0) / D-WAT-01b (1+).
export default function WatchlistSelector() {
  const navigate = useNavigate();
  const token = useAuthStore((s) => s.accessToken);
  const owner = useAuthStore((s) => s.member?.id ?? s.accessToken);
  const draft = useOnboardingStore();
  const { initializeWatchlist } = draft;
  const [retry, setRetry] = useState(0);
  const [searchRetry, setSearchRetry] = useState(0);
  const [saveError, setSaveError] = useState(false);
  const saving = useRef(false);
  const mounted = useRef(true);
  const [lookup, setLookup] = useState<{
    owner: string | null;
    settings: InitialSettings | null;
    portfolio: InitialPortfolio | null;
    settingsError: boolean;
    portfolioError: boolean;
    loading: boolean;
  }>({
    owner,
    settings: null,
    portfolio: null,
    settingsError: false,
    portfolioError: false,
    loading: true,
  });
  const [search, setSearch] = useState<{
    items: WatchlistCompany[];
    loading: boolean;
    error: boolean;
  }>({ items: [], loading: false, error: false });
  const ownsDraft =
    draft.watchlistOwner === owner && draft.watchlistInitialized;
  const ids = ownsDraft ? draft.watchlistIds : [];
  const query = ownsDraft ? draft.searchSubmitted : null;
  const ready =
    lookup.owner === owner &&
    !lookup.loading &&
    !!lookup.settings &&
    !!lookup.portfolio &&
    !lookup.settingsError &&
    !lookup.portfolioError;
  const busy = draft.savingWatchlist;
  const holdings =
    lookup.owner === owner ? lookup.portfolio?.holdings : undefined;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(async () => {
      if (!active || !token || !owner) return;
      setLookup({
        owner,
        settings: null,
        portfolio: null,
        settingsError: false,
        portfolioError: false,
        loading: true,
      });
      const [settings, portfolio] = await Promise.allSettled([
        getInitialSettings(),
        getInitialPortfolio(),
      ]);
      if (!active || currentSessionOwner() !== owner) return;
      if (settings.status === 'fulfilled')
        initializeWatchlist(owner, settings.value.watchlistIds);
      setLookup({
        owner,
        settings: settings.status === 'fulfilled' ? settings.value : null,
        portfolio: portfolio.status === 'fulfilled' ? portfolio.value : null,
        settingsError: settings.status === 'rejected',
        portfolioError: portfolio.status === 'rejected',
        loading: false,
      });
    });
    return () => {
      active = false;
    };
  }, [token, owner, retry, initializeWatchlist]);
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(async () => {
      if (!active) return;
      if (query === null) {
        setSearch({ items: [], loading: false, error: false });
        return;
      }
      setSearch({ items: [], loading: true, error: false });
      try {
        const result = await searchWatchlistCompanies(query);
        if (active)
          setSearch({ items: result.items, loading: false, error: false });
      } catch {
        if (active) setSearch({ items: [], loading: false, error: true });
      }
    });
    return () => {
      active = false;
    };
  }, [query, token, searchRetry]);
  async function complete() {
    if (
      !ready ||
      !lookup.settings ||
      !lookup.portfolio ||
      busy ||
      saving.current ||
      !token
    )
      return;
    saving.current = true;
    draft.setSavingWatchlist(true);
    setSaveError(false);
    const hasStocks = lookup.portfolio.holdings.length > 0 || ids.length > 0;
    try {
      const result = await completeInitialSettings({
        version: lookup.settings.version,
        mode: lookup.portfolio.holdings.length > 0 ? 'assets' : 'watchlist',
        watchlistIds: ids,
        completed: true,
        ...(draft.investmentStatus !== null
          ? { investor: draft.investmentStatus === 'investing' }
          : {}),
      });
      if (!mounted.current || currentSessionOwner() !== owner) return;
      useAuthStore.setState({ onboardingCompleted: result.completed });
      navigate(hasStocks ? '/?mode=personal' : '/?mode=all', { replace: true });
    } catch {
      if (mounted.current && currentSessionOwner() === owner)
        setSaveError(true);
    } finally {
      saving.current = false;
      if (useOnboardingStore.getState().watchlistOwner === owner)
        draft.setSavingWatchlist(false);
    }
  }
  const previous =
    draft.investmentStatus === 'not-investing'
      ? '/onboarding'
      : '/onboarding/account';
  return (
    <section
      className="watchlist-setup"
      data-screen-id={ids.length ? 'D-WAT-01b' : 'D-WAT-01'}
      aria-busy={busy}
    >
      <button
        className="watchlist-back"
        disabled={busy}
        onClick={() => navigate(previous)}
      >
        ← 이전 단계
      </button>
      <h1>관심 있는 종목을 골라 주세요</h1>
      <p className="watchlist-hint">
        기업명이나 종목 코드로 검색해 관심 종목을 추가할 수 있어요.
      </p>
      {lookup.loading && (
        <p role="status">보유 종목과 관심 목록을 확인하고 있어요.</p>
      )}
      {(lookup.settingsError || lookup.portfolioError) && (
        <div role="alert" className="watchlist-error">
          <p>
            {lookup.settingsError
              ? '관심 목록을 불러오지 못했어요.'
              : '보유 종목을 불러오지 못했어요.'}{' '}
            확인 후 시작할 수 있어요.
          </p>
          <button disabled={busy} onClick={() => setRetry((v) => v + 1)}>
            조회 다시 시도
          </button>
        </div>
      )}
      <form
        className="watchlist-search"
        onSubmit={(e) => {
          e.preventDefault();
          if (busy || !ownsDraft) return;
          draft.setSearchSubmitted(draft.searchInput.trim());
          setSearchRetry((v) => v + 1);
        }}
      >
        <label className="sr-only" htmlFor="watchlist-query">
          기업명이나 종목 코드
        </label>
        <input
          id="watchlist-query"
          placeholder="기업명이나 종목 코드로 검색"
          value={ownsDraft ? draft.searchInput : ''}
          disabled={busy || !ownsDraft}
          onChange={(e) => draft.setSearchInput(e.target.value)}
        />
        <button disabled={busy || !ownsDraft}>검색</button>
      </form>
      <div className="watchlist-results" aria-label="기업 검색 결과">
        {search.loading && <p role="status">검색하고 있어요.</p>}
        {search.error && (
          <div role="alert">
            <p>검색 결과를 불러오지 못했어요.</p>
            <button
              disabled={busy}
              onClick={() => setSearchRetry((v) => v + 1)}
            >
              검색 다시 시도
            </button>
          </div>
        )}
        {query !== null &&
          !search.loading &&
          !search.error &&
          search.items.length === 0 && (
            <p role="status">검색 결과가 없습니다.</p>
          )}
        {search.items.length > 0 && (
          <ul>
            {search.items.map((company) => (
              <li key={company.id}>
                <span className="watchlist-mark" aria-hidden="true">
                  {company.name.slice(0, 1)}
                </span>
                <div>
                  <strong>{company.name}</strong>
                  <small>
                    {company.ticker ?? company.id} · 승인된 사건{' '}
                    {company.issueCount}건
                  </small>
                </div>
                <button
                  disabled={busy || !ready || ids.includes(company.id)}
                  onClick={() => draft.addWatchlistCompany(company)}
                  aria-label={`${company.name} ${ids.includes(company.id) ? '선택됨' : '추가'}`}
                >
                  {ids.includes(company.id) ? '선택됨' : '+ 추가'}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <section aria-label="고른 종목" className="watchlist-selected">
        <div className="watchlist-heading">
          <h2>☆ 고른 종목</h2>
          <span>{ids.length}개</span>
        </div>
        {ids.length > 0 ? (
          <ul className="watchlist-chips">
            {ids.map((id) => (
              <li key={id}>
                <span>{draft.watchlistNames[id] ?? id}</span>
                <button
                  disabled={busy || !ready}
                  aria-label={`${draft.watchlistNames[id] ?? id} 해제`}
                  onClick={() => draft.toggleWatchlist(id)}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        ) : (
          ready && (
            <p className="watchlist-empty">
              {holdings?.length
                ? '고르지 않아도 보유 종목 기준 내 종목 지도로 시작할 수 있어요.'
                : '아직 고른 종목이 없어요. 고르지 않으면 시장 전체 지도로 시작해요.'}
            </p>
          )
        )}
      </section>
      <div className="watchlist-finish">
        {saveError && (
          <p role="alert">
            관심 종목을 저장하지 못했어요. 선택한 목록은 유지됩니다. 다시 시도해
            주세요.
          </p>
        )}
        <button disabled={!ready || busy} onClick={() => void complete()}>
          {busy
            ? '저장 중…'
            : saveError
              ? '저장 다시 시도'
              : ids.length
                ? `${ids.length}개 종목으로 시작하기`
                : '고르지 않고 지도 보기'}
        </button>
      </div>
    </section>
  );
}
