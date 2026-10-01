// 이용 통계(요구 74): 요약 지표(산식·정의를 표에 적음) · 일별 추이 · 브리핑 회차별 조회 · 종목 순위.
// 표본이 작으면(분모 < minSample) 비율을 숨기고 건수만 보여 준다. 개인을 알 수 있는 값은 없다. 기간은 KST 달력일.
import { BarChart3, ChartColumn, ListOrdered, Newspaper, Sparkles, Users } from "lucide-react";
import { Link, useSearchParams } from "react-router";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCompanyRanking, useStatsSummary, type StatsMetric, type StatsWindow } from "../api";
import { formatCount } from "../format";
import { BarCell, MetricBasis, MetricValue, parseWindow, WindowSwitch } from "../insights-ui";
import { editionLabel } from "../labels";
import { AdminPageHeader, AdminSection, DataTable, KstTime, Td, Th } from "../ui";

function MetricTable({ caption, metrics, minSample }: { caption: string; metrics: StatsMetric[]; minSample: number }) {
  return (
    <DataTable caption={caption}>
      <thead>
        <tr>
          <Th>지표</Th>
          <Th className="text-right">값</Th>
          <Th className="text-right">산식</Th>
          <Th>정의</Th>
        </tr>
      </thead>
      <tbody>
        {metrics.map((metric) => (
          <tr key={metric.key}>
            <Td className="font-medium whitespace-nowrap">{metric.label}</Td>
            <Td className="text-right">
              <MetricValue metric={metric} />
            </Td>
            <Td className="text-right text-text-secondary">
              <MetricBasis metric={metric} minSample={minSample} />
            </Td>
            <Td className="max-w-md text-sm text-text-secondary">{metric.definition}</Td>
          </tr>
        ))}
      </tbody>
    </DataTable>
  );
}

