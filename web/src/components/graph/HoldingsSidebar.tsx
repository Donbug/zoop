import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import CompanyLogo from '@/components/common/CompanyLogo';
import LoadingIndicator from '@/components/common/LoadingIndicator';
import StockQuote from '@/components/stocks/StockQuote';
import { getPortfolio } from '@/apis/portfolio/portfolio';
import { getSettings } from '@/apis/settings/settings';
import { setWatched } from '@/apis/watchlist/watchlist';
import { getCompanyBrief } from '@/apis/companies/companies';
import { useAsyncData } from '@/hooks/useAsyncData';
import { useAuthStore } from '@/stores/useAuthStore';
import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import type { GraphResponse } from '@/types/map/graph';
import type { CompanyBrief } from '@/types/company';
import type { WatchSync } from '@/types/map';

function complete(value: unknown) {
  if (!value || typeof value !== 'object') return false;
  const metadata = (value as { metadata?: { partial?: boolean } }).metadata;
  return metadata?.partial !== true;
}

async function loadPortfolio() {
  const value = await getPortfolio();
  if (!complete(value) || !Array.isArray(value.holdings))
    throw new Error('불완전한 보유 종목 응답');
  return value;
}

async function loadSettings() {
  const value = await getSettings();
  if (!complete(value) || !Array.isArray(value.watchlistIds))
    throw new Error('불완전한 관심 종목 응답');
  return value;
}

type Props = {
  member: boolean;
  logoOf: (companyId: string) => string | null | undefined;
  graph?: GraphResponse | null;
  onPick: (companyId: string) => void;
  onClose: () => void;
  /** 지도 화면에서 마지막으로 저장한 관심 목록(기업 상세에서 저장한 것 포함). */
  watchSync?: WatchSync | null;
  onWatchChanged?: (watchlistIds: string[]) => void;
};

// D-GRP-01/01b: member holdings and watchlist, with explicit confirmed writes.
export default function HoldingsSidebar({
  member,
  logoOf,
  graph,
  onPick,
  onClose,
  watchSync,
  onWatchChanged,
}: Props) {
  const location = useLocation();
  return (
    <aside
      aria-labelledby="holdings-sidebar-title"
      className="flex w-[280px] shrink-0 flex-col overflow-hidden rounded-[6px] border-[0.667px] border-zoop-line bg-zoop-paper max-md:w-full"
    >
      <header className="flex items-center justify-between border-b-[0.667px] border-zoop-line px-4 py-3">
        <h2
          id="holdings-sidebar-title"
          className="m-0 text-lead font-bold text-zoop-ink"
        >
          내 종목
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="내 종목 사이드바 닫기"
          className="grid size-7 place-items-center rounded text-zoop-muted hover:bg-zoop-soft focus-visible:outline-2"
        >
          ×
        </button>
      </header>
      {member ? (
        <HoldingsList
          logoOf={logoOf}
          graph={graph}
          onPick={onPick}
          watchSync={watchSync}
          onWatchChanged={onWatchChanged}
        />
      ) : (
        <p className={`${ui.muted} px-4 py-4`}>
          로그인하면 가상 계좌의 보유 종목과 관심 종목을 볼 수 있어요.{' '}
          <Link
            to="/login"
            state={{ from: location }}
            className="font-semibold underline"
          >
            로그인
          </Link>
        </p>
      )}
    </aside>
  );
}

