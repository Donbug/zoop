// FS031 주요 시장 지표 · M-BRF-01 아침 이후 바뀐 내용.
// 상태는 색이 아니라 글자로 구분된다: 불러오지 못했어요(요청 실패) · 아직 없어요(출처에 그 시점 값이 없음) · 지연(값은 보이되 표지).
// 한 지표의 상태가 다른 지표를 가리지 않고, 저장되지 않은 옛 회차는 그렇다고 말한다.
import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import type { Schemas } from "@/api/client";
import { openApp } from "./support/app";
import { json, type FakeBff } from "./support/fake-bff";
import { metadata } from "./support/fixtures";

type Briefing = Schemas["BriefingResponse"];
type Indicator = Schemas["MarketIndicator"];

const source = { provider: "yahoo", name: "Yahoo Finance", official: false, delayNote: "비공식 공개 차트 자료예요.", symbol: "^KS11", url: "https://finance.yahoo.com/quote/%5EKS11" } as const;

const kospi: Indicator = {
  id: "kospi",
  label: "KOSPI",
  unit: "pt",
  status: "ok",
  value: 7003.74,
  valueKind: "close",
  observedDate: "2026-10-02",
  observedAt: null,
  baseline: { value: 6971.35, date: "2026-10-01", at: null },
  change: 32.39,
  changeRate: 0.00464617,
  source,
  reasonCode: null,
  reason: null,
};
const withoutValue = (id: Indicator["id"], label: string, status: "failed" | "unavailable", reason: string): Indicator => ({
  id,
  label,
  unit: "pt",
  status,
  value: null,
  valueKind: null,
  observedDate: null,
  observedAt: null,
  baseline: null,
  change: null,
  changeRate: null,
  source: null,
  reasonCode: status === "failed" ? "temporary_failure" : "no_data",
  reason,
});
const rate: Indicator = {
  id: "usdkrw",
  label: "원/달러",
  unit: "KRW",
  status: "delayed",
  value: 1361,
  valueKind: "latest",
  observedDate: "2026-09-17",
  observedAt: "2026-09-17T17:20:00+09:00",
  baseline: { value: 1355, date: "2026-09-16", at: "2026-09-16T15:30:00+09:00" },
  change: 6,
  changeRate: 6 / 1355,
  source: { ...source, symbol: "KRW=X", url: "https://finance.yahoo.com/quote/KRW=X" },
  reasonCode: null,
  reason: "기준 시각보다 45분 앞선 값이에요.",
};

function briefing(patch: Partial<Briefing>): Briefing {
  return {
    id: "brf-2026-09-17-evening",
    date: "2026-09-17",
    edition: "evening",
    status: "published",
    scheduledAt: "2026-09-17T18:10:00+09:00",
    publishedAt: "2026-09-17T09:11:30+00:00",
    generatedAt: "2026-09-17T09:11:30+00:00",
    dataWindow: { start: "2026-09-17T07:40:00+09:00", end: "2026-09-17T18:10:00+09:00", openStart: false },
    dataAsOf: "2026-09-17T18:10:00+09:00",
    graphVersion: "v1",
    items: [],
    marketSummary: { status: "unavailable", reason: "시장 요약 생산자가 없습니다." },
    marketVariables: { status: "available", referenceAt: "2026-09-17T18:10:00+09:00", rateCutoffAt: "2026-09-17T18:05:00+09:00", collectedAt: "2026-09-17T09:11:30+00:00", indicators: [kospi, rate] },
    sinceMorning: null,
    emptyReason: "no_issues_in_window",
    corrections: [],
    notice: null,
    references: { eventIds: [], evidenceIds: [], companyIds: [] },
    metadata: { ...metadata, schedule: { morning: "07:40", evening: "18:10", confirmed: true }, selection: { basis: "market", reason: "recent_in_window" } },
    ...patch,
  };
}

