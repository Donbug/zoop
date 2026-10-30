import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import CompanyLogo from '@/components/common/CompanyLogo';
import { selectMemberId, useAuthStore } from '@/stores/useAuthStore';
import { useOnboardingStore } from '@/stores/useOnboardingStore';
import {
  getInitialSettings,
  getInitialPortfolio,
  searchWatchlistCompanies,
  completeInitialSettings,
  getWatchlistCompanyName,
} from '@/apis/onboarding/watchlist';
import type {
  InitialPortfolio,
  InitialSettings,
  WatchlistCompany,
} from '@/types/onboarding/watchlist';

// 팀 규칙(web/README.md): 스타일은 Tailwind CSS 4
const focusRing =
  'focus-visible:outline-2 focus-visible:outline-offset-[3px] focus-visible:outline-gray-950';
const outlineButton = `shrink-0 whitespace-nowrap rounded border border-gray-300 bg-white px-3 py-2 ${focusRing} disabled:cursor-default disabled:opacity-50`;

function currentSessionOwner() {
  const auth = useAuthStore.getState();
  return auth.member?.id ?? null;
}

// Issue #11 · WBS 6.4.5 · D-WAT-01 (0) / D-WAT-01b (1+).
export default function WatchlistSelector() {
  const navigate = useNavigate();
  // 회원 세션(쿠키)의 회원 ID. 초안 주인이자 조회 시작 조건이다.
  const owner = useAuthStore(selectMemberId);
  const token = owner;
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
  // 이미 저장된 관심 종목은 이름을 모르므로 칩에 ID 대신 이름을 보이도록 채운다.
  const { setWatchlistName, watchlistNames } = draft;
  // 배열은 렌더마다 새로 만들어지므로 의존성에는 문자열 키를 쓴다.
  const unnamed = ids.filter((id) => !watchlistNames[id]).join('|');
  useEffect(() => {
    if (!unnamed) return;
    let active = true;
    for (const id of unnamed.split('|')) {
      getWatchlistCompanyName(id).then(
        (company) => {
          if (active) setWatchlistName(id, company.name);
        },
        () => {
          // 이름을 못 가져오면 ID를 그대로 보여 준다(선택·저장에는 영향 없음).
        },
      );
    }
    return () => {
      active = false;
    };
  }, [unnamed, setWatchlistName]);
  const heldIds = new Set(holdings?.map((holding) => holding.companyId));
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
      useAuthStore.setState((state) => ({
        onboardingCompleted: result.completed,
        session:
          state.session?.kind === 'member'
            ? {
                ...state.session,
                setup: {
                  completed: result.completed,
                  tutorialCompleted: result.tutorialCompleted,
                },
              }
            : state.session,
      }));
      navigate(result.tutorialCompleted ? '/?mode=all' : '/?mode=all&tour=1', {
        replace: true,
      });
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
      className="mx-auto mt-6 flex min-h-[65dvh] w-full max-w-[640px] flex-col gap-5 text-zoop-ink md:min-h-[580px]"
      data-screen-id={ids.length ? 'D-WAT-01b' : 'D-WAT-01'}
      aria-busy={busy}
    >
      <button
        type="button"
        className={`self-start text-sm font-semibold max-md:min-h-10 max-md:min-w-10 ${focusRing} disabled:cursor-default disabled:opacity-50`}
        disabled={busy}
        onClick={() => navigate(previous)}
      >
        ← 이전 단계
      </button>
      <h1 className="text-[21px] font-bold md:text-2xl">
        관심 있는 종목을 골라 주세요
      </h1>
      <p className="text-sm leading-relaxed text-zoop-ink">
        고른 종목을 중심으로 내 종목 지도를 보여드려요. 나중에 [내 종목]에서
        언제든 바꿀 수 있어요.
      </p>
      {lookup.loading && (
        <p role="status" className="text-sm text-zoop-ink">
          보유 종목과 관심 목록을 확인하고 있어요.
        </p>
      )}
      {(lookup.settingsError || lookup.portfolioError) && (
        <div
          role="alert"
          className="flex flex-col items-start gap-2 text-sm leading-relaxed text-red-800"
        >
          <p>
            {lookup.settingsError
              ? '관심 목록을 불러오지 못했어요.'
              : '보유 종목을 불러오지 못했어요.'}{' '}
            확인 후 시작할 수 있어요.
          </p>
          <button
            type="button"
            className={outlineButton}
            disabled={busy}
            onClick={() => setRetry((v) => v + 1)}
          >
            조회 다시 시도
          </button>
        </div>
      )}
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const term = draft.searchInput.trim();
          if (busy || !ownsDraft || !term) return;
          draft.setSearchSubmitted(term);
          setSearchRetry((v) => v + 1);
        }}
      >
        <label className="sr-only" htmlFor="watchlist-query">
          기업명이나 종목 코드
        </label>
        <input
          id="watchlist-query"
          className={`w-full min-w-0 rounded border border-gray-300 bg-white px-3 py-2.5 ${focusRing} disabled:opacity-50`}
          placeholder="기업명이나 종목 코드로 검색"
          value={ownsDraft ? draft.searchInput : ''}
          disabled={busy || !ownsDraft}
          onChange={(e) => draft.setSearchInput(e.target.value)}
        />
        <button
          type="submit"
          className={outlineButton}
          disabled={busy || !ownsDraft}
        >
          검색
        </button>
      </form>
      <section aria-label="고른 종목">
        <div className="flex justify-between text-sm">
          <h2 className="font-bold">☆ 고른 종목</h2>
          <span className="text-zoop-ink">{ids.length}개</span>
        </div>
        {ids.length > 0 ? (
          <ul className="mt-3 flex flex-wrap gap-2">
            {ids.map((id) => (
              <li
                key={id}
                className="flex items-center gap-2 rounded-full border border-gray-300 bg-white px-2 py-1 text-sm"
              >
                <span
                  className="grid size-5 shrink-0 place-items-center rounded-full bg-gray-200 text-[11px]"
                  aria-hidden="true"
                >
                  {(draft.watchlistNames[id] ?? id).slice(0, 1)}
                </span>
                <span>{draft.watchlistNames[id] ?? id}</span>
                <button
                  type="button"
                  className={`min-h-6 min-w-6 rounded-full max-md:min-h-10 max-md:min-w-10 ${focusRing} disabled:cursor-default disabled:opacity-50`}
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
            <p className="mt-2.5 rounded border border-dashed border-gray-300 p-3 text-sm leading-relaxed text-zoop-ink">
              {holdings?.length
                ? '관심 종목을 추가하지 않아도 보유 종목으로 내 종목 지도를 시작할 수 있어요.'
                : '관심 종목 없이 시작하면 시장 전체 지도가 열려요.'}
            </p>
          )
        )}
      </section>
      <div aria-label="기업 검색 결과">
        {query !== null &&
          !search.loading &&
          !search.error &&
          search.items.length > 0 && (
            <div className="mb-2 flex justify-between text-sm">
              <h2 className="font-bold">'{query}' 검색 결과</h2>
              <span className="text-zoop-ink">
                {search.items.length}개 종목
              </span>
            </div>
          )}
        {search.loading && (
          <p role="status" className="text-sm text-zoop-ink">
            검색하고 있어요.
          </p>
        )}
        {search.error && (
          <div
            role="alert"
            className="flex flex-col items-start gap-2 text-sm text-red-800"
          >
            <p>검색 결과를 불러오지 못했어요.</p>
            <button
              type="button"
              className={outlineButton}
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
            <p role="status" className="text-sm text-zoop-ink">
              검색 결과가 없어요.
            </p>
          )}
        {search.items.length > 0 && (
          <ul className="divide-y divide-gray-100 rounded-md border border-gray-200 bg-white">
            {search.items.map((company) => (
              <li
                key={company.id}
                className="flex items-center gap-2 p-3 md:gap-3"
              >
                <CompanyLogo
                  name={company.name}
                  logoUrl={company.logoUrl}
                  className="size-7 rounded-full bg-gray-200"
                />
                <div className="min-w-0 flex-1">
                  <strong className="text-sm">{company.name}</strong>
                  <small className="mt-1 block text-[11px] text-zoop-ink">
                    {company.ticker ?? company.id} · 승인된 사건{' '}
                    {company.issueCount}건
                  </small>
                </div>
                {heldIds.has(company.id) && (
                  <span className="shrink-0 rounded-full bg-gray-200 px-2 py-0.5 text-[11px] font-semibold text-zoop-ink">
                    보유
                  </span>
                )}
                <button
                  type="button"
                  className={outlineButton}
                  disabled={busy || !ready || ids.includes(company.id)}
                  onClick={() => draft.addWatchlistCompany(company)}
                  aria-label={`${company.name} ${ids.includes(company.id) ? '선택됨' : '추가'}`}
                >
                  {ids.includes(company.id) ? '선택됨' : '추가'}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="mt-auto pt-10">
        {saveError && (
          <p role="alert" className="mb-3 text-sm leading-relaxed text-red-800">
            관심 종목을 저장하지 못했어요. 선택한 목록은 유지됩니다. 다시 시도해
            주세요.
          </p>
        )}
        <button
          type="button"
          className={`min-h-11 w-full rounded bg-gray-950 font-bold text-white ${focusRing} disabled:cursor-default disabled:opacity-50`}
          disabled={!ready || busy}
          onClick={() => void complete()}
        >
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
