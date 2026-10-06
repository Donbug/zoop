import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test } from "vitest";
import type { Schemas } from "@/api/client";
import { SentimentLabel } from "@/components/domain/status-labels";
import { sentimentLabel } from "@/lib/labels";
import { openApp } from "./support/app";
import { json } from "./support/fake-bff";
import { ALPHA, metadata } from "./support/fixtures";

const judgement: Schemas["DocumentSentiment"] = {
  label: "positive", companyId: ALPHA.id,
  rationale: "시험: 매출 증가가 기사에 직접 나와요.",
  quotes: ["시험: 알파전자의 매출이 늘었다."],
  judgedAt: "2026-10-06T07:40:00+09:00", model: "test-model", promptVersion: "test-prompt-v1",
};
const outlook: Schemas["BriefingOutlook"] = {
  label: "mixed", rationale: "시험: 매출 증가와 비용 부담이 함께 보도됐어요.",
  issueIds: ["issue-test"], judgedAt: judgement.judgedAt, model: judgement.model, promptVersion: judgement.promptVersion,
};
const round = (value: Schemas["BriefingOutlook"] | null): Schemas["BriefingResponse"] => ({
  id: "round-test", date: "2026-10-06", edition: "morning", status: "published",
  scheduledAt: "2026-10-06T07:40:00+09:00", publishedAt: "2026-10-06T07:41:00+09:00", generatedAt: "2026-10-06T07:41:00+09:00",
  dataWindow: { start: "2026-10-05T18:10:00+09:00", end: "2026-10-06T07:40:00+09:00", openStart: false },
  dataAsOf: "2026-10-06T07:40:00+09:00", graphVersion: "v1", outlook: value,
  items: [{
    eventId: "issue-test", title: "알파전자 실적 발표", rank: 1, eventTime: "2026-10-06", timePrecision: "day",
    companies: [{ id: ALPHA.id, name: ALPHA.name, role: null, roleUnconfirmed: false, relationType: "INVOLVES" }], evidenceCount: 1, reason: "시험 선정 이유",
    sourceSupport: { articleCount: 1, knownLineageCount: 1, unknownLineageArticles: [], independentSourceCount: 1, duplicateGroups: [] },
    matchedCompanyIds: [], evidenceIds: [], summary: { status: "unavailable", reason: "시험 요약 없음" }, reportedAt: null,
    documentSentiments: value ? [{ articleId: "article-test", sentiment: judgement }] : [],
  }],
  marketSummary: { status: "unavailable", reason: "시험 요약 없음" }, marketVariables: { status: "unavailable", reason: "시험 지표 없음" }, sinceMorning: null,
  emptyReason: null, corrections: [], notice: null, references: { eventIds: ["issue-test"], evidenceIds: [], companyIds: [ALPHA.id] },
  metadata: { ...metadata, schedule: { morning: "07:40", evening: "18:10", confirmed: true }, selection: { basis: "market", reason: "recent_in_window" } },
});
const open = (value: Schemas["BriefingOutlook"] | null) => openApp("/briefing?date=2026-10-06&edition=morning", (bff) => {
  bff.on("GET", "/api/briefings", json(round(value)));
  bff.on("GET", "/api/briefings/rounds", json({ items: [{ id: "round-test", date: "2026-10-06", edition: "morning", status: "published", publishedAt: "2026-10-06T07:41:00+09:00" }] }));
  bff.on("GET", "/api/feedback", json({ items: [] }));
  bff.on("POST", "/api/telemetry", json({ accepted: 0 }, 202));
});

afterEach(cleanup);

describe("기사 판정", () => {
  test.each(["positive", "negative", "mixed", "undetermined"] as const)("%s는 labels.ts 표기를 쓰고 등락색을 쓰지 않는다", (label) => {
    render(<SentimentLabel judgement={{ ...judgement, label }} />);
    const button = screen.getByRole("button", { name: `${sentimentLabel[label]} 판정 근거 보기` });
    expect(button.textContent).toBe(sentimentLabel[label]);
    expect(button.className).not.toMatch(/text-up|text-down/);
    expect(screen.getByText("AI 판정")).toBeTruthy();
  });

  test("표기 원천을 바꾸면 라벨 글자도 바뀐다", () => {
    const original = sentimentLabel.positive;
    try {
      sentimentLabel.positive = "시험용 표기";
      render(<SentimentLabel judgement={judgement} />);
      expect(screen.getByRole("button", { name: "시험용 표기 판정 근거 보기" }).textContent).toBe("시험용 표기");
    } finally { sentimentLabel.positive = original; }
  });

  test("null은 아무것도 그리지 않는다", () => {
    const { container } = render(<SentimentLabel judgement={null} />);
    expect(container.innerHTML).toBe("");
  });

  test("라벨에서 사유·원문 인용·KST 시각·모델·프롬프트를 열고 Esc로 닫는다", async () => {
    const user = userEvent.setup();
    render(<SentimentLabel judgement={judgement} accessibleName="알파전자" />);
    const trigger = screen.getByRole("button", { name: "알파전자 · 긍정 판정 근거 보기" });
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "알파전자 · 긍정 판정 근거" });
    const popup = within(dialog);
    expect(popup.getByText(judgement.rationale)).toBeTruthy();
    expect(popup.getByText(`“${judgement.quotes[0]}”`)).toBeTruthy();
    expect(popup.getByText("2026-10-06 07:40 KST")).toBeTruthy();
    expect(popup.getByText(judgement.model)).toBeTruthy();
    expect(popup.getByText(judgement.promptVersion)).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});

describe("브리핑 발행 판정", () => {
  test("outlook null과 빈 문서 판정이면 영역·고지를 그리지 않는다", async () => {
    await open(null);
    await screen.findByRole("heading", { name: "핵심 이슈" });
    expect(screen.queryByRole("region", { name: "회차 판단" })).toBeNull();
    expect(screen.queryByText("주가 전망이 아니에요.")).toBeNull();
    expect(screen.queryByText("AI 판정")).toBeNull();
  });

  test("회차 라벨·사유·실제 근거 이슈 링크와 기업별 문서 판정을 보인다", async () => {
    await open(outlook);
    const section = within(await screen.findByRole("region", { name: "회차 판단" }));
    expect(section.getByRole("button", { name: "회차 · 혼재 판정 근거 보기" })).toBeTruthy();
    expect(section.getByText(outlook.rationale)).toBeTruthy();
    expect(section.getByRole("link", { name: "1. 알파전자 실적 발표" }).getAttribute("href")).toBe("#briefing-issue-issue-test");
    expect(document.getElementById("briefing-issue-issue-test")).toBeTruthy();
    expect(screen.getAllByText("주가 전망이 아니에요.")).toHaveLength(1);
    expect(screen.getByRole("list", { name: "관련 기업 문서 판정" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "알파전자 · 핵심 이슈 1 · 긍정 판정 근거 보기" })).toBeTruthy();
  });
});
