// NFS004 부분 실패 내성.
// 한 영역의 조회가 실패해도 나머지 영역과 편집 중인 입력은 그대로이고, [다시 시도]는 그 영역의 조회만 다시 보내며
// 저장(PUT)·AI 작업 같은 쓰기 요청을 되풀이하지 않는다.
import { act, screen, waitFor, within } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";
import { describe, expect, test } from "vitest";
import { openApp } from "./support/app";
import { apiError, json, networkDown, type FakeBff, type Reply, type Where } from "./support/fake-bff";
import { ALPHA, BETA, disconnectedPortfolio, metricsOf } from "./support/fixtures";
import { endpoint, eventsOf, pageOf } from "./support/routes";
import { alertTitled, errorTitle, readCompanyScreen, retryIn, shown, traceOfCompany, type CompanyScreen } from "./support/screens";
import { sleep } from "./support/time";

interface Region {
  name: string;
  /** 이 영역이 화면에 내는 값 */
  shows: Exclude<keyof CompanyScreen, "alerts">;
  path: string;
  where?: Where;
  title: string;
  failure: Reply;
}

const temporaryFailure = (extra: object) => json({ status: "unavailable", reasonCode: "temporary_failure", reason: "출처 일시 장애", ...extra });

const regions: Region[] = [
  { name: "기업 개요(503)", shows: "name", path: endpoint.company(ALPHA), title: errorTitle.overview, failure: apiError(503, "bff_unreachable") },
  { name: "시세(503)", shows: "quote", path: endpoint.quote(ALPHA), title: errorTitle.quote, failure: apiError(503, "bff_unreachable") },
  { name: "시세(200 + 출처 일시 장애)", shows: "quote", path: endpoint.quote(ALPHA), title: errorTitle.quote, failure: temporaryFailure({ companyId: ALPHA.id }) },
  { name: "주요 지표(연결 끊김)", shows: "metrics", path: endpoint.metrics(ALPHA), title: errorTitle.metrics, failure: networkDown() },
  { name: "주가 차트(503)", shows: "chart", path: endpoint.prices(ALPHA), title: errorTitle.chart, failure: apiError(503, "bff_unreachable") },
  { name: "사건 목록(503)", shows: "events", path: endpoint.events, where: eventsOf(ALPHA, "1m"), title: errorTitle.events, failure: apiError(503, "bff_unreachable") },
  { name: "가상 계좌 보유(503)", shows: "holding", path: "/api/portfolio", title: errorTitle.holding, failure: apiError(503, "bff_unreachable") },
];

describe("기업 상세에서 한 영역만 실패할 때", () => {
  test.each(regions)("$name: 나머지 영역은 그대로이고, 다시 시도는 그 영역의 조회만 보낸다", async (region) => {
    const { bff, held: heal, user } = await openApp(pageOf(ALPHA), (b) => b.on("GET", region.path, region.failure, region.where));

    await waitFor(() => expect(alertTitled(region.title)).not.toBeNull());
    const { alerts, ...view } = readCompanyScreen();
    const { alerts: _expectedAlerts, ...expected } = shown(ALPHA, "1m");
    // 실패한 영역을 뺀 모든 영역이 정상 화면과 같다. 실패한 영역에는 값 대신 오류 안내가 있다.
    expect({ ...view, [region.shows]: null }).toEqual({ ...expected, [region.shows]: null });
    expect(view[region.shows]).not.toEqual(expected[region.shows]);
    expect(alerts).toHaveLength(1);

    heal();
    const before = bff.requests.length;
    await user.click(retryIn(alertTitled(region.title)!));
    await waitFor(() => expect(readCompanyScreen()).toEqual(shown(ALPHA, "1m")));

    const resent = bff.requests.slice(before);
    expect(resent.length).toBeGreaterThan(0);
    expect(resent.map((r) => r.path)).toEqual(resent.map(() => region.path));
    expect(bff.writes).toEqual([]);
  });

  test.each<[string, Reply]>([
    ["정상 응답", json(metricsOf(ALPHA))],
    ["오류 응답", apiError(503, "bff_unreachable")],
  ])("다시 시도하는 동안 다른 기업으로 바꾸면, 이전 기업의 다시 시도 %s이 새 화면에 반영되지 않는다", async (_, late) => {
    const { bff, held: heal, user, navigate, settle } = await openApp(pageOf(ALPHA), (b) => b.on("GET", endpoint.metrics(ALPHA), networkDown()));
    await waitFor(() => expect(alertTitled(errorTitle.metrics)).not.toBeNull());

    heal();
    const retry = bff.hold("GET", endpoint.metrics(ALPHA));
    await user.click(retryIn(alertTitled(errorTitle.metrics)!));
    await retry.arrived();

    await navigate(pageOf(BETA));
    await waitFor(() => expect(readCompanyScreen()).toEqual(shown(BETA, "1m")));

    retry.respond(late);
    await settle();

    expect(readCompanyScreen()).toEqual(shown(BETA, "1m"));
    expect(traceOfCompany(ALPHA)).toEqual([]);
  });

  test("문서 탭의 조회만 실패하면 사건 탭은 그대로이고, 문서 탭에서 다시 시도하면 문서 조회만 다시 보낸다", async () => {
    const { bff, held: heal, user } = await openApp(pageOf(ALPHA), (b) => b.on("GET", endpoint.documents(ALPHA), apiError(503, "bff_unreachable")));
    await waitFor(() => expect(readCompanyScreen()).toEqual(shown(ALPHA, "1m")));

    await user.click(screen.getByRole("tab", { name: "문서" }));
    await waitFor(() => expect(alertTitled(errorTitle.documents)).not.toBeNull());

    heal();
    const before = bff.requests.length;
    await user.click(retryIn(alertTitled(errorTitle.documents)!));
    await waitFor(() => expect(alertTitled(errorTitle.documents)).toBeNull());

    expect(bff.requests.slice(before).map((r) => r.path)).toEqual([endpoint.documents(ALPHA)]);
    expect(bff.writes).toEqual([]);
  });
});