function HoldingsList({
  logoOf,
  graph,
  onPick,
  watchSync,
  onWatchChanged,
}: Omit<Props, 'member' | 'onClose'>) {
  const portfolio = useAsyncData(loadPortfolio);
  const settings = useAsyncData(loadSettings);
  // 다른 곳(기업 상세)에서 저장한 관심 목록을 받으면 별·목록·빈 안내를 그 목록으로 맞춘다.
  // 처음 열 때의 값은 이미 조회 결과에 들어 있으므로 그 뒤에 바뀐 것만 반영한다.
  const [appliedSync, setAppliedSync] = useState(watchSync?.seq ?? 0);
  if (watchSync && watchSync.seq !== appliedSync) {
    setAppliedSync(watchSync.seq);
    if (settings.status === 'success')
      settings.setData({ ...settings.data, watchlistIds: watchSync.ids });
    else settings.reload();
  }
  const watchKey = settings.data?.watchlistIds.join('\u001f') ?? '';
  const loadWatch = useCallback(async () => {
    const ids = watchKey ? watchKey.split('\u001f') : [];
    const results = await Promise.allSettled(
      ids.map(async (id) => {
        const company = await getCompanyBrief(id);
        if (company.id !== id) throw new Error('기업 응답 불일치');
        return company;
      }),
    );
    return results.map((result, index) => ({
      id: ids[index],
      company: result.status === 'fulfilled' ? result.value : null,
    }));
  }, [watchKey]);
  const watchedCompanies = useAsyncData(loadWatch);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState('');
  const lock = useRef(false);
  const active = useRef(true);
  const watchSection = useRef<HTMLElement>(null);
  const focusAfter = useRef<number | null>(null);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    if (focusAfter.current === null || watchedCompanies.status !== 'success')
      return;
    const rows = [...(watchSection.current?.querySelectorAll('li') ?? [])];
    const target =
      rows[
        Math.min(focusAfter.current, rows.length - 1)
      ]?.querySelector<HTMLElement>('button:last-child') ??
      watchSection.current?.querySelector<HTMLElement>('a, button');
    focusAfter.current = null;
    target?.focus();
  }, [watchedCompanies.status, watchKey]);
  const watched = new Set(settings.data?.watchlistIds ?? []);
  const canInferNoEvents =
    graph && !graph.metadata.partial && !graph.metadata.truncated;
  const noEvents = (id: string) =>
    canInferNoEvents &&
    graph.nodes.some((node) => node.id === id && node.kind === 'company') &&
    !graph.edges.some((edge) => edge.source === id || edge.target === id);
  async function toggle(
    id: string,
    currentlyWatched: boolean,
    inWatchSection: boolean,
  ) {
    if (lock.current || settings.status !== 'success') return;
    lock.current = true;
    setPending(id);
    setError('');
    const focused = document.activeElement;
    const removedIndex = settings.data.watchlistIds.indexOf(id);
    const revision = useAuthStore.getState().sessionRevision;
    try {
      const result = await setWatched(id, !currentlyWatched);
      if (
        !active.current ||
        revision !== useAuthStore.getState().sessionRevision
      )
        return;
      if (
        !complete(result) ||
        !Array.isArray(result.watchlistIds) ||
        result.watchlistIds.includes(id) !== !currentlyWatched
      )
        throw new Error('저장 결과 불일치');
      if (
        inWatchSection &&
        currentlyWatched &&
        (document.activeElement === focused ||
          document.activeElement === document.body)
      )
        focusAfter.current = Math.max(removedIndex, 0);
      settings.setData(result);
      onWatchChanged?.(result.watchlistIds);
    } catch {
      if (
        active.current &&
        revision === useAuthStore.getState().sessionRevision
      )
        setError(
          '관심 종목 저장 결과를 확인하지 못했어요. 다시 확인해 주세요.',
        );
    } finally {
      lock.current = false;
      if (active.current) setPending(null);
    }
  }
  function row(
    id: string,
    name: string,
    logo: string | null | undefined,
    detail: string | null,
    inWatchSection: boolean,
  ) {
    const isWatched = watched.has(id);
    return (
      <li key={id} className="flex items-center pr-3">
        <button
          type="button"
          onClick={() => onPick(id)}
          aria-label={`${name}, 지도에서 보기`}
          className="flex min-w-0 flex-1 items-center gap-3 px-4 py-3 text-left hover:bg-zoop-soft focus-visible:outline-2"
        >
          <CompanyLogo
            name={name}
            logoUrl={logo}
            className="size-9 rounded-full border-[0.667px] border-zoop-line bg-zoop-paper text-body font-bold text-zoop-ink"
          />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-body font-semibold text-zoop-ink">
              {name}
            </span>
            {detail && (
              <span className="block text-caption text-zoop-faint">
                {detail}
              </span>
            )}
            {noEvents(id) && (
              <span className="block text-caption text-zoop-muted">
                연결된 사건 없음
              </span>
            )}
          </span>
          <StockQuote companyId={id} />
        </button>
        <button
          type="button"
          aria-label={`${name} 관심 종목`}
          aria-pressed={isWatched}
          disabled={settings.status !== 'success' || Boolean(pending)}
          onClick={() => void toggle(id, isWatched, inWatchSection)}
          className="grid size-9 shrink-0 place-items-center text-title-sm text-zoop-ink disabled:opacity-50"
        >
          {isWatched ? '★' : '☆'}
        </button>
      </li>
    );
  }
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      {!(
        portfolio.status === 'success' && portfolio.data.holdings.length === 0
      ) && (
        <section aria-label="보유 종목">
          <h3 className="px-4 pt-3 text-caption font-bold text-zoop-muted">
            보유 종목
          </h3>
          {portfolio.status === 'loading' && (
            <LoadingIndicator
              label="보유 종목을 불러오는 중이에요."
              className="flex min-h-10 w-full px-4 text-caption"
            />
          )}
          {portfolio.status === 'error' && (
            <p role="alert" className="px-4 py-4 text-caption">
              보유 종목을 불러오지 못했어요.{' '}
              <button onClick={portfolio.reload} className="underline">
                다시 시도
              </button>
            </p>
          )}
          {portfolio.status === 'success' &&
            portfolio.data.holdings.length > 0 && (
              <ul>
                {portfolio.data.holdings.map((h) =>
                  row(
                    h.companyId,
                    h.name,
                    logoOf(h.companyId),
                    `${h.quantity.toLocaleString('ko-KR')}주`,
                    false,
                  ),
                )}
              </ul>
            )}
        </section>
      )}
      <section ref={watchSection} aria-label="관심 종목">
        <h3 className="px-4 pt-3 text-caption font-bold text-zoop-muted">
          관심 종목
        </h3>
        {settings.status === 'loading' && (
          <LoadingIndicator
            label="관심 종목을 불러오는 중이에요."
            className="flex min-h-10 w-full px-4 text-caption"
          />
        )}
        {settings.status === 'error' && (
          <p role="alert" className="px-4 py-4 text-caption">
            관심 종목을 불러오지 못했어요.{' '}
            <button onClick={settings.reload} className="underline">
              다시 시도
            </button>
          </p>
        )}
        {settings.status === 'success' &&
          settings.data.watchlistIds.length === 0 && (
            <p className="px-4 py-4 text-caption">
              고른 관심 종목이 없어요.{' '}
              <Link to="/my" className="underline">
                관심 종목 고르기
              </Link>
            </p>
          )}
        {settings.status === 'success' &&
          settings.data.watchlistIds.length > 0 &&
          watchedCompanies.status === 'loading' && (
            <LoadingIndicator
              label="관심 기업을 불러오는 중이에요."
              className="flex min-h-10 w-full px-4 text-caption"
            />
          )}
        {settings.status === 'success' &&
          settings.data.watchlistIds.length > 0 &&
          watchedCompanies.status === 'success' && (
            <ul>
              {watchedCompanies.data.map(
                ({
                  id,
                  company,
                }: {
                  id: string;
                  company: CompanyBrief | null;
                }) =>
                  company ? (
                    row(
                      id,
                      company.name,
                      logoOf(id) ?? company.logoUrl,
                      company.ticker,
                      true,
                    )
                  ) : (
                    <li key={id} className="px-4 py-3 text-caption">
                      기업 정보를 불러오지 못했어요.{' '}
                      <button
                        onClick={watchedCompanies.reload}
                        className="underline"
                      >
                        다시 시도
                      </button>
                    </li>
                  ),
              )}
            </ul>
          )}
        {error && (
          <p role="alert" className="px-4 py-3 text-caption text-zoop-alert">
            {error}
          </p>
        )}
      </section>
    </div>
  );
}
