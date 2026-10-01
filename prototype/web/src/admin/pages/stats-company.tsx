// 기업별 통계 상세(요구 74): 한 기업의 노드 조회·간선/사건 선택·AI 질문 추이(KST 일별)와 관심 등록·가상 보유 현황.
import { ArrowLeft, BarChart3, Building2, Eye, Link2, Sparkles, Star, Users, Wallet, Zap } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { ApiError } from "@/api/client";
import { useCompanyStats } from "../api";
import { formatCount } from "../format";
import { BarCell, parseWindow, WindowSwitch } from "../insights-ui";
import { AdminPageHeader, AdminSection, DataTable, KstTime, Metric, Td, Th } from "../ui";

export function AdminCompanyStatsPage() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const window = parseWindow(params.get("window"));
  const stats = useCompanyStats(id, window);
  const data = stats.data;
  const back = `/admin/stats?tab=companies${window === "7d" ? "" : `&window=${window}`}`;

  const days = data ? [...data.series].reverse() : [];
  const peak = (pick: (d: (typeof days)[number]) => number) => Math.max(0, ...days.map(pick));

  return (
    <>
      <div>
        <Button variant="ghost" size="sm" asChild>
          <Link to={back}>
            <ArrowLeft aria-hidden="true" />
            종목 순위
          </Link>
        </Button>
      </div>
      <AdminPageHeader
        title={data ? data.name : "기업 통계"}
        icon={Building2}
        actions={<WindowSwitch value={window} onChange={(value) => setParams(value === "7d" ? {} : { window: value }, { replace: true })} />}
      />
      {stats.isPending && <SkeletonRows count={3} label="기업 통계를 불러오고 있어요" />}
      {stats.isError &&
        (stats.error instanceof ApiError && stats.error.status === 404 ? (
          <EmptyState title="이 기업의 통계가 없어요" description="통계에 나타난 적 없는 기업이에요." action={<Link to={back} className="font-medium text-brand-primary hover:underline">종목 순위로 가기</Link>} />
        ) : (
          <ErrorState error={stats.error} title="기업 통계를 불러오지 못했어요" onRetry={() => void stats.refetch()} />
        ))}
      {data && (
        <>
          <p className="text-sm text-text-secondary">
            {data.ticker ? `${data.ticker} · ` : ""}
            {data.inCatalog ? "" : "현재 그래프 목록에 없는 기업 · "}집계 시각 <KstTime value={data.asOf} seconds />
          </p>
          <dl className="grid grid-cols-4 gap-x-6 gap-y-4 border-y border-border-subtle py-4">
            <Metric icon={Eye} label="노드 조회" value={`${formatCount(data.nodeViews)}회`} detail={`조회한 사용자 ${formatCount(data.viewers)}명`} />
            <Metric icon={Link2} label="간선 선택" value={`${formatCount(data.edgeSelections)}회`} detail="이 기업에 이어진 연결선" />
            <Metric icon={Zap} label="사건 선택" value={`${formatCount(data.issueSelections)}회`} detail="이 기업과 연결된 사건 노드" />
            <Metric icon={Sparkles} label="AI 질문" value={`${formatCount(data.aiQuestions)}회`} detail="질문에 이 기업을 연결한 횟수" />
            <Metric icon={Star} label="관심 등록" value={`${formatCount(data.watchlistMembers)}명`} detail="지금 저장된 회원 설정 기준" />
            <Metric icon={Wallet} label="가상 보유" value={`${formatCount(data.holdingMembers)}명`} detail="연결한 가상 계좌 기준" />
          </dl>
          <AdminSection title="일별 추이" icon={BarChart3} id="company-trend">
            <DataTable caption={`${data.name} 일별 추이`}>
              <thead>
                <tr>
                  <Th>날짜(KST)</Th>
                  <Th className="text-right">노드 조회</Th>
                  <Th className="text-right">간선 선택</Th>
                  <Th className="text-right">사건 선택</Th>
                  <Th className="text-right">AI 질문</Th>
                </tr>
              </thead>
              <tbody>
                {days.map((day) => (
                  <tr key={day.date}>
                    <Td className="whitespace-nowrap tabular-nums">{day.date}</Td>
                    <Td className="text-right">
                      <BarCell value={day.nodeViews} max={peak((d) => d.nodeViews)} />
                    </Td>
                    <Td className="text-right">
                      <BarCell value={day.edgeSelections} max={peak((d) => d.edgeSelections)} />
                    </Td>
                    <Td className="text-right">
                      <BarCell value={day.issueSelections} max={peak((d) => d.issueSelections)} />
                    </Td>
                    <Td className="text-right">
                      <BarCell value={day.aiQuestions} max={peak((d) => d.aiQuestions)} />
                    </Td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          </AdminSection>
          <p className="flex items-center gap-2 text-sm text-text-secondary">
            <Users className="size-4 shrink-0" aria-hidden="true" />
            {data.note}
          </p>
        </>
      )}
    </>
  );
}
