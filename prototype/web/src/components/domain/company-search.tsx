// CompanySearch: 기업을 검색해 행을 눌러 추가·해제한다. 온보딩과 내 종목(관심 종목 추가)이 함께 쓴다.
// 결과 행은 ListRow 버튼(aria-pressed=고른 상태). 행 안에 다른 버튼을 두지 않는다.
import { Check, Plus } from "lucide-react";
import { useEffect, useState, type Ref } from "react";
import type { Schemas } from "@/api/client";
import { useCompanySearch } from "@/api/queries";
import { ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { Input } from "@/components/ui/input";
import { ListRow } from "@/components/ui/list-row";
import { CompanyMark } from "./company-mark";

interface CompanySearchProps {
  /** 이미 고른 기업 id(행에 '선택됨'으로 보인다) */
  selectedIds: string[];
  onToggle: (company: Schemas["CompanySummary"]) => void;
  label?: string;
  /** false면 검색어를 입력하기 전에는 결과를 숨긴다. */
  showWhenEmpty?: boolean;
  disabled?: boolean;
  inputRef?: Ref<HTMLInputElement>;
}

export function CompanySearch({ selectedIds, onToggle, label = "종목 검색", showWhenEmpty = true, disabled, inputRef }: CompanySearchProps) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const search = useCompanySearch(debounced);
  const visible = showWhenEmpty || debounced.length > 0;

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(timer);
  }, [query]);

  return (
    <div className="flex flex-col gap-2">
      <div className="px-4">
        <Input
          ref={inputRef}
          label={label}
          variant="search"
          placeholder="종목명이나 종목 코드"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onClear={() => setQuery("")}
          autoComplete="off"
        />
      </div>
      {visible && (
        <div aria-busy={search.isFetching} aria-live="polite">
          {search.isPending && <SkeletonRows count={3} label="종목을 찾고 있어요" />}
          {search.isError && (
            <ErrorState className="px-4" error={search.error} title="종목을 검색하지 못했어요" onRetry={() => void search.refetch()} compact />
          )}
          {search.data && search.data.items.length === 0 && (
            <p className="px-4 py-3 text-base text-text-secondary">‘{debounced}’와 맞는 종목이 없어요. 다른 이름으로 찾아보세요.</p>
          )}
          {search.data && search.data.items.length > 0 && (
            <ul aria-label="검색 결과" className="stagger">
              {search.data.items.map((company) => {
                const picked = selectedIds.includes(company.id);
                return (
                  <li key={company.id}>
                    <ListRow
                      onClick={() => onToggle(company)}
                      disabled={disabled}
                      selected={picked}
                      leading={<CompanyMark id={company.id} name={company.name} brandColor={company.brandColor} logoUrl={company.logoUrl} />}
                      title={company.name}
                      description={
                        <span className="tabular-nums">
                          {company.ticker ? `${company.ticker} · ` : ""}사건 {company.issueCount}건
                        </span>
                      }
                      trailing={
                        picked ? (
                          <Check className="size-5 text-brand-primary" aria-hidden="true" />
                        ) : (
                          <Plus className="size-5 text-text-primary" aria-hidden="true" />
                        )
                      }
                    />
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