describe("내 종목에서 보유 종목 조회가 실패할 때", () => {
  const failPortfolio = (b: FakeBff) => b.on("GET", "/api/portfolio", apiError(503, "bff_unreachable"));

  const addBeta = async (user: UserEvent) => {
    const box = within(screen.getByRole("search", { name: "관심 종목 추가" })).getByRole("searchbox");
    await user.type(box, "베타{Enter}");
    await user.click(await screen.findByRole("button", { name: new RegExp(BETA.name) }));
  };

  test("편집 중인 관심 종목 목록은 보유 영역의 실패·다시 시도에도 그대로이고, 저장은 다시 실행되지 않는다", async () => {
    const { bff, held: heal, user, world } = await openApp("/me/stocks", (b, w) => {
      w.portfolio = disconnectedPortfolio();
      return failPortfolio(b);
    });
    await waitFor(() => expect(alertTitled(errorTitle.portfolio)).not.toBeNull());

    await addBeta(user);
    expect(screen.getByText(/저장하지 않은 변경/).textContent).toContain("추가 1개");

    heal();
    await user.click(retryIn(alertTitled(errorTitle.portfolio)!));
    await screen.findByText(/연결된 가상 계좌가 없어요/);

    expect(screen.getByText(/저장하지 않은 변경/).textContent).toContain("추가 1개");
    expect(bff.writes).toEqual([]);

    await user.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(world.settings.watchlistIds).toEqual([ALPHA.id, BETA.id]));
    expect(bff.calls("PUT", "/api/me/settings")).toHaveLength(1);
  });

  test("관심 종목 저장에 성공한 뒤 보유 영역을 다시 시도해도 저장 요청은 한 번뿐이다", async () => {
    const { bff, held: heal, user } = await openApp("/me/stocks", (b, w) => {
      w.portfolio = disconnectedPortfolio();
      return failPortfolio(b);
    });
    await waitFor(() => expect(alertTitled(errorTitle.portfolio)).not.toBeNull());
    await addBeta(user);
    await user.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(bff.calls("PUT", "/api/me/settings")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByText(/저장하지 않은 변경/)).toBeNull());

    heal();
    await user.click(retryIn(alertTitled(errorTitle.portfolio)!));
    await screen.findByText(/연결된 가상 계좌가 없어요/);

    expect(bff.calls("PUT", "/api/me/settings")).toHaveLength(1);
    expect(bff.writes.map((r) => `${r.method} ${r.path}`)).toEqual(["PUT /api/me/settings"]);
  });

  test("저장이 실패해도 저절로 다시 보내지 않고 편집 내용을 지키며, 사용자가 [다시 저장]을 눌러야 다시 보낸다", async () => {
    const { bff, held: heal, user, world } = await openApp("/me/stocks", (b, w) => {
      w.portfolio = disconnectedPortfolio();
      return b.on("PUT", "/api/me/settings", apiError(503, "bff_unreachable"));
    });
    await screen.findByText(/연결된 가상 계좌가 없어요/);
    await addBeta(user);
    await user.click(screen.getByRole("button", { name: "저장" }));
    const again = await screen.findByRole("button", { name: "다시 저장" });

    // 조회 재시도가 시작되는 1초(앱의 일시 장애 재시도 간격)를 넘겨도 저장은 한 번만 나갔다.
    await act(async () => {
      await sleep(1300);
    });
    expect(bff.calls("PUT", "/api/me/settings")).toHaveLength(1);
    expect(screen.getByText(/저장하지 않은 변경/).textContent).toContain("추가 1개");

    heal();
    await user.click(again);
    await waitFor(() => expect(world.settings.watchlistIds).toEqual([ALPHA.id, BETA.id]));
    expect(bff.calls("PUT", "/api/me/settings")).toHaveLength(2);
  });
});