function SummaryPanel({ window }: { window: StatsWindow }) {
  const summary = useStatsSummary(window);
  if (summary.isPending) return <SkeletonRows count={4} label="이용 통계를 불러오고 있어요" />;
  if (summary.isError) return <ErrorState error={summary.error} title="이용 통계를 불러오지 못했어요" onRetry={() => void summary.refetch()} />;
  const data = summary.data;

  const byGroup = (group: StatsMetric["group"]) => data.metrics.filter((m) => m.group === group);
  const trend = [...data.trend].reverse();
  const peak = (pick: (d: (typeof trend)[number]) => number) => Math.max(0, ...trend.map(pick));
  const peaks = {
    activeUsers: peak((d) => d.activeUsers),
    nodeSelections: peak((d) => d.nodeSelections),
    edgeSelections: peak((d) => d.edgeSelections),
    briefingViews: peak((d) => d.briefingViews),
    aiQuestions: peak((d) => d.aiQuestions),
  };

  return (
    <>
      <p className="text-sm text-text-secondary">
        집계 시각 <KstTime value={data.asOf} seconds /> · 비율은 분모가 {data.minSample} 미만이면 숨기고 건수만 보여 줘요 · 온보딩은 {data.membersScope} 기준이에요.
      </p>
      <AdminSection title="서비스 이용" icon={Users} id="stats-usage">
        <MetricTable caption="서비스 이용 지표" metrics={byGroup("usage")} minSample={data.minSample} />
      </AdminSection>
      <AdminSection title="브리핑 관심도" icon={Newspaper} id="stats-interest">
        <MetricTable caption="브리핑 관심도 지표" metrics={byGroup("interest")} minSample={data.minSample} />
      </AdminSection>
      <AdminSection title="AI 질문" icon={Sparkles} id="stats-ai">
        <MetricTable caption="AI 질문 지표" metrics={byGroup("ai")} minSample={data.minSample} />
      </AdminSection>

      <AdminSection title="일별 추이" icon={ChartColumn} id="stats-trend">
        <DataTable caption="일별 이용 추이">
          <thead>
            <tr>
              <Th>날짜(KST)</Th>
              <Th className="text-right">활성 사용자</Th>
              <Th className="text-right">노드 선택</Th>
              <Th className="text-right">간선 선택</Th>
              <Th className="text-right">브리핑 조회</Th>
              <Th className="text-right">AI 질문</Th>
            </tr>
          </thead>
          <tbody>
            {trend.map((day) => (
              <tr key={day.date}>
                <Td className="whitespace-nowrap tabular-nums">{day.date}</Td>
                <Td className="text-right">
                  <BarCell value={day.activeUsers} max={peaks.activeUsers} />
                </Td>
                <Td className="text-right">
                  <BarCell value={day.nodeSelections} max={peaks.nodeSelections} />
                </Td>
                <Td className="text-right">
                  <BarCell value={day.edgeSelections} max={peaks.edgeSelections} />
                </Td>
                <Td className="text-right">
                  <BarCell value={day.briefingViews} max={peaks.briefingViews} />
                </Td>
                <Td className="text-right">
                  <BarCell value={day.aiQuestions} max={peaks.aiQuestions} />
                </Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      </AdminSection>

      <AdminSection title="브리핑 회차별 조회" icon={Newspaper} id="stats-rounds">
        {data.rounds.length === 0 ? (
          <p className="py-2 text-base text-text-secondary">이 기간에 브리핑을 조회하거나 평가한 기록이 없어요.</p>
        ) : (
          <DataTable caption="브리핑 회차별 조회·평가">
            <thead>
              <tr>
                <Th>회차</Th>
                <Th className="text-right">조회</Th>
                <Th className="text-right">조회한 사용자</Th>
                <Th className="text-right">이슈 열기</Th>
                <Th className="text-right">좋아요</Th>
                <Th className="text-right">싫어요</Th>
              </tr>
            </thead>
            <tbody>
              {data.rounds.map((round) => (
                <tr key={round.roundId}>
                  <Td className="whitespace-nowrap tabular-nums">
                    {round.date} {editionLabel[round.edition]}
                  </Td>
                  <Td className="text-right">{formatCount(round.views)}</Td>
                  <Td className="text-right">{formatCount(round.viewers)}</Td>
                  <Td className="text-right">{formatCount(round.issueOpens)}</Td>
                  <Td className="text-right">{formatCount(round.likes)}</Td>
                  <Td className="text-right">{formatCount(round.dislikes)}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </AdminSection>
    </>
  );
}

function CompaniesPanel({ window }: { window: StatsWindow }) {
  const ranking = useCompanyRanking(window);
  if (ranking.isPending) return <SkeletonRows count={4} label="종목 순위를 불러오고 있어요" />;
  if (ranking.isError) return <ErrorState error={ranking.error} title="종목 순위를 불러오지 못했어요" onRetry={() => void ranking.refetch()} />;
  const data = ranking.data;
  return (
    <>
      <p className="text-sm text-text-secondary">
        기업 {formatCount(data.totalCompanies)}개 중 활동이 있는 {formatCount(data.items.length)}개 · {data.holdingsNote}
      </p>
      {data.items.length === 0 ? (
        <EmptyState title="아직 집계할 종목 활동이 없어요" description="사용자가 지도에서 기업을 고르거나 관심 종목을 저장하면 여기에 나타나요." />
      ) : (
        <DataTable caption="종목 순위">
          <thead>
            <tr>
              <Th className="w-12 text-right">순위</Th>
              <Th>기업</Th>
              <Th className="text-right">관심 등록(명)</Th>
              <Th className="text-right">가상 보유(명)</Th>
              <Th className="text-right">노드 조회</Th>
              <Th className="text-right">간선 선택</Th>
              <Th className="text-right">AI 질문</Th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((row, index) => (
              <tr key={row.companyId}>
                <Td className="text-right text-text-secondary">{index + 1}</Td>
                <Td className="font-medium">
                  <Link to={`/admin/stats/companies/${encodeURIComponent(row.companyId)}?window=${window}`} className="text-brand-primary underline underline-offset-4">
                    {row.name}
                  </Link>
                  {row.ticker && <span className="ml-2 text-sm font-normal text-text-secondary">{row.ticker}</span>}
                </Td>
                <Td className="text-right">{formatCount(row.watchlistMembers)}</Td>
                <Td className="text-right">{formatCount(row.holdingMembers)}</Td>
                <Td className="text-right">{formatCount(row.nodeViews)}</Td>
                <Td className="text-right">{formatCount(row.edgeSelections)}</Td>
                <Td className="text-right">{formatCount(row.aiQuestions)}</Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </>
  );
}

export function AdminStatsPage() {
  const [params, setParams] = useSearchParams();
  const window = parseWindow(params.get("window"));
  const tab = params.get("tab") === "companies" ? "companies" : "summary";
  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(patch)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    setParams(next, { replace: true });
  };

  return (
    <>
      <AdminPageHeader title="이용 통계" icon={BarChart3} actions={<WindowSwitch value={window} onChange={(value) => update({ window: value === "7d" ? null : value })} />} />
      <Tabs value={tab} onValueChange={(value) => update({ tab: value === "summary" ? null : value })} className="flex flex-col gap-4">
        <TabsList className="max-w-md">
          <TabsTrigger value="summary">
            <ChartColumn aria-hidden="true" />
            요약
          </TabsTrigger>
          <TabsTrigger value="companies">
            <ListOrdered aria-hidden="true" />
            종목 순위
          </TabsTrigger>
        </TabsList>
        <TabsContent value="summary" className="flex flex-col gap-4">
          <SummaryPanel window={window} />
        </TabsContent>
        <TabsContent value="companies" className="flex flex-col gap-4">
          <CompaniesPanel window={window} />
        </TabsContent>
      </Tabs>
    </>
  );
}
