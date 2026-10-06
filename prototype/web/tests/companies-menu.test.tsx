import type { Schemas } from "@/api/client";
import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { openApp } from "./support/app";
import { apiError, json } from "./support/fake-bff";
import { ALPHA, BETA, metadata } from "./support/fixtures";
import { endpoint } from "./support/routes";

describe("종목 메뉴 (FS037)", () => {
  test("지도와 종목은 별도 메뉴이고 옛 목록 주소를 옮긴다", async () => {
    await openApp("/?mode=all&view=list");
    await screen.findByRole("heading", { name: "종목", level: 1 });
    expect(window.location.pathname).toBe("/companies");
    expect(window.location.search).not.toContain("view=");
    expect(screen.queryByRole("radio", { name: "목록으로 보기" })).toBeNull();
    const menu = screen.getByRole("navigation", { name: "주요 메뉴" });
    expect(within(menu).getAllByRole("link").map((link) => link.textContent)).toEqual(["지도", "종목", "브리핑", "내 종목"]);
  });

  test("검색 버튼으로 실행하고 현재 검색 결과에서 기업 상세로 진입한다", async () => {
    const { user, bff } = await openApp("/companies");
    await screen.findByRole("link", { name: `${ALPHA.name} 기업 상세` });
    const input = screen.getByRole("searchbox", { name: "기업명·영문명·티커 검색" });
    await user.type(input, BETA.ticker);
    expect(bff.calls("GET", "/api/companies", (r) => r.query.get("q") === BETA.ticker)).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "검색" }));
    await waitFor(() => expect(screen.queryByRole("link", { name: `${ALPHA.name} 기업 상세` })).toBeNull());
    expect(screen.getByRole("link", { name: `${BETA.name} 기업 상세` }).getAttribute("href")).toBe(`/companies/${encodeURIComponent(BETA.id)}`);
  });

  test("회원 관심 토글은 저장 성공 후 상태를 반영한다", async () => {
    const { user, bff } = await openApp("/companies", (b, world) => {
      b.on("PUT", "/api/me/watchlist/:id", (request, { id }) => {
        const body = request.body;
        if (!body || typeof body !== "object" || !("watched" in body) || typeof body.watched !== "boolean") throw new Error("관심 토글 요청 형식");
        const watched = body.watched;
        world.settings = { ...world.settings, watchlistIds: watched ? [...world.settings.watchlistIds, id!] : world.settings.watchlistIds.filter((value) => value !== id), version: world.settings.version + 1 };
        return json(world.settings);
      });
    });
    const toggle = await screen.findByRole("button", { name: `${BETA.name} 관심 종목` });
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    await user.click(toggle);
    await waitFor(() => expect(toggle.getAttribute("aria-pressed")).toBe("true"));
    expect(bff.calls("PUT", `/api/me/watchlist/${encodeURIComponent(BETA.id)}`)).toHaveLength(1);
  });

  test("비회원은 목록·상세 링크를 읽고 관심 등록은 로그인 안내를 받는다", async () => {
    await openApp("/companies", (_, world) => { world.session = { authenticated: true, kind: "guest", user: null, setup: null, metadata }; });
    expect(await screen.findByRole("link", { name: `${ALPHA.name} 기업 상세` })).toBeTruthy();
    expect(screen.getByRole("link", { name: `${ALPHA.name}: 로그인하고 관심 종목에 담기` })).toBeTruthy();
  });
});

describe("기업 패널 독립 요약 (FS020)", () => {
  test("기업 맥락의 문서 판정은 뉴스와 해당 사건에 표시하고 null은 숨긴다", async () => {
    const event = ALPHA.events["1m"][0]!;
    const judged: Schemas["CompanyDocument"] = {
      id: "test-judged-document", title: "시험용 긍정 문서", publisher: "시험 출처", url: null,
      publishedAt: "2026-09-20T10:00:00+09:00", synthetic: true, quotes: [],
      events: [{ eventId: event.id, title: event.title, relationType: "REPORTS" }],
      sentiment: { label: "positive", companyId: ALPHA.id, rationale: "시험용 사업 계약의 긍정적 내용이에요.", quotes: [], judgedAt: "2026-10-06T09:00:00+09:00", model: "fixed-test", promptVersion: "test" },
    };
    await openApp(`/?mode=all&select=node:${encodeURIComponent(ALPHA.id)}`, (b) => b.on("GET", endpoint.documents(ALPHA), json({ items: [judged, { ...judged, id: "test-null-document", title: "시험용 판정 없는 문서", sentiment: null }], metadata })));
    const news = await screen.findByRole("region", { name: "뉴스·공시" });
    expect(await within(news).findByText("긍정", { exact: true })).toBeTruthy();
    const issues = screen.getByRole("region", { name: "직접 이슈" });
    expect(within(issues).getAllByText("긍정", { exact: true }).length).toBeGreaterThan(0);
    expect(within(news).getAllByText("긍정", { exact: true })).toHaveLength(1);
    expect(within(news).getByText("시험용 판정 없는 문서")).toBeTruthy();
  });

  test("패널의 기준 시점으로 상세에 이동하면 기업·시세·지표·가격·문서를 재요청하지 않는다", async () => {
    const { user, bff, settle } = await openApp(`/?mode=all&select=node:${encodeURIComponent(ALPHA.id)}`);
    await screen.findByText("최근 1개월 시세 추이");
    await settle();
    const paths = [endpoint.company(ALPHA), endpoint.quote(ALPHA), endpoint.metrics(ALPHA), endpoint.prices(ALPHA), endpoint.documents(ALPHA)];
    const opened = paths.flatMap((path) => bff.calls("GET", path).map((request) => ({ path, query: request.query.toString() })));
    await user.click(screen.getByRole("link", { name: "기업 상세" }));
    await screen.findByRole("heading", { name: ALPHA.name, level: 1 });
    await settle();
    expect(new URLSearchParams(window.location.search).get("asOf")).toBeTruthy();
    // 새 기간 지원 여부 조회(1d/1w)와 스위처의 최신 기업 이름 조회는 다른 키다.
    // 패널이 이미 받은 동일 기간·시점의 요청만 상세에서 재사용하는지 확인한다.
    for (const { path, query } of opened) expect(bff.calls("GET", path, (request) => request.query.toString() === query), `${path}?${query}`).toHaveLength(1);
  });

  test("시세 실패에도 기업·이슈·보유·차트는 유지하고 같은 조회를 중복하지 않는다", async () => {
    const { bff, settle } = await openApp(`/?mode=all&select=node:${encodeURIComponent(ALPHA.id)}`, (b) => b.on("GET", endpoint.quote(ALPHA), apiError(404, "quote_unavailable", "시세를 불러오지 못했어요")));
    await screen.findByText("시세를 불러오지 못했어요", { exact: true });
    await settle();
    expect(screen.getByRole("region", { name: "기업 기본 정보" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "직접 이슈" })).toBeTruthy();
    expect(screen.getByText("가상 계좌 보유")).toBeTruthy();
    expect(screen.getByText("최근 1개월 시세 추이")).toBeTruthy();
    for (const path of [endpoint.company(ALPHA), endpoint.quote(ALPHA), endpoint.metrics(ALPHA), endpoint.prices(ALPHA), endpoint.documents(ALPHA)]) expect(bff.calls("GET", path)).toHaveLength(1);
  });
});
