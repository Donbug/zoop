// FS037 종목 목록: 지도 관계 필터와 분리된 카탈로그. 기업명·영문 별칭·티커는 서버 검색을 그대로 쓴다.
import { ArrowUpRight, Map, Search, Star, Wallet } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router";
import type { Schemas } from "@/api/client";
import { useCompanyList, useCompanyQuote, usePortfolio, useSession, useSettings } from "@/api/queries";
import { CompanyMark } from "@/components/domain/company-mark";
import { GraphModeSwitch, PersonalFilterSwitch } from "@/components/domain/graph-legend";
import { PriceChange } from "@/components/domain/status-labels";
import { WatchToggle } from "@/components/domain/watch-toggle";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { Input } from "@/components/ui/input";
import { Tooltip } from "@/components/ui/tooltip";
import { readPersonalFilter, savePersonalFilter, type PersonalFilter } from "@/lib/personal-filter";
import { formatPrice } from "@/lib/market";

const guestLockedModes = ["personal"] as const;

export function CompaniesPage() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q")?.trim() ?? "";
  const [draft, setDraft] = useState(q);
  const session = useSession();
  const member = session.data?.kind === "member";
  const settings = useSettings(member);
  const portfolio = usePortfolio(member);
  const catalog = useCompanyList(q);
  const personal = params.get("mode") === "personal";
  const [filter, setFilter] = useState<PersonalFilter>(readPersonalFilter);
  const [visibleCount, setVisibleCount] = useState(20);
  const [loginPrompt, setLoginPrompt] = useState(false);
  useEffect(() => { setDraft(q); }, [q]);
  useEffect(() => { setVisibleCount(20); }, [q, personal, filter]);

  const watchIds = new Set(settings.data?.watchlistIds ?? []);
  const holdingIds = new Set(portfolio.data?.holdings.map((h) => h.companyId) ?? []);
  const items = catalog.data?.items.filter((c) => !personal || (filter === "holding" ? holdingIds.has(c.id) : filter === "watch" ? watchIds.has(c.id) : holdingIds.has(c.id) || watchIds.has(c.id))) ?? [];
  const personalError = personal && (filter !== "holding" && settings.isError ? settings : filter !== "watch" && portfolio.isError ? portfolio : null);
  const personalPending = personal && (filter !== "holding" && settings.isPending || filter !== "watch" && portfolio.isPending);
  const location = useLocation();
  const focusedCompany = useRef<string | null>(null);
  const previousRows = useRef<string[]>([]);
  const rowIds = items.slice(0, visibleCount).map((company) => company.id);
  const rowKey = rowIds.join("\0");
  useLayoutEffect(() => {
    const before = previousRows.current;
    previousRows.current = rowIds;
    const removed = focusedCompany.current;
    if (!removed || rowIds.includes(removed) || !before.includes(removed)) return;
    focusedCompany.current = null;
    if (document.activeElement && document.activeElement !== document.body) return;
    const next = rowIds[Math.min(before.indexOf(removed), rowIds.length - 1)];
    const target = next ? document.querySelector<HTMLElement>(`[data-company-id="${CSS.escape(next)}"] button`) : null;
    (target ?? document.querySelector<HTMLInputElement>('input[type="search"]'))?.focus();
    // 행 목록이 바뀔 때만. 관심 해제로 행이 사라져도 포커스를 본문으로 잃지 않는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rowKey]);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 px-4 py-5 md:px-6 md:py-6">
      <h1 className="text-2xl font-bold text-text-primary">종목</h1>
      <form className="flex items-end gap-2" onSubmit={(e) => {
        e.preventDefault();
        setParams((prev) => { const next = new URLSearchParams(prev); if (draft.trim()) next.set("q", draft.trim()); else next.delete("q"); return next; });
      }}>
        <Input label="기업명·영문명·티커 검색" placeholder="기업명, 영문명 또는 티커" variant="search" value={draft} onChange={(e) => setDraft(e.target.value)} onClear={() => { setDraft(""); setParams((prev) => { const next = new URLSearchParams(prev); next.delete("q"); return next; }); }} className="min-w-0 flex-1" />
        <Button type="submit" variant="secondary"><Search aria-hidden="true" />검색</Button>
      </form>
      <div className="flex flex-wrap items-center gap-2">
        <GraphModeSwitch value={personal ? "personal" : "all"} lockedModes={member ? [] : [...guestLockedModes]} onValueChange={(mode) => {
          if (!member && mode === "personal") { setLoginPrompt(true); return; }
          setLoginPrompt(false);
          setParams((prev) => { const next = new URLSearchParams(prev); if (mode === "personal") next.set("mode", mode); else next.delete("mode"); return next; });
        }} />
        {member && personal && <PersonalFilterSwitch value={filter} holdingCount={portfolio.data?.holdings.length ?? null} watchCount={settings.data?.watchlistIds.length ?? null} onValueChange={(next) => { setFilter(next); savePersonalFilter(next); }} />}
      </div>
      {(!member && personal || loginPrompt) ? <EmptyState title="로그인하면 내 종목 목록을 볼 수 있어요" action={<Button asChild><Link to="/login">로그인</Link></Button>} /> : personalError ? <ErrorState title="내 종목 목록을 불러오지 못했어요" error={personalError.error} onRetry={() => void personalError.refetch()} /> : catalog.isPending || personalPending ? <SkeletonRows count={5} label="종목을 불러오고 있어요" /> : catalog.isError ? <ErrorState title="종목 목록을 불러오지 못했어요" error={catalog.error} onRetry={() => void catalog.refetch()} /> : items.length === 0 ? <EmptyState title={q ? "검색 결과가 없어요" : "이 범위의 종목이 없어요"} description={q ? "다른 기업명이나 티커로 검색해 주세요." : "시장 전체에서 종목을 찾아보세요."} /> : (
        <section aria-label="종목 목록" className="flex flex-col">
          <p role="status" className="pb-2 text-sm text-text-secondary tabular-nums">{items.length}개 종목</p>
          <ul className="divide-y divide-border-subtle border-y border-border-subtle" onFocusCapture={(event) => {
            if (event.target instanceof HTMLElement) focusedCompany.current = event.target.closest("[data-company-id]")?.getAttribute("data-company-id") ?? null;
          }}>
            {items.slice(0, visibleCount).map((company) => <CompanyRow key={company.id} company={company} holding={holdingIds.has(company.id)} watched={watchIds.has(company.id)} from={location.pathname + location.search} />)}
          </ul>
          {visibleCount < items.length && <Button variant="ghost" className="mt-3 self-center" onClick={() => setVisibleCount((n) => n + 20)}>종목 더 보기 ({items.length - visibleCount}개 남음)</Button>}
        </section>
      )}
    </div>
  );
}

