// /me/stocks 내 종목 (design-direction §5.8)
//  보유 종목(가상 계좌, 모의 데이터): 계좌 식별·예수금, 종목별 수량·평가 금액·자산 비중(같은 계산 시점 시세, 현금 제외, 계산 불가는 그대로),
//  모의 정보 기준 시점과 평가 계산 시점, 연결/해제
//  관심 종목: 개수 제한 없음. 검색 결과 선택·빼기는 편집 목록에만 반영하고 [저장]이 PUT /api/me/settings(FS011-01·FS027).
//    version 409·422는 사람말로, 실패해도 편집 내용은 남는다.
//  각 종목 행 → 그 종목을 고른 지도, [상세] → 기업 상세. 비회원은 로그인 안내.
import { ArrowUpRight, Landmark, Star, Wallet, X } from "lucide-react";
import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { ApiError, type Schemas } from "@/api/client";
import {
  useCompanies,
  useConnectPortfolio,
  useDisconnectPortfolio,
  useLogout,
  useMockPortfolios,
  usePortfolio,
  useSession,
  useSettings,
  useUpdateSettings,
} from "@/api/queries";
import { CompanyMark } from "@/components/domain/company-mark";
import { CompanySearch } from "@/components/domain/company-search";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { ListRow } from "@/components/ui/list-row";
import { SectionHeader } from "@/components/ui/section-header";
import { useToast } from "@/components/ui/toast";
import { Tooltip } from "@/components/ui/tooltip";
import { holdingWeightText } from "@/lib/holding";
import { errorReasonMessage, formatKst } from "@/lib/labels";
import { formatPrice } from "@/lib/market";

export function MyStocksPage() {
  const session = useSession();
  const isMember = session.data?.kind === "member";
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col pb-8">
      <h1 className="px-4 pt-6 text-2xl font-bold text-text-primary">내 종목</h1>
      {isMember ? (
        <>
          <Holdings />
          <Watchlist />
        </>
      ) : (
        <GuestPrompt />
      )}
    </div>
  );
}

/** 비회원: 탭을 숨기지 않고, 들어오면 로그인 안내를 보여준다. */
function GuestPrompt() {
  const logout = useLogout();
  const navigate = useNavigate();
  return (
    <EmptyState
      className="px-4"
      title="로그인하면 내 종목을 관리할 수 있어요"
      description="관심 종목을 고르거나 가상 계좌를 연결해 내 종목 주변 사건을 모아 봐요."
      action={
        <Button loading={logout.isPending} onClick={() => logout.mutate(undefined, { onSettled: () => navigate("/login") })}>
          로그인하기
        </Button>
      }
    />
  );
}

interface StockRowProps {
  id: string;
  mode: "assets" | "watchlist";
  title: string;
  description?: React.ReactNode;
  brandColor?: string | null;
  logoUrl?: string | null;
  /** 행 밖 오른쪽 끝 행동(예: 관심 종목에서 빼기) */
  action?: React.ReactNode;
}

/** 종목 행: 누르면 그 종목을 고른 지도, 오른쪽 [상세] 아이콘은 기업 상세(돌아오면 이 화면). */
function StockRow({ id, mode, title, description, brandColor, logoUrl, action }: StockRowProps) {
  const location = useLocation();
  return (
    <li className="flex items-center gap-1 pr-2">
      <ListRow
        className="min-w-0 flex-1"
        to={`/?mode=${mode}&select=${encodeURIComponent(`node:${id}`)}`}
        leading={<CompanyMark id={id} name={title} brandColor={brandColor} logoUrl={logoUrl} />}
        title={title}
        description={description}
        aria-label={`${title}, 지도에서 보기`}
      />
      <Tooltip content="기업 상세">
        <Button variant="ghost" size="icon" asChild>
          <Link to={`/companies/${encodeURIComponent(id)}`} state={{ from: location.pathname }} aria-label={`${title} 기업 상세`}>
            <ArrowUpRight aria-hidden="true" />
          </Link>
        </Button>
      </Tooltip>
      {action}
    </li>
  );
}