const open = (round: Briefing) =>
  openApp(`/briefing?date=${round.date}&edition=${round.edition}`, (bff: FakeBff) => {
    bff.on("GET", "/api/briefings", json(round));
    bff.on("GET", "/api/briefings/rounds", json({ items: [{ id: round.id, date: round.date, edition: round.edition, status: "published", publishedAt: round.publishedAt }] }));
    bff.on("POST", "/api/telemetry", json({ accepted: 0 }, 202));
  });

const card = (label: string) => screen.getByText(label, { selector: "span" }).closest("li") as HTMLElement;

describe("주요 시장 지표", () => {
  test("지표마다 상태가 따로 보이고, 하나가 불러오지 못해도 나머지는 값을 보인다", async () => {
    await open(
      briefing({
        marketVariables: {
          status: "available",
          referenceAt: "2026-09-17T18:10:00+09:00",
          rateCutoffAt: "2026-09-17T18:05:00+09:00",
          collectedAt: "2026-09-17T09:11:30+00:00",
          indicators: [kospi, withoutValue("kosdaq", "KOSDAQ", "failed", "이 회차를 만들 때 출처에 연결하지 못했어요."), rate],
        },
      }),
    );
    await screen.findByText("주요 시장 지표");
    expect(within(screen.getByRole("region", { name: "2026-09-17 퇴근 브리핑" })).getByText("발행", { selector: "span" })).toBeTruthy();

    const first = within(card("KOSPI"));
    expect(first.getByText("7,003.74")).toBeTruthy();
    expect(first.getByText(/▲ \+32\.39 \(\+0\.46%\)/)).toBeTruthy();
    expect(first.getByText("10월 2일 종가")).toBeTruthy();
    expect(first.getByText("10월 1일 종가 대비")).toBeTruthy();

    // 요청 실패: 값 자리에 글자로 말하고, 지연·아직 없음 표지는 붙지 않는다.
    const failed = within(card("KOSDAQ"));
    expect(failed.getByText("불러오지 못했어요")).toBeTruthy();
    expect(failed.queryByText("아직 없어요")).toBeNull();
    expect(failed.queryByText("지연")).toBeNull();

    // 지연: 값과 실제 관측 시각을 그대로 보이고 '지연' 글자 표지를 붙인다.
    const late = within(card("원/달러"));
    expect(late.getByText("지연")).toBeTruthy();
    expect(late.getByText("1,361.00원")).toBeTruthy();
    expect(late.getByText("9월 17일 17:20 기준")).toBeTruthy();
    expect(late.getByText("9월 16일 15:30 대비")).toBeTruthy();
    expect(late.getByText("기준 시각보다 45분 앞선 값이에요.")).toBeTruthy();
    expect(within(card("KOSPI")).queryByText("지연")).toBeNull();
  });

  test("출처에 그 시점 값이 없으면 '아직 없어요'로, 요청 실패와 구분한다", async () => {
    await open(
      briefing({
        marketVariables: {
          status: "available",
          referenceAt: "2026-09-17T18:10:00+09:00",
          rateCutoffAt: "2026-09-17T18:05:00+09:00",
          collectedAt: "2026-09-17T09:11:30+00:00",
          indicators: [withoutValue("kospi", "KOSPI", "unavailable", "출처에 이 시점 이전의 지수 자료가 없어요."), { ...kospi, id: "kosdaq", label: "KOSDAQ" }, { ...rate, status: "ok", reason: null }],
        },
      }),
    );
    await screen.findByText("주요 시장 지표");
    const none = within(card("KOSPI"));
    expect(none.getByText("아직 없어요")).toBeTruthy();
    expect(none.getByText("출처에 이 시점 이전의 지수 자료가 없어요.")).toBeTruthy();
    expect(none.queryByText("불러오지 못했어요")).toBeNull();
    expect(within(card("KOSDAQ")).getByText("7,003.74")).toBeTruthy();
  });

  test("지표가 저장되지 않은 옛 회차는 그렇다고 말한다", async () => {
    await open(briefing({ marketVariables: { status: "unavailable", reason: "이 회차에는 시장 지표가 저장되지 않았어요." } }));
    await screen.findByText("이 회차에는 시장 지표가 저장되지 않았어요.");
    expect(screen.queryByText("불러오지 못했어요")).toBeNull();
    expect(screen.queryByText("KOSPI")).toBeNull();
  });
});

