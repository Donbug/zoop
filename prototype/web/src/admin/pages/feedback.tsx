// 선호도(요구 75): AI 기능별 좋아요/싫어요(비율·일별 추이), 싫어요 사유 목록, AI 대화록 목록.
// 사용자는 가명 id로만 보이고, 사유·질문은 개인정보를 가린 사본이다. 표본이 작으면 비율 대신 건수만 보여 준다.
import { ChartColumn, EyeOff, Info, MessageSquareText, ThumbsDown, ThumbsUp } from "lucide-react";
import { Link, useSearchParams } from "react-router";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { Segmented } from "@/components/ui/segmented";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useDislikes, useFeedbackSummary, useTranscripts, type StatsWindow } from "../api";
import { formatCount } from "../format";
import { formatPercent, parseWindow, WindowSwitch } from "../insights-ui";
import { AdminPageHeader, AdminSection, DataTable, KstTime, StatusLabel, Td, Th } from "../ui";

const tabs = ["summary", "dislikes", "transcripts"] as const;
type FeedbackTab = (typeof tabs)[number];

function Votes({ up, down, rate }: { up: number; down: number; rate?: number | null }) {
  return (
    <span className="whitespace-nowrap tabular-nums">
      {formatCount(up)} / {formatCount(down)}
      {rate != null && <span className="ml-1 text-text-secondary">({formatPercent(rate)})</span>}
    </span>
  );
}

