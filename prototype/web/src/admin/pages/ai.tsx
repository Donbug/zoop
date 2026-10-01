// AI 운영(요구 77): 챗봇·뉴스 분석·브리핑별 요청·성공·실패·처리 시간·사용량, 비용(실제·추정 구분).
// 비용 단가를 지어내지 않는다: 서버가 미제공이라 하면 "미제공"과 이유만 보여 준다.
import { CircleAlert, CircleHelp, History, Sparkles } from "lucide-react";
import { useState } from "react";
import { ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { IconHint } from "@/components/ui/icon-hint";
import { Segmented } from "@/components/ui/segmented";
import { useAiUsage } from "../api";
import { formatCount, formatDurationMs } from "../format";
import { AdminPageHeader, AdminSection, DataTable, KstTime, Td, Th } from "../ui";

type Window = "24h" | "7d" | "30d" | "all";
const windowOptions: { value: Window; label: string }[] = [
  { value: "24h", label: "24시간" },
  { value: "7d", label: "7일" },
  { value: "30d", label: "30일" },
  { value: "all", label: "전체" },
];

const sourceLabel: Record<string, string> = {
  measured: "BFF 실측",
  "job-runner": "작업 러너",
  "ledger-db": "원장 DB",
  document: "문서 기록",
};

const policyGroupLabel: Record<string, string> = {
  "strict-web": "엄격(웹 검증)",
  "relaxed-no-web": "완화(웹 검증 없음)",
  "admin-job": "관리자 작업",
};

function CostCell({ cost }: { cost: { status: string; estimated: number | null; reason: string } }) {
  if (cost.status === "estimated" && cost.estimated != null) {
    return <span className="tabular-nums">추정 {formatCount(cost.estimated)}</span>;
  }
  return (
    <span className="inline-flex items-center gap-1 text-text-secondary">
      미제공
      <IconHint icon={CircleHelp} label="비용 미제공 이유">
        <p>{cost.reason}</p>
      </IconHint>
    </span>
  );
}

export function AdminAiPage() {
  const [window, setWindow] = useState<Window>("7d");
  const usage = useAiUsage(window);
  const data = usage.data;

  return (
    <>
      <AdminPageHeader
        title="AI 운영"
        icon={Sparkles}
        actions={<Segmented aria-label="집계 기간" value={window} onValueChange={setWindow} options={windowOptions} />}
      />
      {usage.isPending && <SkeletonRows count={3} label="AI 사용량을 불러오고 있어요" />}
      {usage.isError && <ErrorState error={usage.error} title="AI 사용량을 불러오지 못했어요" onRetry={() => void usage.refetch()} />}
      {data && (
        <>
          <p className="text-sm text-text-secondary">
            집계 시각 <KstTime value={data.asOf} seconds /> · 비용 {data.cost.status === "unavailable" ? `미제공(${data.cost.reason})` : "추정"}
          </p>
          <AdminSection title="기능별 사용량" icon={Sparkles} id="ai-features">
            <DataTable caption="AI 기능별 사용량">
              <thead>
                <tr>
                  <Th>기능</Th>
                  <Th>처리 방식</Th>
                  <Th className="text-right">요청</Th>
                  <Th className="text-right">성공</Th>
                  <Th className="text-right">실패</Th>
                  <Th className="text-right">평균 처리</Th>
                  <Th className="text-right">p95</Th>
                  <Th className="text-right">모델 호출</Th>
                  <Th className="text-right">입력 토큰</Th>
                  <Th className="text-right">출력 토큰</Th>
                  <Th>비용</Th>
                  <Th>집계 출처</Th>
                </tr>
              </thead>
              <tbody>
                {data.features.map((f) => (
                  <tr key={f.feature}>
                    <Td className="font-medium whitespace-nowrap">
                      <span className="inline-flex items-center gap-1">
                        {f.label}
                        {f.note && (
                          <IconHint icon={CircleHelp} label={`${f.label} 집계 참고`}>
                            <p>{f.note}</p>
                          </IconHint>
                        )}
                      </span>
                    </Td>
                    <Td className="text-text-secondary">{f.engine}</Td>
                    <Td className="text-right">{formatCount(f.requests)}</Td>
                    <Td className="text-right">{formatCount(f.succeeded)}</Td>
                    <Td className="text-right">{formatCount(f.failed)}</Td>
                    <Td className="text-right">{formatDurationMs(f.latencyMs?.avg)}</Td>
                    <Td className="text-right">{formatDurationMs(f.latencyMs?.p95)}</Td>
                    <Td className="text-right">{formatCount(f.usage?.modelCalls)}</Td>
                    <Td className="text-right">{formatCount(f.usage?.inputTokens)}</Td>
                    <Td className="text-right">{formatCount(f.usage?.outputTokens)}</Td>
                    <Td className="whitespace-nowrap">
                      <CostCell cost={f.cost} />
                    </Td>
                    <Td className="whitespace-nowrap text-text-secondary">{sourceLabel[f.source] ?? f.source}</Td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          </AdminSection>

          <AdminSection title="최근 오류" icon={CircleAlert} id="ai-errors">
            {data.features.every((f) => f.recentErrors.length === 0) ? (
              <p className="py-2 text-base text-text-secondary">이 기간에 기록된 오류가 없어요.</p>
            ) : (
              <DataTable caption="AI 최근 오류">
                <thead>
                  <tr>
                    <Th>시각</Th>
                    <Th>기능</Th>
                    <Th>코드</Th>
                    <Th>내용</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.features.flatMap((f) =>
                    f.recentErrors.map((e, i) => (
                      <tr key={`${f.feature}-${e.at}-${i}`}>
                        <Td>
                          <KstTime value={e.at} seconds />
                        </Td>
                        <Td>{f.label}</Td>
                        <Td className="text-sm">{e.code}</Td>
                        <Td>{e.message}</Td>
                      </tr>
                    )),
                  )}
                </tbody>
              </DataTable>
            )}
          </AdminSection>

          <AdminSection title="뉴스 분석 실행 기록" icon={History} id="ai-runs">
            <DataTable caption="뉴스 분석 실행 기록">
              <thead>
                <tr>
                  <Th>실행</Th>
                  <Th>정책</Th>
                  <Th className="text-right">처리</Th>
                  <Th className="text-right">승인</Th>
                  <Th className="text-right">보류</Th>
                  <Th className="text-right">거부</Th>
                  <Th className="text-right">오류</Th>
                  <Th className="text-right">모델 호출</Th>
                  <Th className="text-right">입력 토큰</Th>
                  <Th className="text-right">걸린 시간</Th>
                  <Th>출처</Th>
                </tr>
              </thead>
              <tbody>
                {data.pastRuns.map((run, i) => (
                  <tr key={run.runId ?? `${run.label}-${i}`}>
                    <Td className="font-medium">{run.label}</Td>
                    <Td className="text-text-secondary">{policyGroupLabel[run.policyGroup] ?? run.policyGroup}</Td>
                    <Td className="text-right">{formatCount(run.processed)}</Td>
                    <Td className="text-right">{formatCount(run.approved)}</Td>
                    <Td className="text-right">{formatCount(run.held)}</Td>
                    <Td className="text-right">{formatCount(run.rejected)}</Td>
                    <Td className="text-right">{formatCount(run.errorCount)}</Td>
                    <Td className="text-right">{formatCount(run.usage.calls)}</Td>
                    <Td className="text-right">{formatCount(run.usage.inputTokens)}</Td>
                    <Td className="text-right">{formatDurationMs(run.usage.elapsedSeconds == null ? null : run.usage.elapsedSeconds * 1000)}</Td>
                    <Td className="text-text-secondary">{sourceLabel[run.source] ?? run.source}</Td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          </AdminSection>
        </>
      )}
    </>
  );
}
