import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { Schemas } from "@/api/client";
import { AdminAiPage } from "@/admin/pages/ai";
import { TooltipProvider } from "@/components/ui/tooltip";

const { useAiUsage } = vi.hoisted(() => ({ useAiUsage: vi.fn() }));
vi.mock("@/admin/api", () => ({ useAiUsage }));
afterEach(cleanup);

const cost: Schemas["FeatureCost"] = { status: "unavailable", actual: null, estimated: null, currency: null, reason: "시험: 단가 없음" };
const features: Schemas["AiFeature"][] = [
  { feature: "document-sentiment", label: "문서×기업 판정", engine: "시험 모델", modelBacked: true, requests: 8, succeeded: 6, failed: 2, latencyMs: null, usage: { modelCalls: 3, replayCalls: 5, retries: 2, inputTokens: 120, outputTokens: 40 }, cost, source: "measured", recentErrors: [], note: "" },
  { feature: "briefing-outlook", label: "브리핑 회차 판단", engine: "시험 모델", modelBacked: true, requests: 0, succeeded: 0, failed: 0, latencyMs: null, usage: { modelCalls: 0, replayCalls: 0, retries: 0, inputTokens: 0, outputTokens: 0 }, cost, source: "measured", recentErrors: [], note: "" },
];

describe("관리자 AI 사용량", () => {
  test("새 기능 행을 동적으로 그리고 실제 호출·재생·재시도·실패를 서로 다른 열에 표시한다", () => {
    const data: Schemas["AiUsageResponse"] = { asOf: "2026-10-06T07:40:00+09:00", window: "7d", features, pastRuns: [], cost };
    useAiUsage.mockReturnValue({ data, isPending: false, isError: false });
    render(<TooltipProvider><AdminAiPage /></TooltipProvider>);
    const table = screen.getByRole("table", { name: "AI 기능별 사용량" });
    const headers = within(table).getAllByRole("columnheader").map((header) => header.textContent);
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText("문서×기업 판정")).toBeTruthy();
    expect(within(rows[1]!).getByText("브리핑 회차 판단")).toBeTruthy();
    const cells = within(rows[0]!).getAllByRole("cell");
    expect(cells[headers.indexOf("실제 모델 호출")]!.textContent).toBe("3");
    expect(cells[headers.indexOf("재생(호출 아님)")]!.textContent).toBe("5");
    expect(cells[headers.indexOf("재시도")]!.textContent).toBe("2");
    expect(cells[headers.indexOf("실패")]!.textContent).toBe("2");
    const emptyCells = within(rows[1]!).getAllByRole("cell");
    for (const name of ["실제 모델 호출", "재생(호출 아님)", "재시도", "실패"]) {
      expect(emptyCells[headers.indexOf(name)]!.textContent).toBe("0");
    }
  });
});
