import { describe, expect, test } from "vitest";
import { companySwitchUrl, detailRange, eventBucket, exchangeZone, groupEvents, parseAsOf, parsePeriod, periodFrom } from "@/lib/company-timeline";
import { eventList } from "./support/fixtures";

const issue = (id: string, time: string, precision: "day" | "datetime" = "datetime") => ({
  ...eventList([{ id, title: id, eventTime: time }]).items[0]!, timePrecision: precision,
});

describe("기업 상세 시간 버킷", () => {
  test("5분·시간·일·ISO 주로 묶으며 문서 수와 무관하게 사건 수를 센다", () => {
    const events = [issue("a", "2026-10-06T10:02:00+09:00"), issue("b", "2026-10-06T10:04:00+09:00"), issue("c", "2026-10-06T10:06:00+09:00")];
    expect(groupEvents(events, [], "1d").map(g => g.items.length)).toEqual([2, 1]);
    expect(groupEvents(events, [], "1w")[0]?.items.length).toBe(3);
    expect(eventBucket(events[0]!, "1m")?.key).toBe("2026-10-06");
    expect(eventBucket(events[0]!, "1y")?.key).toBe("2026-10-05");
    expect(groupEvents([...events, issue("d", "2026-10-04", "day")], [], "1y").map(g => g.items.length)).toEqual([3, 1]);
  });
  test("일자만 아는 사건에는 임의 시각을 만들지 않는다", () => {
    expect(eventBucket(issue("a", "2026-10-06", "day"), "1d")?.key).toBe("2026-10-06");
    expect(groupEvents([], [{ ...issue("unknown", "2026", "day"), timePrecision: "year" }], "1w")[0]?.unknown).toBe(true);
  });
  test("1주는 7일 범위이며 1개월 말일을 보정한다", () => {
    expect(periodFrom("1w", "2026-10-06")).toBe("2026-09-29");
    expect(periodFrom("1m", "2026-03-31")).toBe("2026-02-28");
    expect(parsePeriod("1w")).toBe("1w");
  });
  test("거래소의 당일 경계와 기준 시점을 사용한다", () => {
    const now = new Date("2026-10-06T02:00:00Z");
    const range = detailRange("1d", now, exchangeZone("NASDAQ:NVDA"));
    expect(range.today).toBe("2026-10-05");
    expect(range.from).toBe("2026-10-05T00:00:00-04:00");
    expect(range.to).toBe(now.toISOString());
    expect(parseAsOf(range.to)?.toISOString()).toBe(range.to);
    expect(parseAsOf("yesterday")).toBeNull();
  });
  test("기업 전환은 기간·시점·탭을 유지하고 기업별 선택만 해제한다", () => {
    const params = new URLSearchParams("period=1w&asOf=2026-10-06T02%3A00%3A00Z&tab=documents&issue=old&bucket=old&open=old");
    const url = new URL(companySwitchUrl("KRX:005930", params), "http://localhost");
    expect(url.pathname).toBe("/companies/KRX%3A005930");
    expect(url.searchParams.get("period")).toBe("1w");
    expect(url.searchParams.get("tab")).toBe("documents");
    expect(url.searchParams.get("asOf")).toBe("2026-10-06T02:00:00Z");
    expect(url.searchParams.has("issue")).toBe(false);
    expect(url.searchParams.has("bucket")).toBe(false);
  });
});