function CompanyRow({ company, holding, watched, from }: { company: Schemas["CompanySummary"]; holding: boolean; watched: boolean; from: string }) {
  const quote = useCompanyQuote(company.id);
  const available = quote.data?.status === "available" ? quote.data : null;
  return (
    <li data-company-id={company.id} className="flex items-center gap-2 py-3">
      <Link to={`/companies/${encodeURIComponent(company.id)}`} state={{ from }} className="flex min-h-11 min-w-0 flex-1 items-center gap-3 rounded-sm px-1 text-text-primary hover:bg-surface-sunken" aria-label={`${company.name} 기업 상세`}>
        <CompanyMark id={company.id} name={company.name} brandColor={company.brandColor} logoUrl={company.logoUrl} size={36} />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="text-base font-semibold">{company.name}</span>
          <span className="text-sm text-text-secondary tabular-nums">{company.ticker ? `${company.ticker} · ` : ""}승인 사건 {company.issueCount}건</span>
          {(holding || watched) && <span className="flex gap-2 text-sm text-text-secondary">{holding && <span className="inline-flex items-center gap-1"><Wallet className="size-4" aria-hidden="true" />보유</span>}{watched && <span className="inline-flex items-center gap-1"><Star className="size-4" aria-hidden="true" />관심</span>}</span>}
        </div>
        {available && <div className="flex shrink-0 flex-col items-end gap-1"><span className="text-base font-semibold tabular-nums">{formatPrice(available.quote.price, available.quote.currency)}</span><PriceChange changePercent={available.quote.changeRate === null ? null : available.quote.changeRate * 100} className="text-sm" /></div>}
        <ArrowUpRight className="hidden size-4 shrink-0 text-text-tertiary md:block" aria-hidden="true" />
      </Link>
      <Tooltip content="지도에서 보기"><Button variant="ghost" size="icon" asChild><Link to={`/?mode=all&select=node:${encodeURIComponent(company.id)}`} aria-label={`${company.name} 지도에서 보기`}><Map aria-hidden="true" /></Link></Button></Tooltip>
      <WatchToggle companyId={company.id} companyName={company.name} variant="icon" />
    </li>
  );
}
