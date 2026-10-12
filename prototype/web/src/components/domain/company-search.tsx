// CompanySearch: 기업을 검색해 행을 눌러 추가·해제한다. 온보딩과 내 종목(관심 종목 추가)이 함께 쓴다.
// FS011-01(D01): 검색은 [검색] 버튼이나 Enter로만 실행한다. 입력만으로는 조회하지 않는다.
//  - 앞뒤 공백을 뺀 검색어가 비면 요청하지 않고 입력을 안내한다.
//  - 결과는 마지막으로 실행한 검색어의 응답만 보인다(검색어마다 조회 칸이 달라 늦게 온 이전 응답이 덮지 않는다).
//    입력을 고쳐도 다시 검색하기 전까지는 어떤 검색어의 결과인지 함께 적는다.
//  - 실패하면 검색어를 그대로 두고 이 영역에서만 다시 시도한다.
//  - 행을 누르면 편집 중인 목록에만 반영한다. 저장은 각 화면의 저장 기능이 한다.
// 결과 행은 ListRow 버튼(aria-pressed=고른 상태). 행 안에 다른 버튼을 두지 않는다.
import { ArrowRight, Check, Plus, Search } from "lucide-react";
import { useState, type FormEvent, type Ref } from "react";
import type { Schemas } from "@/api/client";
import { useCompanySearch } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { Input } from "@/components/ui/input";
import { ListRow } from "@/components/ui/list-row";
import { CompanyMark } from "./company-mark";

interface CompanySearchProps {
  /** 이미 고른 기업 id(행에 '선택됨'으로 보인다) */
  selectedIds: string[];
  onToggle: (company: Schemas["CompanySummary"]) => void;
  label?: string;
  disabled?: boolean;
  inputRef?: Ref<HTMLInputElement>;
  /** 상세 안에서 기업을 전환하는 행에는 추가 대신 이동 아이콘을 쓴다. */
  navigation?: boolean;
}

export function CompanySearch({ selectedIds, onToggle, label = "종목 검색", disabled, inputRef, navigation = false }: CompanySearchProps) {
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [emptyHint, setEmptyHint] = useState(false);
  const search = useCompanySearch(query);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const q = draft.trim();
    setEmptyHint(q.length === 0);
    if (!q) return;
    if (q === query) void search.refetch();
    else setQuery(q);
  };

  return (
    <div className="flex flex-col gap-2">
      <form role="search" aria-label={label} onSubmit={submit} className="flex items-end gap-2 px-4">
        <Input
          ref={inputRef}
          label={label}
          variant="search"
          className="min-w-0 flex-1"
          placeholder="종목명이나 종목 코드"
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            if (emptyHint) setEmptyHint(false);
          }}
          onClear={() => {
            setDraft("");
            setQuery("");
            setEmptyHint(false);
          }}
          autoComplete="off"
          enterKeyHint="search"
        />
        <Button type="submit" variant="secondary">
          <Search aria-hidden="true" />
          검색
        </Button>
      </form>
      {emptyHint && (
        <p role="alert" className="px-4 text-sm font-medium text-error">
          검색할 종목명이나 종목 코드를 입력해 주세요.
        </p>
      )}
      {query && (
        <div aria-busy={search.isFetching} aria-live="polite">
          {search.isPending && <SkeletonRows count={3} label={`‘${query}’ 종목을 찾고 있어요`} />}
          {search.isError && (
            <ErrorState
              className="px-4"
              error={search.error}
              title={`‘${query}’ 검색을 하지 못했어요`}
              message="검색어는 그대로 두었어요. 다시 시도해 주세요."
              onRetry={() => void search.refetch()}
              compact
            />
          )}
          {search.isSuccess && search.data.items.length === 0 && (
            <p className="px-4 py-3 text-base text-text-secondary">‘{query}’와 맞는 종목이 없어요. 검색어를 고쳐 다시 검색해 보세요.</p>
          )}
          {search.isSuccess && search.data.items.length > 0 && (
            <>
              <p className="px-4 text-sm text-text-secondary">
                ‘{query}’ 검색 결과 <span className="tabular-nums">{search.data.items.length}</span>개
              </p>
              <ul aria-label={`‘${query}’ 검색 결과`} className="stagger">
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
                            {company.ticker ? `${company.ticker} · ` : ""}사건 {company.issueCount}건{picked ? " · 선택됨" : ""}
                          </span>
                        }
                        trailing={
                          picked ? (
                            <Check className="size-5 text-brand-primary" aria-hidden="true" />
                          ) : (
                            navigation ? <ArrowRight className="size-5 text-text-primary" aria-hidden="true" /> : <Plus className="size-5 text-text-primary" aria-hidden="true" />
                          )
                        }
                      />
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
