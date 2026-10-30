import { useCallback, useState, type FormEvent } from 'react';
import ErrorNotice from '@/components/common/ErrorNotice';
import CompanyMark from '@/components/stocks/CompanyMark';
import HeldBadge from '@/components/stocks/HeldBadge';
import { searchCompanies } from '@/apis/companies/companies';
import { useAsyncData } from '@/hooks/useAsyncData';
import type { CompanySearchProps } from '@/types/company';

// 기업 검색 후 결과 행에서 추가·해제한다. 초기 설정 관심 종목과 내 종목 관심 추가가 함께 쓴다.
// - 검색은 [검색] 버튼이나 Enter로만 실행한다. 입력만으로는 조회하지 않는다.
// - 앞뒤 공백을 뺀 검색어가 비면 요청하지 않고 입력을 안내한다.
// - 결과는 마지막으로 실행한 검색어의 응답만 보인다(늦게 온 이전 응답은 버린다).
// - 실패하면 검색어를 그대로 두고 이 영역에서만 다시 시도한다.
// - 검색어는 바깥이 들고 있어 화면을 오가도 검색어·결과 맥락이 유지된다.
// - 행을 누르면 onToggle만 부른다. 저장은 각 화면이 맡는다.
export default function CompanySearch({
  label = '종목 검색',
  terms,
  onTermsChange,
  selectedIds,
  heldIds = [],
  onToggle,
  disabled = false,
  addLabel = '추가',
}: CompanySearchProps) {
  const { draft, query } = terms;
  const [emptyHint, setEmptyHint] = useState(false);
  const load = useCallback(
    () => (query ? searchCompanies(query) : Promise.resolve(null)),
    [query],
  );
  const search = useAsyncData(load);
  const items = search.data?.items ?? [];

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const next = draft.trim();
    setEmptyHint(next.length === 0);
    if (!next) return;
    if (next === query) search.reload();
    else onTermsChange({ draft, query: next });
  };

  return (
    <div className="flex flex-col gap-3">
      <form
        role="search"
        aria-label={label}
        onSubmit={submit}
        className="flex gap-2"
      >
        <input
          type="search"
          aria-label={label}
          value={draft}
          onChange={(event) => {
            onTermsChange({ draft: event.target.value, query });
            if (emptyHint) setEmptyHint(false);
          }}
          placeholder="기업명이나 종목 코드로 검색"
          autoComplete="off"
          enterKeyHint="search"
          className="min-w-0 flex-1 rounded-xl border border-gray-300 bg-white px-4 py-2.5 text-sm outline-none focus:border-gray-950"
        />
        <button
          type="submit"
          className="shrink-0 rounded-xl bg-gray-950 px-4 py-2.5 text-sm font-semibold text-white hover:bg-gray-800"
        >
          검색
        </button>
      </form>
      {emptyHint && (
        <p role="alert" className="text-sm font-medium text-red-700">
          검색할 기업명이나 종목 코드를 입력해 주세요.
        </p>
      )}
      {query && (
        <div aria-live="polite" aria-busy={search.status === 'loading'}>
          {search.status === 'loading' && (
            <p role="status" className="text-sm text-zoop-ink">
              ‘{query}’ 종목을 찾고 있어요
            </p>
          )}
          {search.status === 'error' && (
            <ErrorNotice
              title={`‘${query}’ 검색을 하지 못했어요`}
              message="검색어는 그대로 두었어요. 다시 시도해 주세요."
              onRetry={search.reload}
            />
          )}
          {search.status === 'success' && items.length === 0 && (
            <p className="text-sm text-zoop-ink">
              ‘{query}’와 맞는 종목이 없어요. 검색어를 고쳐 다시 검색해 보세요.
            </p>
          )}
          {search.status === 'success' && items.length > 0 && (
            <>
              <p className="text-sm text-zoop-ink">
                ‘{query}’ 검색 결과{' '}
                <span className="tabular-nums">{items.length}개 종목</span>
              </p>
              <ul
                aria-label={`‘${query}’ 검색 결과`}
                className="mt-2 divide-y divide-gray-100"
              >
                {items.map((company) => {
                  const picked = selectedIds.includes(company.id);
                  return (
                    <li
                      key={company.id}
                      className="flex items-center gap-3 py-3"
                    >
                      <CompanyMark
                        name={company.name}
                        logoUrl={company.logoUrl}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-medium text-zoop-ink">
                          {company.name}
                        </p>
                        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-zoop-ink">
                          <span className="tabular-nums">
                            {[
                              company.ticker,
                              `승인된 사건 ${company.issueCount}건`,
                            ]
                              .filter(Boolean)
                              .join(' · ')}
                          </span>
                          {heldIds.includes(company.id) && <HeldBadge />}
                        </p>
                      </div>
                      <button
                        type="button"
                        aria-pressed={picked}
                        aria-label={`${company.name} ${picked ? '선택됨' : addLabel}`}
                        disabled={disabled}
                        onClick={() => onToggle(company)}
                        className={`shrink-0 rounded-lg px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${
                          picked
                            ? 'bg-gray-950 text-white'
                            : 'border border-gray-300 text-zoop-ink hover:bg-gray-50'
                        }`}
                      >
                        {picked ? '선택됨' : addLabel}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}
