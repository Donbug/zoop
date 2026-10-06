import { ArrowLeftRight, Building2, History, Network, Star, Wallet } from "lucide-react";
import { useEffect, useState } from "react";
import { useCompanies, useCompanyQuote, usePortfolio, useSession, useSettings } from "@/api/queries";
import type { Schemas } from "@/api/client";
import { CompanySearch } from "@/components/domain/company-search";
import { CompanyMark } from "@/components/domain/company-mark";
import { PriceChange } from "@/components/domain/status-labels";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/dialog";
import { ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { ListRow } from "@/components/ui/list-row";
import { SectionHeader } from "@/components/ui/section-header";
import { formatPrice } from "@/lib/market";
import { useMediaQuery } from "@/lib/theme";

const RECENT_KEY = "zoop:recent-companies";
function recentCompanies(): string[] {
  try {
    const ids: unknown = JSON.parse(sessionStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(ids) ? ids.filter((id): id is string => typeof id === "string").slice(0, 8) : [];
  } catch { return []; }
}

export function CompanySwitcher({ companyId, company, connectedIds, asOf, onSwitch }: {
  companyId: string; company?: Schemas["CompanyDetail"]; connectedIds: string[]; asOf: string; onSwitch: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const desktop = useMediaQuery("(min-width: 1024px)");
  const session = useSession();
  const member = session.data?.kind === "member";
  const portfolio = usePortfolio(member);
  const settings = useSettings(member);
  const [recent] = useState(recentCompanies);
  useEffect(() => {
    if (!company) return;
    sessionStorage.setItem(RECENT_KEY, JSON.stringify([companyId, ...recent.filter(id => id !== companyId)].slice(0, 8)));
  }, [company, companyId, recent]);
  const choose = (id: string) => { setOpen(false); if (id !== companyId) onSwitch(id); };
  const content = (
    <div className="flex flex-col gap-4">
      {company && <div className="flex items-center gap-3 border-b border-border-subtle px-4 pb-4"><CompanyMark id={company.id} name={company.name} brandColor={company.brandColor} logoUrl={company.logoUrl} size={32} /><div className="min-w-0"><p className="font-semibold text-text-primary">{company.name}</p><p className="text-sm text-text-secondary">{[company.ticker, company.sector].filter(Boolean).join(" · ")}</p></div></div>}
      <CompanySearch selectedIds={[companyId]} onToggle={company => choose(company.id)} label="기업 검색" navigation />
      {member && portfolio.isPending && <SkeletonRows count={2} label="보유 기업을 불러오고 있어요" />}
      {member && portfolio.isError && <ErrorState compact title="보유 기업을 불러오지 못했어요" error={portfolio.error} onRetry={() => void portfolio.refetch()} />}
      {member && settings.isError && <ErrorState compact title="관심 기업을 불러오지 못했어요" error={settings.error} onRetry={() => void settings.refetch()} />}
      {member && portfolio.data && <CompanyList title="보유 기업" icon={Wallet} ids={portfolio.data.holdings.map(item => item.companyId)} companyId={companyId} asOf={asOf} onSwitch={choose} />}
      {member && settings.isPending && <SkeletonRows count={2} label="관심 기업을 불러오고 있어요" />}
      {member && settings.data && <CompanyList title="관심 기업" icon={Star} ids={settings.data.watchlistIds} companyId={companyId} asOf={asOf} onSwitch={choose} />}
      <CompanyList title="최근 본 기업" icon={History} ids={[companyId, ...recent.filter(id => id !== companyId)]} companyId={companyId} asOf={asOf} onSwitch={choose} />
      <CompanyList title="연결된 기업" icon={Network} ids={connectedIds.filter(id => id !== companyId)} companyId={companyId} asOf={asOf} onSwitch={choose} />
      {!member && <p className="px-4 text-sm text-text-secondary">로그인하면 보유·관심 기업도 볼 수 있어요.</p>}
    </div>
  );
  if (desktop) return <aside aria-label="기업 전환" className="sticky top-20 max-h-[calc(100dvh-6rem)] overflow-y-auto border-r border-border-subtle py-2 pr-3">{content}</aside>;
  return <><Button variant="secondary" className="w-full" onClick={() => setOpen(true)}><ArrowLeftRight aria-hidden="true" />{company?.name ?? "기업"} · 다른 기업 보기</Button><Sheet open={open} onOpenChange={setOpen} title="기업 전환" closeLabel="기업 전환 닫기">{content}</Sheet></>;
}

function CompanyList({ title, icon, ids, companyId, asOf, onSwitch }: {
  title: string; icon: typeof Building2; ids: string[]; companyId: string; asOf: string; onSwitch: (id: string) => void;
}) {
  const unique = [...new Set(ids)];
  const companies = useCompanies(unique, asOf);
  if (!unique.length) return null;
  return <section><SectionHeader title={title} icon={icon} className="px-4" /><ul aria-label={title}>{companies.map((query, index) => <li key={unique[index]}>{query.isPending ? <SkeletonRows count={1} label="기업 정보를 불러오고 있어요" /> : query.isError ? <ErrorState compact error={query.error} title="기업 정보를 불러오지 못했어요" onRetry={() => void query.refetch()} /> : query.data && <CompanySwitchRow company={query.data} selected={query.data.id === companyId} onSwitch={onSwitch} />}</li>)}</ul></section>;
}
function CompanySwitchRow({ company, selected, onSwitch }: { company: Schemas["CompanyDetail"]; selected: boolean; onSwitch: (id: string) => void }) {
  const quote = useCompanyQuote(company.id);
  const value = quote.data?.status === "available" ? quote.data.quote : null;
  return <ListRow selected={selected} onClick={() => onSwitch(company.id)} leading={<CompanyMark id={company.id} name={company.name} brandColor={company.brandColor} logoUrl={company.logoUrl} />} title={company.name} description={<span className="flex flex-wrap items-center gap-x-2 tabular-nums">{value ? <><span>{formatPrice(value.price, value.currency)}</span><PriceChange changePercent={value.changeRate === null ? null : value.changeRate * 100} className="text-sm" /></> : company.ticker}</span>} />;
}
