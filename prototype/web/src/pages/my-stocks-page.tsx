// /me/stocks 내 종목 (design-direction §5.8)
//  보유 종목(가상 계좌): 연결 상태, 종목별 수량·원가 비중, 연결/해제(평가금액은 데이터가 없어 자리를 두지 않는다)
//  관심 종목: 개수 제한 없음, 검색·추가·빼기(PUT /api/me/settings, version 409·422는 사람말로)
//  각 종목 행 → 그 종목을 고른 지도, [상세] → 기업 상세. 비회원은 로그인 안내.
import { ArrowUpRight, Landmark, Star, Wallet, X } from "lucide-react";
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
import { errorReasonMessage } from "@/lib/labels";

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
                    {h.quantity.toLocaleString("ko-KR")}주 · 원가 비중 {Math.round(h.weight * 100)}%
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
                description={<span className="tabular-nums">보유 종목 {account.holdingsCount}개</span>}
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

function Watchlist() {
  const settings = useSettings();
  const update = useUpdateSettings();
  const toast = useToast();
  const watchIds = settings.data?.watchlistIds ?? [];
  const watchQueries = useCompanies(watchIds);

  const saveList = (next: string[], done: string, name: string) => {
    if (!settings.data) return;
    update.mutate(
      { version: settings.data.version, watchlistIds: next },
      {
        onSuccess: () => toast({ title: done, description: name, tone: "success" }),
        onError: (error) => {
          if (error instanceof ApiError && error.code === "version_conflict") void settings.refetch();
        },
      },
    );
  };
  const remove = (id: string, name: string) => saveList(watchIds.filter((x) => x !== id), "관심 종목에서 뺐어요", name);

  const onToggle = (company: Schemas["CompanySummary"]) => {
    if (watchIds.includes(company.id)) {
      remove(company.id, company.name);
      return;
    }
    saveList([...watchIds, company.id], "관심 종목에 추가했어요", company.name);
  };

  const updateMessage = update.error instanceof ApiError ? errorReasonMessage(update.error.code) : undefined;

  return (
    <section aria-labelledby="stocks-watch">
      <SectionHeader
        id="stocks-watch"
        icon={Star}
        title="관심 종목"
        action={
          <data value={watchIds.length} className="text-sm text-text-secondary tabular-nums" aria-label={`관심 종목 ${watchIds.length}개`}>
            {watchIds.length}개
          </data>
        }
      />
      {settings.isPending && <SkeletonRows count={2} label="관심 종목을 불러오고 있어요" />}
      {settings.isError && (
        <ErrorState className="px-4" error={settings.error} title="관심 종목을 불러오지 못했어요" onRetry={() => void settings.refetch()} compact />
      )}
      {settings.isSuccess &&
        (watchIds.length === 0 ? (
          <p className="px-4 pb-3 text-base text-text-secondary">고른 관심 종목이 없어요. 아래에서 검색해 추가해 주세요.</p>
        ) : (
          <ul>
            {watchIds.map((id, i) => {
              const q = watchQueries[i];
              const name = q?.data?.name ?? "종목";
              const removeButton = (
                <Button variant="ghost" size="icon" aria-label={`${name} 관심 종목에서 빼기`} disabled={update.isPending} onClick={() => remove(id, name)}>
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
                    description={q.data.ticker ?? undefined}
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
      {update.isError && (
        <p role="alert" className="px-4 py-2 text-sm font-medium text-error">
          {updateMessage ?? "관심 종목을 저장하지 못했어요. 잠시 후 다시 시도해 주세요."}
        </p>
      )}
      {settings.isSuccess && (
        <div className="pt-4">
          <CompanySearch label="관심 종목 추가" selectedIds={watchIds} onToggle={onToggle} showWhenEmpty={false} disabled={update.isPending} />
        </div>
      )}
    </section>
  );
}