function SummaryPanel({ window }: { window: StatsWindow }) {
  const summary = useFeedbackSummary(window);
  if (summary.isPending) return <SkeletonRows count={3} label="선호도를 불러오고 있어요" />;
  if (summary.isError) return <ErrorState error={summary.error} title="선호도를 불러오지 못했어요" onRetry={() => void summary.refetch()} />;
  const data = summary.data;
  const dates = (data.features[0]?.days ?? []).map((d) => d.date).reverse();
  return (
    <>
      <p className="text-sm text-text-secondary">
        집계 시각 <KstTime value={data.asOf} seconds /> · {data.basis} (기준 표 {data.minSample}개)
      </p>
      <AdminSection title="기능별 좋아요 비율" icon={ThumbsUp} id="feedback-features">
        <DataTable caption="AI 기능별 좋아요·싫어요">
          <thead>
            <tr>
              <Th>기능</Th>
              <Th className="text-right">좋아요</Th>
              <Th className="text-right">싫어요</Th>
              <Th className="text-right">표 합계</Th>
              <Th className="text-right">좋아요 비율</Th>
            </tr>
          </thead>
          <tbody>
            {data.features.map((f) => (
              <tr key={f.feature}>
                <Td className="font-medium">{f.label}</Td>
                <Td className="text-right">{formatCount(f.up)}</Td>
                <Td className="text-right">{formatCount(f.down)}</Td>
                <Td className="text-right">{formatCount(f.total)}</Td>
                <Td className="text-right">
                  {f.rate == null ? (
                    <StatusLabel icon={EyeOff} label={`표본 부족(${formatCount(f.total)}/${data.minSample})`} tone="warning" />
                  ) : (
                    <span className="font-semibold tabular-nums">{formatPercent(f.rate)}</span>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
        {data.unsupported.map((u) => (
          <p key={u.feature} className="flex items-start gap-2 text-sm text-text-secondary">
            <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <span>
              {u.label}: {u.reason}
            </span>
          </p>
        ))}
      </AdminSection>
      <AdminSection title="일별 추이" icon={ChartColumn} id="feedback-trend">
        <DataTable caption="일별 좋아요·싫어요">
          <thead>
            <tr>
              <Th>날짜(KST)</Th>
              {data.features.map((f) => (
                <Th key={f.feature} className="text-right">
                  {f.label}
                  <span className="block text-xs font-normal">좋아요 / 싫어요(비율)</span>
                </Th>
              ))}
            </tr>
          </thead>
          <tbody>
            {dates.map((date) => (
              <tr key={date}>
                <Td className="whitespace-nowrap tabular-nums">{date}</Td>
                {data.features.map((f) => {
                  const day = f.days.find((d) => d.date === date);
                  return (
                    <Td key={f.feature} className="text-right">
                      <Votes up={day?.up ?? 0} down={day?.down ?? 0} rate={day?.rate} />
                    </Td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </DataTable>
      </AdminSection>
    </>
  );
}

function DislikesPanel({ window }: { window: StatsWindow }) {
  const dislikes = useDislikes(window);
  const rows = dislikes.data?.pages.flatMap((page) => page.items) ?? [];
  const total = dislikes.data?.pages[0]?.total ?? 0;
  if (dislikes.isPending) return <SkeletonRows count={4} label="싫어요 사유를 불러오고 있어요" />;
  if (dislikes.isError) return <ErrorState error={dislikes.error} title="싫어요 사유를 불러오지 못했어요" onRetry={() => void dislikes.refetch()} />;
  if (rows.length === 0) return <EmptyState title="이 기간에 싫어요가 없어요" />;
  return (
    <>
      <p className="text-sm text-text-secondary">싫어요 {formatCount(total)}건 · 사유와 질문은 개인정보를 가린 사본이에요.</p>
      <DataTable caption="싫어요 사유">
        <thead>
          <tr>
            <Th>시각</Th>
            <Th>기능</Th>
            <Th>대상</Th>
            <Th>사유</Th>
            <Th>사용자</Th>
            <Th>대화록</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.targetId}-${row.voter}`}>
              <Td>
                <KstTime value={row.at} seconds />
              </Td>
              <Td className="whitespace-nowrap">{row.featureLabel}</Td>
              <Td className="max-w-72 text-sm text-text-secondary">{row.targetLabel}</Td>
              <Td className="max-w-96">{row.reason ?? <span className="text-text-tertiary">사유 없음</span>}</Td>
              <Td className="font-mono text-sm whitespace-nowrap">{row.voter}</Td>
              <Td>
                {row.sessionId ? (
                  <Link to={`/admin/feedback/transcripts/${encodeURIComponent(row.sessionId)}`} className="text-sm font-medium text-brand-primary underline-offset-4 hover:underline">
                    열람
                  </Link>
                ) : (
                  <span className="text-text-tertiary">–</span>
                )}
              </Td>
            </tr>
          ))}
        </tbody>
      </DataTable>
      {dislikes.hasNextPage && (
        <Button variant="secondary" className="self-start" loading={dislikes.isFetchingNextPage} onClick={() => void dislikes.fetchNextPage()}>
          더 보기
        </Button>
      )}
    </>
  );
}

function TranscriptsPanel({ only, onOnlyChange }: { only: "all" | "disliked"; onOnlyChange: (only: "all" | "disliked") => void }) {
  const transcripts = useTranscripts(only);
  const rows = transcripts.data?.pages.flatMap((page) => page.items) ?? [];
  const total = transcripts.data?.pages[0]?.total ?? 0;
  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <Segmented
          aria-label="대화록 보기"
          value={only}
          onValueChange={onOnlyChange}
          options={[
            { value: "all", label: "모든 대화" },
            { value: "disliked", label: "싫어요가 있는 대화" },
          ]}
        />
        <p className="text-sm text-text-secondary">대화 {formatCount(total)}건 · 열람하면 감사 로그에 남아요. 개인정보는 가려서 보여 줘요.</p>
      </div>
      {transcripts.isPending && <SkeletonRows count={4} label="대화록을 불러오고 있어요" />}
      {transcripts.isError && <ErrorState error={transcripts.error} title="대화록을 불러오지 못했어요" onRetry={() => void transcripts.refetch()} />}
      {transcripts.isSuccess && rows.length === 0 && <EmptyState title="조건에 맞는 대화가 없어요" />}
      {rows.length > 0 && (
        <DataTable caption="AI 대화록">
          <thead>
            <tr>
              <Th>마지막 대화</Th>
              <Th>사용자</Th>
              <Th>첫 질문(가림)</Th>
              <Th className="text-right">질문 수</Th>
              <Th className="text-right">좋아요 / 싫어요</Th>
              <Th>대화록</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <Td>
                  <KstTime value={row.lastAt} seconds />
                </Td>
                <Td className="font-mono text-sm whitespace-nowrap">
                  {row.user}
                  <span className="ml-2 font-sans text-text-secondary">{row.userKind === "member" ? "회원" : "비회원"}</span>
                </Td>
                <Td className="max-w-md">{row.preview}</Td>
                <Td className="text-right">{formatCount(row.messages)}</Td>
                <Td className="text-right">
                  <Votes up={row.up} down={row.down} />
                </Td>
                <Td>
                  <Link to={`/admin/feedback/transcripts/${encodeURIComponent(row.id)}`} className="text-sm font-medium text-brand-primary underline-offset-4 hover:underline">
                    열람
                  </Link>
                </Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
      {transcripts.hasNextPage && (
        <Button variant="secondary" className="self-start" loading={transcripts.isFetchingNextPage} onClick={() => void transcripts.fetchNextPage()}>
          더 보기
        </Button>
      )}
    </>
  );
}

export function AdminFeedbackPage() {
  const [params, setParams] = useSearchParams();
  const window = parseWindow(params.get("window"));
  const tab: FeedbackTab = tabs.includes(params.get("tab") as FeedbackTab) ? (params.get("tab") as FeedbackTab) : "summary";
  const only = params.get("only") === "disliked" ? "disliked" : "all";
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
      <AdminPageHeader
        title="선호도"
        icon={ThumbsUp}
        actions={tab === "transcripts" ? undefined : <WindowSwitch value={window} onChange={(value) => update({ window: value === "7d" ? null : value })} />}
      />
      <Tabs value={tab} onValueChange={(value) => update({ tab: value === "summary" ? null : value })} className="flex flex-col gap-4">
        <TabsList className="max-w-xl">
          <TabsTrigger value="summary">
            <ThumbsUp aria-hidden="true" />
            요약
          </TabsTrigger>
          <TabsTrigger value="dislikes">
            <ThumbsDown aria-hidden="true" />
            싫어요 사유
          </TabsTrigger>
          <TabsTrigger value="transcripts">
            <MessageSquareText aria-hidden="true" />
            AI 대화록
          </TabsTrigger>
        </TabsList>
        <TabsContent value="summary" className="flex flex-col gap-4">
          <SummaryPanel window={window} />
        </TabsContent>
        <TabsContent value="dislikes" className="flex flex-col gap-4">
          <DislikesPanel window={window} />
        </TabsContent>
        <TabsContent value="transcripts" className="flex flex-col gap-4">
          <TranscriptsPanel only={only} onOnlyChange={(value) => update({ only: value === "all" ? null : value })} />
        </TabsContent>
      </Tabs>
    </>
  );
}
