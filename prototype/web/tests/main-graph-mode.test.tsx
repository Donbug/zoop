// FS017 지도 조회 실패 · FS019 모드 전환 — 전환 응답이 실패하거나 늦게(순서가 뒤바뀌어) 와도 지금 보이는 지도·모드·선택은 그대로다.
// 캔버스는 노드를 버튼으로 내보내는 대역이라, "지도에 어떤 노드가 있는가"로 어느 모드의 지도인지 판정한다.
import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { openApp } from "./support/app";
import { apiError, json, type Where } from "./support/fake-bff";
import { ALPHA, BETA, graphOf } from "./support/fixtures";
import { alertTitled, modeButton, readMap, retryIn } from "./support/screens";
import { sleep } from "./support/time";

const ISSUE = ALPHA.events["1m"][0]!.title;
const PERSONAL_MAP = { title: "내 종목 지도", mode: "내 종목", nodes: [ALPHA.name, ISSUE], alerts: [] };
const MARKET_MAP = { title: "시장 전체 지도", mode: "시장 전체", nodes: [ALPHA.name, BETA.name, ISSUE], alerts: [] };

const requestsFor =
  (mode: "all" | "personal"): Where =>
  (r) =>
    r.query.get("mode") === mode;

const searchParam = (name: string) => new URLSearchParams(window.location.search).get(name);

describe("모드 전환 (FS019)", () => {
  test("대상 모드 조회가 실패하면 지금 모드의 지도와 모드 표시를 그대로 두고, 다시 시도가 성공하면 그때 바꾼다", async () => {
    const { user, held: heal } = await openApp("/?mode=personal", (b) => b.on("GET", "/api/graph", apiError(503, "bff_unreachable"), requestsFor("all")));
    await waitFor(() => expect(readMap()).toEqual(PERSONAL_MAP));

    await user.click(modeButton("시장 전체"));
    await waitFor(() => expect(readMap().alerts).toHaveLength(1));

    expect(readMap()).toEqual({ ...PERSONAL_MAP, alerts: [expect.stringContaining("시장 전체 지도를 불러오지 못했어요")] });
    expect(searchParam("mode")).toBe("personal");

    heal();
    await user.click(retryIn(screen.getByRole("alert")));
    await waitFor(() => expect(readMap()).toEqual(MARKET_MAP));
    expect(searchParam("mode")).toBe("all");
  });

  test.each([
    ["정상 응답", false],
    ["오류 응답", true],
  ])("내 종목으로 되돌아온 뒤 늦게 도착한 시장 전체 %s은 지도·모드를 바꾸지 않는다", async (_, fails) => {
    const { user, held, settle } = await openApp("/?mode=personal", (b) => {
      // 오류 응답은 앱이 한 번 더 시도한 뒤에도 같은 서버 장애여야 최종 실패가 된다.
      if (fails) b.on("GET", "/api/graph", apiError(503, "bff_unreachable"), requestsFor("all"));
      return b.hold("GET", "/api/graph", requestsFor("all"));
    });
    await waitFor(() => expect(readMap()).toEqual(PERSONAL_MAP));

    await user.click(modeButton("시장 전체"));
    await held.arrived();
    await user.click(modeButton("내 종목"));

    held.respond(fails ? apiError(503, "bff_unreachable") : json(graphOf("all")));
    if (fails) await sleep(1300);
    await settle();

    expect(readMap()).toEqual(PERSONAL_MAP);
    expect(searchParam("mode")).toBe("personal");
  });
});

describe("지도 조회 실패 (FS017)", () => {
  test("처음 조회가 실패하면 오류와 다시 시도를 보이되 모드 전환은 막지 않고, 다시 시도가 성공하면 지도가 뜬다", async () => {
    const { user, held: heal } = await openApp("/?mode=all", (b) => b.on("GET", "/api/graph", apiError(503, "bff_unreachable")));
    await waitFor(() => expect(alertTitled("지도를 불러오지 못했어요")).not.toBeNull());
    expect(readMap().nodes).toEqual([]);
    expect(screen.getByRole("radio", { name: "내 종목" })).toBeTruthy();

    heal();
    await user.click(retryIn(alertTitled("지도를 불러오지 못했어요")!));
    await waitFor(() => expect(readMap()).toEqual(MARKET_MAP));
  });

  test("이미 보이는 지도가 있으면, 다른 주소의 지도 조회가 실패해도 보던 지도를 그대로 두고 다시 시도로 이어 간다", async () => {
    const { user, navigate, held: heal } = await openApp("/?mode=all", (b) => b.on("GET", "/api/graph", apiError(503, "bff_unreachable"), requestsFor("personal")));
    await waitFor(() => expect(readMap()).toEqual(MARKET_MAP));

    await navigate("/?mode=personal");
    await waitFor(() => expect(readMap().alerts).toHaveLength(1));

    expect(readMap()).toEqual({ ...MARKET_MAP, alerts: [expect.stringContaining("이전에 보던 시장 전체 지도")] });
    expect(within(screen.getByRole("alert")).getByRole("button", { name: "다시 시도" })).toBeTruthy();

    heal();
    await user.click(retryIn(screen.getByRole("alert")));
    await waitFor(() => expect(readMap()).toEqual(PERSONAL_MAP));
  });
});