function Holdings() {
  const portfolio = usePortfolio();
  const options = useMockPortfolios();
  const connect = useConnectPortfolio();
  const disconnect = useDisconnectPortfolio();
  const toast = useToast();
  const account = options.data?.items[0];
  const connection = portfolio.data?.connection;

  const onConnect = () => {
    if (!account) return;
    connect.mutate(account.id, {
      onSuccess: () => toast({ title: "가상 계좌를 연결했어요", tone: "success" }),
      onError: (error) => {
        if (error instanceof ApiError && error.code === "already_connected") void portfolio.refetch();
      },
    });
  };
  const onDisconnect = () => {
    if (!connection) return;
    disconnect.mutate(connection.id, { onSuccess: () => toast({ title: "가상 계좌 연결을 끊었어요", tone: "success" }) });
  };

  const action = connection ? (
    <Button variant="ghost" size="sm" loading={disconnect.isPending} onClick={onDisconnect}>
      연결 끊기
    </Button>
  ) : undefined;

  return (
    <section aria-labelledby="stocks-holdings">
      <SectionHeader id="stocks-holdings" icon={Wallet} title="보유 종목(가상 계좌)" action={action} />
      {portfolio.isPending && <SkeletonRows count={2} label="보유 종목을 불러오고 있어요" />}
      {portfolio.isError && (
        <ErrorState className="px-4" error={portfolio.error} title="보유 종목을 불러오지 못했어요" onRetry={() => void portfolio.refetch()} compact />
      )}
      {disconnect.isError && <ErrorState className="px-4" error={disconnect.error} title="연결을 끊지 못했어요" compact />}
      {portfolio.data?.connected && portfolio.data.connection && portfolio.data.valuation && (
        <div className="flex flex-col gap-0.5 px-4 pb-2 text-sm text-text-secondary tabular-nums">
          <p>
            모의 계좌 {portfolio.data.connection.accountId ?? "식별 정보 미제공"} · 예수금{" "}
            {portfolio.data.connection.cash ? formatPrice(portfolio.data.connection.cash.amount, portfolio.data.connection.cash.currency) : "미제공"}
          </p>
          <p>
            모의 정보 기준 {formatKst(portfolio.data.mockAsOf)} · 평가 계산 {formatKst(portfolio.data.valuation.calculatedAt)}
          </p>
          {portfolio.data.holdings.length > 0 && portfolio.data.valuation.weightUnavailableReason && <p>{portfolio.data.valuation.weightUnavailableReason}</p>}
        </div>
      )}
      {portfolio.data?.connected &&
        (portfolio.data.holdings.length === 0 ? (
          <p className="px-4 py-3 text-base text-text-secondary">이 계좌에는 보유 종목이 없어요.</p>
        ) : (
          <ul>
            {portfolio.data.holdings.map((h) => (
              <StockRow
                key={h.companyId}
                id={h.companyId}
                mode="assets"
                title={h.name}
                description={
                  <span className="tabular-nums">
                    {h.quantity.toLocaleString("ko-KR")}주 · 평가{" "}
                    {h.quote.status === "available" && h.marketValue !== null ? formatPrice(h.marketValue, h.quote.currency) : "미제공"} ·{" "}
                    {holdingWeightText(h)}
                  </span>
                }
              />
            ))}
          </ul>
        ))}
      {portfolio.data && !portfolio.data.connected && (
        <div className="flex flex-col">
          <p className="px-4 pb-1 text-base text-text-secondary">연결된 가상 계좌가 없어요.</p>
          {options.isError && (
            <ErrorState className="px-4" error={options.error} title="가상 계좌를 불러오지 못했어요" onRetry={() => void options.refetch()} compact />
          )}
          {account && (
            <div className="flex items-center pr-4">
              <ListRow
                className="flex-1"
                divider="none"
                leading={<Landmark />}
                title={account.label}
                description={<span className="tabular-nums">모의 계좌 {account.accountId} · 보유 종목 {account.holdingsCount}개</span>}
              />
              <Button variant="secondary" size="sm" loading={connect.isPending} onClick={onConnect}>
                연결하기
              </Button>
            </div>
          )}
          {connect.isError && !(connect.error instanceof ApiError && connect.error.code === "already_connected") && (
            <ErrorState className="px-4" error={connect.error} title="계좌를 연결하지 못했어요" compact />
          )}
        </div>
      )}
    </section>
  );
}

/** 관심 종목(FS011-01·FS027): 검색 결과 선택과 빼기는 편집 중인 목록에만 반영하고, [저장]이 실제 저장이다.
 *  저장이 성공하기 전에는 성공을 알리지 않으며, 실패하면 편집 내용을 그대로 두고 다시 저장할 수 있다. */
