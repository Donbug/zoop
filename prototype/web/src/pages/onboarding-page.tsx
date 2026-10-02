// UI-02 초기 설정(요구 8–14, design-direction §5.2)
//  1) 투자 여부(저장): 투자 중 → 가상 계좌 연결, 아니면 → 관심 종목 고르기
//  2) 가상 계좌(요구 9 보류 중이지만 모의 프로필 연결은 유지): 모의 데이터임을 밝히고, 연결하면 보유 종목을 보여 준다.
//     건너뛰기 → 관심 종목. 실패하면 다시 시도하거나 관심 종목으로 넘어간다.
//  3) 관심 종목: 개수 제한 없음. 검색(이름·티커)과 추천(승인된 사건이 많은 기업, 근거 문구 포함). 0개여도 지도로 간다.
//  저장에 실패하면 완료로 처리하지 않고 고른 내용을 그대로 둔 채 다시 시도한다(요구 13).
//  설정이 끝나면 메인 지도로 가고, 튜토리얼은 메인 지도 위에서 진행한다(features/graph-tutorial.tsx).
import { ArrowLeft, Briefcase, FlaskConical, Landmark, Lightbulb, Sprout, Star, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { ApiError, type Schemas } from "@/api/client";
import { useConnectPortfolio, useMockPortfolios, usePortfolio, useRecommendations, useSettings, useUpdateSettings } from "@/api/queries";
import { CompanyMark } from "@/components/domain/company-mark";
import { CompanySearch } from "@/components/domain/company-search";
import { Button } from "@/components/ui/button";
import { ErrorState, SkeletonLines, SkeletonRows } from "@/components/ui/feedback";
import { ListRow } from "@/components/ui/list-row";
import { SectionHeader } from "@/components/ui/section-header";
import { holdingWeightText } from "@/lib/holding";
import { cn } from "@/lib/utils";

type Step = "investor" | "account" | "watchlist";
type PickedCompany = Pick<Schemas["CompanySummary"], "id" | "name" | "brandColor" | "logoUrl">;

export function OnboardingPage() {
  const settings = useSettings();
  const [step, setStep] = useState<Step | null>(null);

  if (settings.isError) {
    return (
      <div className="mx-auto w-full max-w-xl px-4 py-6">
        <ErrorState error={settings.error} title="설정을 불러오지 못했어요" onRetry={() => void settings.refetch()} />
      </div>
    );
  }
  if (!settings.data) {
    return (
      <div className="mx-auto w-full max-w-xl py-6">
        <SkeletonRows count={3} label="설정을 불러오고 있어요" />
      </div>
    );
  }
  // 새로 고침해도 저장된 투자 여부에서 이어 간다.
  const current: Step = step ?? (settings.data.investor === null ? "investor" : settings.data.investor ? "account" : "watchlist");
  if (current === "investor") return <InvestorStep settings={settings.data} onNext={(investor) => setStep(investor ? "account" : "watchlist")} />;
  if (current === "account") return <AccountStep settings={settings.data} onBack={() => setStep("investor")} onWatchlist={() => setStep("watchlist")} />;
  return <WatchlistStep settings={settings.data} onBack={() => setStep(settings.data.investor ? "account" : "investor")} />;
}

/** 설정 저장. 버전 충돌(409)이면 최신 설정을 다시 받아 두고, 사용자가 한 번 더 누르면 되게 한다. */
function useSaveSettings(settings: Schemas["SettingsResponse"]) {
  const update = useUpdateSettings();
  const refetch = useSettings(false).refetch;
  const save = (body: Omit<Schemas["SettingsUpdate"], "version">, onSuccess: () => void) =>
    update.mutate(
      { version: settings.version, ...body },
      {
        onSuccess,
        onError: (error) => {
          if (error instanceof ApiError && error.code === "version_conflict") void refetch();
        },
      },
    );
  return { save, update };
}

function StepLayout({ title, onBack, children, footer }: { title: string; onBack?: () => void; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="mx-auto flex w-full max-w-xl flex-1 flex-col">
      <div className="flex flex-col gap-2 px-4 pt-6 pb-2">
        {onBack && (
          <Button variant="link" className="self-start" onClick={onBack}>
            <ArrowLeft aria-hidden="true" />
            이전 단계
          </Button>
        )}
        <h1 className="text-2xl font-bold text-text-primary">{title}</h1>
      </div>
      {children}
      {footer && (
        <div className="sticky bottom-0 mt-auto flex flex-col gap-2 border-t border-border-subtle bg-surface-base px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          {footer}
        </div>
      )}
    </div>
  );
}

// ---- 1) 투자 여부

function InvestorStep({ settings, onNext }: { settings: Schemas["SettingsResponse"]; onNext: (investor: boolean) => void }) {
  const { save, update } = useSaveSettings(settings);
  const [chosen, setChosen] = useState<boolean | null>(settings.investor);
  const choose = (investor: boolean) => {
    setChosen(investor);
    save({ investor }, () => onNext(investor));
  };
  const options = [
    { value: true, icon: Briefcase, title: "지금 주식에 투자하고 있어요", description: "가상 계좌를 연결해 보유 종목 주변을 봐요" },
    { value: false, icon: Sprout, title: "아직 투자하지 않아요", description: "관심 있는 종목을 골라 시작해요" },
  ];
  return (
    <StepLayout title="지금 주식에 투자하고 계신가요?">
      <ul className="flex flex-col gap-3 px-4 pt-4" aria-label="투자 여부">
        {options.map((o) => (
          <li key={String(o.value)}>
            <button
              type="button"
              aria-pressed={chosen === o.value}
              disabled={update.isPending}
              onClick={() => choose(o.value)}
              className={cn(
                "pressable flex min-h-20 w-full items-center gap-4 rounded-md border px-4 py-4 text-left transition-token disabled:cursor-progress",
                chosen === o.value ? "border-brand-primary bg-surface-selected" : "border-border-strong bg-surface-raised hover:bg-surface-sunken",
              )}
            >
              <o.icon className="size-6 shrink-0 text-brand-primary" aria-hidden="true" />
              <span className="flex flex-col gap-0.5">
                <span className="text-md font-semibold text-text-primary">{o.title}</span>
                <span className="text-sm text-text-secondary">{o.description}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      <div className="px-4 pt-3">
        {update.isPending && <p role="status" className="text-sm text-text-secondary">선택을 저장하고 있어요</p>}
        {update.isError && chosen !== null && (
          <ErrorState error={update.error} title="선택을 저장하지 못했어요" onRetry={() => choose(chosen)} compact />
        )}
      </div>
    </StepLayout>
  );
}

// ---- 2) 가상 계좌

function AccountStep({ settings, onBack, onWatchlist }: { settings: Schemas["SettingsResponse"]; onBack: () => void; onWatchlist: () => void }) {
  const navigate = useNavigate();
  const portfolios = useMockPortfolios();
  const portfolio = usePortfolio();
  const connect = useConnectPortfolio();
  const { save, update } = useSaveSettings(settings);
  const [chosenId, setChosenId] = useState<string | null>(null);
  const connected = portfolio.data?.connected ? portfolio.data : null;
  const selectedId = chosenId ?? portfolios.data?.items[0]?.id ?? null;

  const finish = () => save({ mode: "assets", completed: true }, () => navigate("/", { replace: true }));
  const tryConnect = () => selectedId && connect.mutate(selectedId);

  const footer = connected ? (
    <>
      {update.isError && <ErrorState error={update.error} title="설정을 저장하지 못했어요" onRetry={finish} compact />}
      <Button size="lg" className="w-full" loading={update.isPending} onClick={finish}>
        이 계좌로 지도 보기
      </Button>
      <Button variant="secondary" size="lg" className="w-full" disabled={update.isPending} onClick={onWatchlist}>
        관심 종목도 고르기
      </Button>
    </>
  ) : (
    <>
      {connect.isError && (
        <div role="alert" className="flex flex-col gap-2">
          <ErrorState error={connect.error} title="계좌를 연결하지 못했어요" compact />
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" loading={connect.isPending} onClick={tryConnect}>
              다시 시도
            </Button>
            <Button variant="ghost" onClick={onWatchlist}>
              관심 종목 고르기로 넘어가기
            </Button>
          </div>
        </div>
      )}
      {!connect.isError && (
        <Button size="lg" className="w-full" loading={connect.isPending} disabled={!selectedId} onClick={tryConnect}>
          선택한 가상 계좌 연결하기
        </Button>
      )}
      <Button variant="ghost" size="lg" className="w-full" disabled={connect.isPending} onClick={onWatchlist}>
        건너뛰고 관심 종목 고르기
      </Button>
    </>
  );

  return (
    <StepLayout title={connected ? "가상 계좌를 연결했어요" : "가상 계좌를 연결해요"} onBack={connected ? undefined : onBack} footer={footer}>
      <p className="mx-4 mt-2 flex items-start gap-2 rounded-sm bg-surface-sunken px-3 py-2 text-base text-text-primary">
        <FlaskConical className="mt-0.5 size-5 shrink-0 text-warning" aria-hidden="true" />
        실제 증권 계좌가 아니에요. 준비된 모의 데이터로 만든 가상 계좌예요.
      </p>

      {connected ? (
        <section aria-labelledby="onboarding-holdings">
          <SectionHeader id="onboarding-holdings" icon={Landmark} title={`${connected.connection?.label ?? "가상 계좌"} 보유 종목`} />
          <ul>
            {connected.holdings.map((h) => (
              <li key={h.companyId}>
                <ListRow
                  leading={<CompanyMark id={h.companyId} name={h.name} />}
                  title={h.name}
                  description={
                    <span className="tabular-nums">
                      {h.quantity.toLocaleString("ko-KR")}주 · {holdingWeightText(h)}
                    </span>
                  }
                />
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <section aria-labelledby="onboarding-account">
          <SectionHeader id="onboarding-account" icon={Landmark} title="연결할 가상 계좌" />
          {(portfolios.isPending || portfolio.isPending) && (
            <div className="px-4">
              <SkeletonLines lines={2} label="가상 계좌를 불러오고 있어요" />
            </div>
          )}
          {portfolios.isError && (
            <ErrorState className="px-4" error={portfolios.error} title="가상 계좌를 불러오지 못했어요" onRetry={() => void portfolios.refetch()} compact />
          )}
          {portfolios.data && portfolios.data.items.length === 0 && (
            <p className="px-4 py-3 text-base text-text-secondary">지금은 연결할 수 있는 가상 계좌가 없어요. 관심 종목을 골라 시작해 주세요.</p>
          )}
          {portfolios.data && portfolios.data.items.length > 0 && (
            <ul aria-label="가상 계좌 목록">
              {portfolios.data.items.map((p) => (
                <li key={p.id}>
                  <ListRow
                    onClick={() => setChosenId(p.id)}
                    selected={selectedId === p.id}
                    disabled={connect.isPending}
                    leading={<Landmark />}
                    title={p.label}
                    description={<span className="tabular-nums">보유 종목 {p.holdingsCount}개</span>}
                  />
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </StepLayout>
  );
}

// ---- 3) 관심 종목

function WatchlistStep({ settings, onBack }: { settings: Schemas["SettingsResponse"]; onBack: () => void }) {
  const navigate = useNavigate();
  const { save, update } = useSaveSettings(settings);
  const recommendations = useRecommendations();
  const portfolio = usePortfolio();
  const [picked, setPicked] = useState<PickedCompany[]>([]);
  const pickedIds = picked.map((p) => p.id);

  const toggle = (company: Schemas["CompanySummary"]) =>
    setPicked((prev) =>
      prev.some((p) => p.id === company.id)
        ? prev.filter((p) => p.id !== company.id)
        : [...prev, { id: company.id, name: company.name, brandColor: company.brandColor, logoUrl: company.logoUrl }],
    );

  const submit = () =>
    save(
      { mode: picked.length === 0 && portfolio.data?.connected ? "assets" : "watchlist", watchlistIds: pickedIds, completed: true },
      () => navigate("/", { replace: true }),
    );

  const footer = (
    <>
      {update.isError && <ErrorState error={update.error} title="관심 종목을 저장하지 못했어요. 고른 종목은 그대로 있어요" onRetry={submit} compact />}
      <Button size="lg" className="w-full" loading={update.isPending} onClick={submit}>
        {picked.length > 0 ? `${picked.length}개 종목으로 시작하기` : "고르지 않고 지도 보기"}
      </Button>
    </>
  );

  return (
    <StepLayout title="관심 있는 종목을 골라 주세요" onBack={onBack} footer={footer}>
      <section aria-labelledby="onboarding-picked">
        <SectionHeader
          id="onboarding-picked"
          icon={Star}
          title="고른 종목"
          action={
            <data value={picked.length} className="text-sm text-text-secondary tabular-nums">
              {picked.length}개
            </data>
          }
        />
        {picked.length === 0 ? (
          <p className="px-4 pb-3 text-base text-text-secondary">고르지 않아도 시장 전체 지도로 시작할 수 있어요.</p>
        ) : (
          <ul>
            {picked.map((p) => (
              <li key={p.id} className="flex items-center pr-2">
                <ListRow className="flex-1" leading={<CompanyMark id={p.id} name={p.name} brandColor={p.brandColor} logoUrl={p.logoUrl} />} title={p.name} />
                <Button variant="ghost" size="icon" aria-label={`${p.name} 빼기`} onClick={() => setPicked((prev) => prev.filter((x) => x.id !== p.id))}>
                  <X aria-hidden="true" />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="onboarding-recommended">
        <SectionHeader id="onboarding-recommended" icon={Lightbulb} title="승인된 사건이 많은 기업" />
        {recommendations.isPending && <SkeletonRows count={2} label="추천 종목을 불러오고 있어요" />}
        {recommendations.isError && (
          <ErrorState className="px-4" error={recommendations.error} title="추천 종목을 불러오지 못했어요" onRetry={() => void recommendations.refetch()} compact />
        )}
        {recommendations.data && recommendations.data.items.length === 0 && (
          <p className="px-4 py-3 text-base text-text-secondary">추천할 만큼 사건이 쌓인 기업이 아직 없어요. 아래에서 검색해 주세요.</p>
        )}
        {recommendations.data && recommendations.data.items.length > 0 && (
          <ul aria-label="추천 종목">
            {recommendations.data.items.map(({ company, reason }) => (
              <li key={company.id}>
                <ListRow
                  onClick={() => toggle(company)}
                  disabled={update.isPending}
                  selected={pickedIds.includes(company.id)}
                  leading={<CompanyMark id={company.id} name={company.name} brandColor={company.brandColor} logoUrl={company.logoUrl} />}
                  title={company.name}
                  description={<span className="tabular-nums">{company.ticker ? `${company.ticker} · ` : ""}{reason}</span>}
                  trailing={pickedIds.includes(company.id) ? <span className="font-medium text-brand-primary">선택됨</span> : <span>추가</span>}
                />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="종목 검색" className="pt-6 pb-6">
        <CompanySearch selectedIds={pickedIds} onToggle={toggle} disabled={update.isPending} />
      </section>
    </StepLayout>
  );
}
