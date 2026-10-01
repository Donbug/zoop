// 기업 상세의 가상 보유 영역(요구 36). 가상 계좌를 연결한 회원이 이 기업을 보유할 때만 그린다.
// 비회원·미연결·미보유·관심 종목만인 경우는 영역 자체를 그리지 않는다(0주로 바꾸지 않는다).
// 평가 금액은 시세가 없어 그리지 않고 이유를 정보 아이콘에 둔다. 비중은 매입 원가 기준이다.
// 계좌 조회가 실패하면 이 영역만 오류와 [다시 시도]를 보인다(요구 54). 로그아웃하면 세션이 바뀌어 곧바로 사라진다.
import { Info, Wallet } from "lucide-react";
import { usePortfolio, useSession } from "@/api/queries";
import { ErrorState } from "@/components/ui/feedback";
import { IconHint } from "@/components/ui/icon-hint";

const numberFormat = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 });

export function CompanyHolding({ companyId }: { companyId: string }) {
  const session = useSession();
  const isMember = session.data?.kind === "member";
  const portfolio = usePortfolio(isMember);

  if (!isMember) return null;
  if (portfolio.isError)
    return <ErrorState compact error={portfolio.error} title="가상 계좌 보유 정보를 불러오지 못했어요" onRetry={() => void portfolio.refetch()} />;
  const holding = portfolio.data?.connected ? portfolio.data.holdings.find((h) => h.companyId === companyId) : undefined;
  if (!holding) return null;

  const stats = [
    { label: "보유 수량", value: `${numberFormat.format(holding.quantity)}주` },
    { label: "평균 매입가", value: numberFormat.format(holding.avgPrice) },
    { label: "원가 비중", value: `${Math.round(holding.weight * 100)}%` },
  ];

  return (
    <section aria-labelledby="company-holding-title" className="flex flex-col gap-2 border-y border-border-subtle py-3">
      <div className="flex items-center gap-2">
        <h2 id="company-holding-title" className="flex items-center gap-2 text-base font-semibold text-text-primary">
          <Wallet className="size-5 text-text-secondary" aria-hidden="true" />
          가상 계좌 보유
        </h2>
        <IconHint icon={Info} label="모의 보유 정보">
          <p>연결한 가상 계좌의 모의 데이터예요.</p>
          <p>시세가 없어 평가 금액은 보여 드리지 않아요. 비중은 매입 원가로 계산했어요.</p>
        </IconHint>
      </div>
      <dl className="grid grid-cols-3 gap-x-3">
        {stats.map((s) => (
          <div key={s.label} className="flex min-w-0 flex-col gap-0.5">
            <dt className="text-sm text-text-secondary">{s.label}</dt>
            <dd className="text-lg font-semibold text-text-primary tabular-nums">{s.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