function Watchlist() {
  const settings = useSettings();
  const update = useUpdateSettings();
  const toast = useToast();
  const savedIds = settings.data?.watchlistIds ?? [];
  const [draft, setDraft] = useState<string[] | null>(null);
  const editIds = draft ?? savedIds;
  const added = editIds.filter((id) => !savedIds.includes(id));
  const removed = savedIds.filter((id) => !editIds.includes(id));
  const dirty = added.length + removed.length > 0;
  const watchQueries = useCompanies(editIds);

  const edit = (next: string[]) => {
    setDraft(next);
    update.reset();
  };
  const remove = (id: string) => edit(editIds.filter((x) => x !== id));
  const onToggle = (company: Schemas["CompanySummary"]) =>
    edit(editIds.includes(company.id) ? editIds.filter((x) => x !== company.id) : [...editIds, company.id]);

  const save = () => {
    if (!settings.data || !dirty) return;
    update.mutate(
      { version: settings.data.version, watchlistIds: editIds },
      {
        onSuccess: () => {
          setDraft(null);
          toast({ title: "관심 종목을 저장했어요", description: `${editIds.length}개`, tone: "success" });
        },
        onError: (error) => {
          if (error instanceof ApiError && error.code === "version_conflict") void settings.refetch();
        },
      },
    );
  };

  const conflict = update.error instanceof ApiError && update.error.code === "version_conflict";
  const updateMessage = conflict
    ? "다른 곳에서 관심 종목이 바뀌었어요. 최신 목록을 불러왔으니 편집한 내용으로 다시 저장할 수 있어요."
    : update.error instanceof ApiError
      ? errorReasonMessage(update.error.code)
      : undefined;

  return (
    <section aria-labelledby="stocks-watch">
      <SectionHeader
        id="stocks-watch"
        icon={Star}
        title="관심 종목"
        action={
          <data value={editIds.length} className="text-sm text-text-secondary tabular-nums" aria-label={`관심 종목 ${editIds.length}개${dirty ? ", 저장 전" : ""}`}>
            {editIds.length}개{dirty && " · 저장 전"}
          </data>
        }
      />
      {settings.isPending && <SkeletonRows count={2} label="관심 종목을 불러오고 있어요" />}
      {settings.isError && (
        <ErrorState className="px-4" error={settings.error} title="관심 종목을 불러오지 못했어요" onRetry={() => void settings.refetch()} compact />
      )}
      {settings.isSuccess &&
        (editIds.length === 0 ? (
          <p className="px-4 pb-3 text-base text-text-secondary">고른 관심 종목이 없어요. 아래에서 검색해 추가해 주세요.</p>
        ) : (
          <ul>
            {editIds.map((id, i) => {
              const q = watchQueries[i];
              const name = q?.data?.name ?? "종목";
              const pending = added.includes(id);
              const removeButton = (
                <Button variant="ghost" size="icon" aria-label={`${name} 관심 종목 목록에서 빼기`} disabled={update.isPending} onClick={() => remove(id)}>
                  <X aria-hidden="true" />
                </Button>
              );
              if (q?.data) {
                return (
                  <StockRow
                    key={id}
                    id={id}
                    mode="watchlist"
                    title={q.data.name}
                    description={[q.data.ticker, pending && "추가 · 저장 전"].filter(Boolean).join(" · ") || undefined}
                    brandColor={q.data.brandColor}
                    logoUrl={q.data.logoUrl}
                    action={removeButton}
                  />
                );
              }
              return (
                <li key={id} className="flex items-center pr-2">
                  {q?.isError ? (
                    <p className="flex-1 px-4 py-3 text-base text-text-secondary">종목 정보를 불러오지 못했어요.</p>
                  ) : (
                    <div className="flex-1">
                      <SkeletonRows count={1} label="관심 종목을 불러오고 있어요" />
                    </div>
                  )}
                  {removeButton}
                </li>
              );
            })}
          </ul>
        ))}
      {dirty && (
        <div className="flex flex-wrap items-center gap-2 px-4 py-3">
          <p className="mr-auto text-sm text-text-secondary tabular-nums" aria-live="polite">
            저장하지 않은 변경 {added.length > 0 && `추가 ${added.length}개`}
            {added.length > 0 && removed.length > 0 && " · "}
            {removed.length > 0 && `빼기 ${removed.length}개`}
          </p>
          <Button variant="ghost" disabled={update.isPending} onClick={() => edit(savedIds)}>
            되돌리기
          </Button>
          <Button loading={update.isPending} disabled={!settings.data} onClick={save}>
            {update.isError ? "다시 저장" : "저장"}
          </Button>
        </div>
      )}
      {update.isError && (
        <p role="alert" className="px-4 pb-2 text-sm font-medium text-error">
          {updateMessage ?? "관심 종목을 저장하지 못했어요. 편집한 내용은 그대로 있어요. 다시 저장해 주세요."}
        </p>
      )}
      {settings.isSuccess && (
        <div className="pt-4">
          <CompanySearch label="관심 종목 추가" selectedIds={editIds} onToggle={onToggle} disabled={update.isPending} />
        </div>
      )}
    </section>
  );
}
