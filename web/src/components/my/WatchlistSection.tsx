import { useEffect, useRef, useState } from 'react';
import ErrorNotice from '@/components/common/ErrorNotice';
import StockRow from '@/components/my/StockRow';
import CompanySearch from '@/components/stocks/CompanySearch';
import HeldBadge from '@/components/stocks/HeldBadge';
import { getCompanyBrief } from '@/apis/companies/companies';
import { setWatched } from '@/apis/watchlist/watchlist';
import type { CompanyBrief, CompanySummary } from '@/types/company';
import type { WatchChange, WatchlistSectionProps } from '@/types/my';

type BriefEntry =
  { status: 'success'; data: CompanyBrief } | { status: 'error' };

function applyChange(savedIds: string[], change: WatchChange | null) {
  if (!change) return savedIds;
  const rest = savedIds.filter((id) => id !== change.companyId);
  return change.watched ? [...rest, change.companyId] : rest;
}

// D-MY-01 / 01b 관심 종목
// - 검색 결과 추가·빼기가 곧 저장이다(PUT /api/v1/me/watchlist/{id}). 응답 전에도 목록에 반영한다.
// - 저장에 실패하면 목록을 이전 상태로 되돌리고 하단 알림의 [다시 시도]로 같은 변경을 다시 보낸다.
// - 저장 중에는 다른 변경을 막아 응답 순서가 엇갈리지 않게 한다.
// - 행: 종목 코드·승인된 사건 수, 보유 중이면 '보유' 배지. 보유·관심이 모두 없으면 지도 안내를 보인다.
export default function WatchlistSection({
  settings,
  portfolio,
  terms,
  onTermsChange,
}: WatchlistSectionProps) {
  const { setData: setSettings } = settings;
  const [pending, setPending] = useState<WatchChange | null>(null);
  const [failed, setFailed] = useState<WatchChange | null>(null);
  const [briefs, setBriefs] = useState<Record<string, BriefEntry>>({});
  const requested = useRef(new Set<string>());
  const [briefAttempt, setBriefAttempt] = useState(0);

  const savedIds = settings.data?.watchlistIds ?? [];
  const shownIds = applyChange(savedIds, pending);
  const heldIds = portfolio.data?.connected
    ? portfolio.data.holdings.map((holding) => holding.companyId)
    : [];
  const shownKey = shownIds.join('\n');

  // 행 표시용 기업 요약은 한 번만 받아 둔다(검색 결과에서 추가한 기업은 이미 있다).
  useEffect(() => {
    if (!shownKey) return;
    for (const id of shownKey.split('\n')) {
      if (requested.current.has(id)) continue;
      requested.current.add(id);
      getCompanyBrief(id).then(
        (data) =>
          setBriefs((previous) => ({
            ...previous,
            [id]: { status: 'success', data },
          })),
        () =>
          setBriefs((previous) => ({ ...previous, [id]: { status: 'error' } })),
      );
    }
  }, [shownKey, briefAttempt]);

  /** 기업 정보 조회에 실패한 행만 다시 조회한다. */
  const retryBrief = (id: string) => {
    requested.current.delete(id);
    setBriefs((previous) => {
      const next = { ...previous };
      delete next[id];
      return next;
    });
    setBriefAttempt((value) => value + 1);
  };

  const change = async (next: WatchChange) => {
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

  const toggleFromSearch = (company: CompanySummary) => {
    if (!requested.current.has(company.id)) {
      requested.current.add(company.id);
      setBriefs((previous) => ({
        ...previous,
        [company.id]: {
          status: 'success',
          data: {
            id: company.id,
            name: company.name,
            ticker: company.ticker,
            issueCount: company.issueCount,
          },
        },
      }));
    }
    void change({
      companyId: company.id,
      name: company.name,
      watched: !shownIds.includes(company.id),
    });
  };

  return (
    <section
      aria-labelledby="my-watchlist"
      className="rounded-xl border border-gray-200 bg-white p-5"
    >
      <div className="mb-3 flex items-center gap-2">
        <h2 id="my-watchlist" className="flex-1 text-lg font-semibold">
          관심 종목
        </h2>
        {settings.status === 'success' && (
          <span className="text-sm text-gray-500 tabular-nums">
            {shownIds.length}개{pending && ' · 저장 중'}
          </span>
        )}
      </div>

      {settings.status === 'loading' && (
        <p role="status" className="text-sm text-gray-500">
          관심 종목을 불러오고 있어요
        </p>
      )}
      {settings.status === 'error' && (
        <ErrorNotice
          title="관심 종목을 불러오지 못했어요"
          onRetry={settings.reload}
        />
      )}

      {settings.status === 'success' &&
        (shownIds.length === 0 ? (
          <p className="rounded-xl border border-dashed border-gray-300 px-4 py-3 text-sm text-gray-600">
            아직 관심 종목이 없어요. 아래에서 기업을 검색해 추가하면 내 종목
            지도에 함께 보여요.
          </p>
        ) : (
          <ul aria-label="관심 종목 목록" className="divide-y divide-gray-100">
            {shownIds.map((id) => {
              const entry = briefs[id];
              const brief = entry?.status === 'success' ? entry.data : null;
              const name = brief?.name ?? '종목';
              const removeButton = (
                <button
                  type="button"
                  aria-label={`${name} 관심 종목에서 빼기`}
                  disabled={pending !== null}
                  onClick={() =>
                    void change({ companyId: id, name, watched: false })
                  }
                  className="flex size-9 shrink-0 items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100 hover:text-gray-950 disabled:cursor-not-allowed disabled:text-gray-300"
                >
                  ×
                </button>
              );
              if (!brief) {
                return (
                  <li key={id} className="flex items-center gap-2 py-3">
                    <p className="flex-1 text-sm text-gray-500">
                      {entry?.status === 'error'
                        ? '종목 정보를 불러오지 못했어요.'
                        : '종목 정보를 불러오고 있어요'}
                    </p>
                    {entry?.status === 'error' && (
                      <button
                        type="button"
                        aria-label="종목 정보 다시 불러오기"
                        onClick={() => retryBrief(id)}
                        className="shrink-0 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-900 hover:bg-gray-50"
                      >
                        다시 시도
                      </button>
                    )}
                    {removeButton}
                  </li>
                );
              }
              return (
                <StockRow
                  key={id}
                  id={id}
                  name={brief.name}
                  description={
                    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="tabular-nums">
                        {[
                          brief.ticker,
                          `승인된 사건 ${brief.issueCount}건`,
                          pending?.companyId === id && '저장 중',
                        ]
                          .filter(Boolean)
                          .join(' · ')}
                      </span>
                      {heldIds.includes(id) && <HeldBadge />}
                    </span>
                  }
                  action={removeButton}
                />
              );
            })}
          </ul>
        ))}

      {settings.status === 'success' && (
        <div className="mt-5 flex flex-col gap-3">
          <h3 className="text-base font-semibold">관심 종목 추가</h3>
          <CompanySearch
            label="관심 종목 추가"
            terms={terms}
            onTermsChange={onTermsChange}
            selectedIds={shownIds}
            heldIds={heldIds}
            onToggle={toggleFromSearch}
            disabled={pending !== null}
            addLabel="관심 추가"
          />
          {portfolio.status === 'success' &&
            heldIds.length === 0 &&
            shownIds.length === 0 && (
              <p className="text-sm text-gray-500">
                보유·관심이 모두 없으면 지도는 시장 전체로 열려요.
              </p>
            )}
        </div>
      )}

      {failed && (
        <div
          role="alert"
          className="fixed inset-x-4 bottom-20 z-[60] flex items-center gap-3 rounded-xl bg-gray-950 py-2 pr-2 pl-4 text-sm text-white shadow-lg md:inset-x-auto md:right-6 md:bottom-6 md:w-96"
        >
          <p className="min-w-0 flex-1">
            관심 종목을 저장하지 못했어요. 목록을 이전 상태로 되돌렸어요.
          </p>
          <button
            type="button"
            onClick={() => void change(failed)}
            className="shrink-0 rounded-lg px-2 py-2 font-semibold underline underline-offset-2"
          >
            다시 시도
          </button>
        </div>
      )}
    </section>
  );
}