describe("회차 상태와 아침 이후 바뀐 내용", () => {
  const item = (eventId: string, title: string, change: "new" | "continuing" | "dropped", extra: object): Extract<NonNullable<Briefing["sinceMorning"]>, { status: "available" }>["items"][number] => ({
    eventId,
    title,
    eventTime: null,
    timePrecision: "unknown",
    reportedAt: null,
    companyNames: [],
    change,
    rank: null,
    morningRank: null,
    evidenceCount: null,
    morningEvidenceCount: null,
    ...extra,
  });

  test("신규·이어짐·빠짐을 글자로 구분해 시간순으로 보이고, 이어진 이슈는 근거 수 변화를 적는다", async () => {
    await open(
      briefing({
        sinceMorning: {
          status: "available",
          morningRoundId: "brf-2026-09-17-morning",
          morningPublishedAt: "2026-09-16T22:41:30+00:00",
          morningDataAsOf: "2026-09-17T07:40:00+09:00",
          items: [
            item("a", "아침에만 있던 이슈", "dropped", { reportedAt: "2026-09-17T06:00:00+09:00", morningRank: 1, morningEvidenceCount: 1 }),
            item("b", "아침부터 이어진 이슈", "continuing", { reportedAt: "2026-09-17T10:05:00+09:00", rank: 2, morningRank: 1, evidenceCount: 3, morningEvidenceCount: 2 }),
            item("c", "오후에 새로 들어온 이슈", "new", { reportedAt: "2026-09-17T16:30:00+09:00", rank: 1, evidenceCount: 1 }),
          ],
        },
      }),
    );
    const heading = await screen.findByText("아침 이후 바뀐 내용");
    const section = heading.closest("section") as HTMLElement;
    const rows = within(section).getAllByRole("listitem");
    expect(rows.map((row) => within(row).getByRole("link").textContent)).toEqual(["아침에만 있던 이슈", "아침부터 이어진 이슈", "오후에 새로 들어온 이슈"]);
    expect(rows.map((row) => /빠짐|이어짐|신규/.exec(row.textContent ?? "")?.[0])).toEqual(["빠짐", "이어짐", "신규"]);
    expect(within(rows[1]!).getByText("근거 2건 → 3건")).toBeTruthy();
    expect(within(rows[0]!).getByText(/이번 회차 핵심 이슈에는 없어요/)).toBeTruthy();
    expect(within(rows[2]!).getByText("보도 16:30")).toBeTruthy();
    // 제목이 겹치지 않으면 둘째 줄은 근거 수뿐이다.
    expect(within(rows[2]!).queryByText(/관련 기업|발생 시각/)).toBeNull();
    // 이 회차에 있는 이슈는 이 회차 그래프로, 빠진 이슈는 출근 회차 그래프로 이어진다.
    const to = (row: HTMLElement) => decodeURIComponent(within(row).getByRole("link").getAttribute("href") ?? "");
    expect(to(rows[2]!)).toContain("round=brf-2026-09-17-evening");
    expect(to(rows[0]!)).toContain("round=brf-2026-09-17-morning");
  });

  test("보도 시각이 날짜뿐이거나 없으면 0시로 그리지 않고, 제목이 같은 이슈는 이미 가진 구분 정보를 덧붙인다", async () => {
    await open(
      briefing({
        sinceMorning: {
          status: "available",
          morningRoundId: "brf-2026-09-17-morning",
          morningPublishedAt: "2026-09-16T22:41:30+00:00",
          morningDataAsOf: "2026-09-17T07:40:00+09:00",
          items: [
            item("a", "같은 제목 이슈", "dropped", { reportedAt: "2026-09-16T23:59:00+09:00", morningRank: 1, morningEvidenceCount: 1, companyNames: ["NVIDIA"] }),
            item("b", "같은 제목 이슈", "dropped", { reportedAt: "2026-09-17T00:00:48+09:00", morningRank: 2, morningEvidenceCount: 3, companyNames: ["NVIDIA"], eventTime: "2026-09-16", timePrecision: "day" }),
            item("c", "날짜만 아는 이슈", "new", { reportedAt: "2026-09-17", rank: 1, evidenceCount: 1 }),
            item("d", "보도 시각이 없는 이슈", "new", { reportedAt: null, rank: 2, evidenceCount: 1 }),
          ],
        },
      }),
    );
    const section = (await screen.findByText("아침 이후 바뀐 내용")).closest("section") as HTMLElement;
    const rows = within(section).getAllByRole("listitem");
    // 이전 날의 보도는 날짜가 앞서고 시각이 따로 보인다. 같은 날 0시 48초는 실제 시각이라 00:00으로 그대로 보인다.
    expect(within(rows[0]!).getByText("보도 9월 16일")).toBeTruthy();
    expect(within(rows[0]!).getByText("23:59")).toBeTruthy();
    expect(within(rows[1]!).getByText("보도 00:00")).toBeTruthy();
    // 날짜만 아는 값은 날짜만, 없는 값은 '보도 시각 미상'. 둘 다 시각을 지어내지 않는다.
    expect(within(rows[2]!).getByText("보도 9월 17일")).toBeTruthy();
    expect(within(rows[2]!).queryByText(/\d\d:\d\d/)).toBeNull();
    expect(within(rows[3]!).getByText("보도 시각 미상")).toBeTruthy();
    // 제목이 같은 두 이슈만 관련 기업·발생 시각을 덧붙인다(다른 이슈는 그대로).
    expect(within(rows[0]!).getByText(/관련 기업 NVIDIA · 발생 시각 미상 · 이번 회차 핵심 이슈에는 없어요 · 근거 1건/)).toBeTruthy();
    expect(within(rows[1]!).getByText(/관련 기업 NVIDIA · 발생 2026-09-16 · 이번 회차 핵심 이슈에는 없어요 · 근거 3건/)).toBeTruthy();
    expect(within(rows[2]!).queryByText(/관련 기업|발생/)).toBeNull();
  });

  test("비교할 출근 회차가 없으면 이유 한 줄만 보이고, 출근 회차에는 이 구역이 없다", async () => {
    await open(briefing({ sinceMorning: { status: "unavailable", reason: "같은 날 출근 브리핑이 없어요." } }));
    await screen.findByText("같은 날 출근 브리핑이 없어요.");
    expect(screen.queryByText("아침 이후 바뀐 내용")).toBeNull();
  });

  test("출근 회차에는 아침 이후 바뀐 내용이 없다", async () => {
    await open(briefing({ id: "brf-2026-09-17-morning", edition: "morning", sinceMorning: null }));
    await screen.findByText("주요 시장 지표");
    expect(screen.queryByText("아침 이후 바뀐 내용")).toBeNull();
  });

  test.each([
    ["not_ready", "발행 전"],
    ["generating", "생성 중"],
    ["failed", "발행 실패"],
    ["suspended", "제공 중단"],
  ] as const)("%s 회차는 머리에서 '%s'로 구분되고 지표를 그리지 않는다", async (status, label) => {
    await open(
      briefing({
        status,
        publishedAt: null,
        generatedAt: null,
        dataAsOf: null,
        marketVariables: { status: "unavailable", reason: "발행된 회차에서만 시장 지표를 볼 수 있어요." },
        notice: { kind: status === "failed" ? "failed" : status === "suspended" ? "suspended" : "not_ready", message: "회차 안내 문장", reason: null, at: null },
      }),
    );
    const round = await screen.findByRole("region", { name: "2026-09-17 퇴근 브리핑" });
    expect(within(round).getByText(label)).toBeTruthy();
    // 한 칸에는 한 상태만: 다른 상태 글자는 머리에 없다.
    for (const other of ["발행 전", "생성 중", "발행 실패", "제공 중단", "발행"].filter((text) => text !== label)) expect(within(round).queryByText(other)).toBeNull();
    await waitFor(() => expect(screen.getByText("회차 안내 문장")).toBeTruthy());
    expect(screen.queryByText("주요 시장 지표")).toBeNull();
  });
});
