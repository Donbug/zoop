// FS007 로그아웃 — 로그아웃 뒤에 늦게 도착한 이전 회원의 개인 응답(보유·설정)은 어떤 화면에도 나타나지 않는다.
// "이전 회원의 정보"는 이름·보유 종목·관심 종목이다. 서버의 대화 기록을 지우는 요청은 보내지 않는다.
import { screen, waitFor } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { openApp } from "./support/app";
import { json } from "./support/fake-bff";
import { ALPHA, BETA, holdingsPortfolio, MEMBER_NAME, memberSession, OTHER_MEMBER_NAME, watchSettings } from "./support/fixtures";
import { exposedIn, logIn, logOut } from "./support/screens";

/** 이전 회원(알파전자 보유·관심, 시험회원)의 흔적 */
const PREVIOUS_MEMBER = [MEMBER_NAME, ALPHA.name];

const pathname = () => window.location.pathname;
const requestLine = (r: { method: string; path: string }) => `${r.method} ${r.path}`;

describe("로그아웃과 이전 회원의 늦은 응답", () => {
  test("서버가 로그아웃을 처리하는 동안과 그 뒤, 늦게 온 이전 회원의 보유·관심 종목이 화면에 나타나지 않는다", async () => {
    const { bff, held, user, settle } = await openApp("/me/stocks", (b) => ({
      portfolio: b.hold("GET", "/api/portfolio"),
      settings: b.hold("GET", "/api/me/settings"),
      logout: b.holdResponse("POST", "/api/auth/logout"),
    }));
    await Promise.all([held.portfolio.arrived(), held.settings.arrived()]);

    await logOut(user);
    await waitFor(() => expect(pathname()).toBe("/login"));
    expect(exposedIn(PREVIOUS_MEMBER)).toEqual([]);

    // 서버가 로그아웃을 아직 처리하는 중에 이전 회원의 응답이 도착한다.
    held.portfolio.respond(json(holdingsPortfolio(ALPHA)));
    held.settings.respond(json(watchSettings([ALPHA.id])));
    await settle();
    expect(exposedIn(PREVIOUS_MEMBER)).toEqual([]);

    held.logout.respond();
    await settle();
    expect(pathname()).toBe("/login");
    expect(exposedIn(PREVIOUS_MEMBER)).toEqual([]);

    // 보호된 화면으로 돌아가려 해도 이전 회원의 정보가 아니라 로그인 화면이다.
    window.history.pushState(null, "", "/me/stocks");
    window.dispatchEvent(new PopStateEvent("popstate", { state: null }));
    await settle();
    expect(pathname()).toBe("/login");
    expect(exposedIn(PREVIOUS_MEMBER)).toEqual([]);

    // 로그아웃은 화면을 거두는 일이다. 서버의 개인 기록(대화 등)을 지우는 요청은 없다.
    expect(bff.writes.map(requestLine)).toEqual(["POST /api/auth/logout"]);
  });

  test("다른 회원이 이어서 로그인한 뒤 이전 회원의 보유 응답이 도착해도, 새 회원의 보유·관심 종목만 보인다", async () => {
    const { held, user, world, navigate, settle } = await openApp("/me/stocks", (b) => b.hold("GET", "/api/portfolio"));
    await held.arrived();
    await logOut(user);
    await waitFor(() => expect(pathname()).toBe("/login"));
    // 주소만 바뀐 순간에는 로그아웃의 세션 재조회·가드 이동이 아직 남을 수 있다.
    // 이전 개인 응답은 계속 붙잡되, 로그아웃 처리가 끝난 로그인 화면에서 다음 회원으로 들어간다.
    await settle();
    await screen.findByRole("button", { name: "로그인" });

    world.nextLogin = memberSession({ id: "member-2", displayName: OTHER_MEMBER_NAME });
    world.portfolio = holdingsPortfolio(BETA);
    world.settings = watchSettings([BETA.id]);
    await settle();
    await logIn(user);
    await navigate("/me/stocks");
    await waitFor(() => expect(screen.queryAllByText(BETA.name).length).toBeGreaterThan(1));

    held.respond(json(holdingsPortfolio(ALPHA)));
    await settle();

    expect(exposedIn(PREVIOUS_MEMBER)).toEqual([]);
    expect(exposedIn([BETA.name, OTHER_MEMBER_NAME])).toEqual([BETA.name, OTHER_MEMBER_NAME]);
  });

  test("관심 종목을 저장하던 중 로그아웃하면, 늦게 온 저장 응답이 다음 회원의 관심 종목을 덮지 않는다", async () => {
    const { bff, held: save, user, world, navigate, settle } = await openApp("/me/stocks", (b) => b.hold("PUT", "/api/me/settings"));
    const removeAlpha = await screen.findByRole("button", { name: `${ALPHA.name} 관심 종목 목록에서 빼기` });

    // 이전 회원이 관심 종목에서 알파전자를 빼고 저장한다. 서버 응답은 늦다.
    await user.click(removeAlpha);
    await user.click(screen.getByRole("button", { name: "저장" }));
    await save.arrived();

    await logOut(user);
    await waitFor(() => expect(pathname()).toBe("/login"));
    // 저장 응답을 풀지 않고 로그아웃·로그인 화면 전환만 완료한다.
    await settle();
    await screen.findByRole("button", { name: "로그인" });
    world.nextLogin = memberSession({ id: "member-2", displayName: OTHER_MEMBER_NAME });
    world.portfolio = holdingsPortfolio(BETA);
    world.settings = watchSettings([BETA.id]);
    await settle();
    await logIn(user);
    await navigate("/me/stocks");
    await waitFor(() => expect(screen.queryAllByText(BETA.name).length).toBeGreaterThan(1));

    save.respond(json({ ...watchSettings([]), version: 2 }));
    await settle();

    expect(screen.queryAllByText(BETA.name).length).toBeGreaterThan(1);
    expect(exposedIn(PREVIOUS_MEMBER)).toEqual([]);
    expect(bff.calls("PUT", "/api/me/settings")).toHaveLength(1);
  });
});
