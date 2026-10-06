// NFS002 응답과 화면 정합성 — 기업 상세.
// 이전 기업·이전 기간의 늦은 정상 응답과 오류 응답이, 지금 보는 기업·기간의 화면을 바꾸지 않는다.
// 화면은 읽는 값(readCompanyScreen)으로만 판정한다: 어느 기업·어느 기간의 값이 들어 있는가.
import { screen, waitFor } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { openApp } from "./support/app";
import { apiError, json, networkDown, type FakeBff, type Hold, type Reply } from "./support/fake-bff";
import { ALPHA, BETA, companyDetail, eventList, metricsOf, pricesOf, quoteOf, type TestCompany } from "./support/fixtures";
import { endpoint, eventsOf, pageOf, pricesInPeriod } from "./support/routes";
import { periodButton, readCompanyScreen, shown, traceOfCompany, traceOfPeriod } from "./support/screens";

/** 기업 c의 1개월 화면을 이루는 요청 다섯 개를 모두 서버에 닿기 전에 붙잡는다. */
function holdWholeScreen(bff: FakeBff, c: TestCompany) {
  return {
    company: bff.hold("GET", endpoint.company(c)),
    quote: bff.hold("GET", endpoint.quote(c)),
    metrics: bff.hold("GET", endpoint.metrics(c)),
    prices: bff.hold("GET", endpoint.prices(c), pricesInPeriod("1m")),
    events: bff.hold("GET", endpoint.events, eventsOf(c, "1m")),
  };
}
type WholeScreen = ReturnType<typeof holdWholeScreen>;

const arrived = (holds: Record<string, Hold>) => Promise.all(Object.values(holds).map((h) => h.arrived()));

/** 붙잡아 둔 기업 c의 응답을 정상 값으로 한꺼번에 푼다. */
function releaseWithData(h: WholeScreen, c: TestCompany) {
  h.company.respond(json(companyDetail(c)));
  h.quote.respond(json(quoteOf(c)));
  h.metrics.respond(json(metricsOf(c)));
  h.prices.respond(json(pricesOf(c, "1m")));
  h.events.respond(json(eventList(c.events["1m"])));
}

const temporaryFailure = (reasonCode = "temporary_failure") => ({ status: "unavailable", reasonCode, reason: "출처 일시 장애" });

/** 붙잡아 둔 응답을 영역마다 다른 종류의 오류로 한꺼번에 푼다: HTTP 5xx, 연결 끊김, 200 + 일시 장애 사유. */
function releaseWithErrors(h: WholeScreen, c: TestCompany) {
  h.company.respond(apiError(503, "bff_unreachable"));
  h.quote.respond(json({ ...temporaryFailure(), companyId: c.id }));
  h.metrics.respond(networkDown());
  h.prices.respond(json({ ...temporaryFailure(), companyId: c.id, period: "1m" }));
  h.events.respond(apiError(503, "bff_unreachable"));
}

describe("기업 A에서 B로 빠르게 바꿀 때", () => {
  test.each<[string, (h: WholeScreen) => void]>([
    ["정상 응답", (h) => releaseWithData(h, ALPHA)],
    ["오류 응답", (h) => releaseWithErrors(h, ALPHA)],
  ])("A의 %s이 B 화면 뒤에 도착해도 B의 개요·시세·지표·차트·사건이 그대로다", async (_, releaseAlpha) => {
    const { held, navigate, settle } = await openApp(pageOf(ALPHA), (bff) => holdWholeScreen(bff, ALPHA));
    await arrived(held);

    await navigate(pageOf(BETA));
    await waitFor(() => expect(readCompanyScreen()).toEqual(shown(BETA, "1m")));

    releaseAlpha(held);
    await settle();

    expect(readCompanyScreen()).toEqual(shown(BETA, "1m"));
    expect(traceOfCompany(ALPHA)).toEqual([]);
  });

  test("A를 다 본 뒤 B로 가면, B의 응답이 오기 전에 A의 값을 B 영역에 보이지 않는다", async () => {
    const { held, navigate, settle } = await openApp(pageOf(ALPHA), (b) => ({
      // B는 개요만 바로 오고, 시세·지표·차트·사건은 늦게 온다.
      quote: b.hold("GET", endpoint.quote(BETA)),
      metrics: b.hold("GET", endpoint.metrics(BETA)),
      prices: b.hold("GET", endpoint.prices(BETA), pricesInPeriod("1m")),
      events: b.hold("GET", endpoint.events, eventsOf(BETA, "1m")),
    }));
    await waitFor(() => expect(readCompanyScreen()).toEqual(shown(ALPHA, "1m")));

    await navigate(pageOf(BETA));
    await screen.findByRole("heading", { level: 1, name: BETA.name });
    await settle();

    expect(traceOfCompany(ALPHA)).toEqual([]);

    held.quote.respond(json(quoteOf(BETA)));
    held.metrics.respond(json(metricsOf(BETA)));
    held.prices.respond(json(pricesOf(BETA, "1m")));
    held.events.respond(json(eventList(BETA.events["1m"])));
    await waitFor(() => expect(readCompanyScreen()).toEqual(shown(BETA, "1m")));
    expect(traceOfCompany(ALPHA)).toEqual([]);
  });
});

describe("조회 기간을 1년에서 1일로 바꿀 때", () => {
  const holdYear = (bff: FakeBff) => ({
    prices: bff.hold("GET", endpoint.prices(ALPHA), pricesInPeriod("1y")),
    events: bff.hold("GET", endpoint.events, eventsOf(ALPHA, "1y")),
  });

  test.each<[string, Record<"prices" | "events", Reply>]>([
    ["정상 응답", { prices: json(pricesOf(ALPHA, "1y")), events: json(eventList(ALPHA.events["1y"])) }],
    ["오류 응답", { prices: json({ ...temporaryFailure(), companyId: ALPHA.id, period: "1y" }), events: apiError(503, "bff_unreachable") }],
  ])("1년 %s이 1일 화면 뒤에 도착해도 1일의 차트·사건만 남는다", async (_, late) => {
    const { held, user, settle } = await openApp(pageOf(ALPHA, "?period=1y"), holdYear);
    await arrived(held);

    await user.click(periodButton("1일"));
    await waitFor(() => expect(readCompanyScreen()).toEqual(shown(ALPHA, "1d")));

    held.prices.respond(late.prices);
    held.events.respond(late.events);
    await settle();

    expect(readCompanyScreen()).toEqual(shown(ALPHA, "1d"));
    expect(traceOfPeriod(ALPHA, "1y")).toEqual([]);
  });

  test("1년 화면을 다 본 뒤 1일로 바꾸면, 1일 응답이 오기 전에 1년의 차트·사건을 1일 화면에 보이지 않는다", async () => {
    const { held, user } = await openApp(pageOf(ALPHA, "?period=1y"), (bff) => ({
      prices: bff.hold("GET", endpoint.prices(ALPHA), pricesInPeriod("1d")),
      events: bff.hold("GET", endpoint.events, eventsOf(ALPHA, "1d")),
    }));
    await waitFor(() => expect(readCompanyScreen()).toEqual(shown(ALPHA, "1y")));

    await user.click(periodButton("1일"));
    await arrived(held);

    expect(traceOfPeriod(ALPHA, "1y")).toEqual([]);

    held.prices.respond(json(pricesOf(ALPHA, "1d")));
    held.events.respond(json(eventList(ALPHA.events["1d"])));
    await waitFor(() => expect(readCompanyScreen()).toEqual(shown(ALPHA, "1d")));
  });
});
