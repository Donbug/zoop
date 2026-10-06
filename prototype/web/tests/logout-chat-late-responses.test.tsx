// FS007 × AI 질문 — A 회원이 질문을 보내는 중에 로그아웃하고 B 회원이 로그인한 뒤, A의 대화 생성·질문 접수 응답이 늦게 도착해도
// B의 질문 창에는 A의 질문·답변이 보이지 않고, 그 응답을 이어받아 A의 대화·작업으로 요청을 보내지 않는다.
import { waitFor } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { openApp } from "./support/app";
import { ChatServer } from "./support/chat-server";
import { json, networkDown } from "./support/fake-bff";
import { ALPHA, disconnectedPortfolio, memberSession, OTHER_MEMBER_NAME, watchSettings } from "./support/fixtures";
import { pageOf } from "./support/routes";
import { askQuestion, chatText, logIn, logOut, openChat, showsEmptyConversation } from "./support/screens";

const EVENT_PAGE = pageOf(ALPHA, "?issue=ev-alpha-1m");
const QUESTION = "이 사건은 언제 알려졌나요?";
const ANSWER = "서버가 저장한 답변";

describe("질문을 보내던 회원이 로그아웃하고 다른 회원이 로그인했을 때", () => {
  test.each([
    ["대화 생성(PUT) 응답이 늦게 도착해도", "PUT", "/api/chat/sessions/:id", false],
    ["질문 접수(POST) 응답이 끝내 오지 않아 작업 상태를 확인하려 해도", "POST", "/api/chat/sessions/:sid/jobs", true],
  ] as const)("이전 회원의 %s 새 회원의 질문 창과 요청에 섞이지 않는다", async (_, method, path, lost) => {
    const chat = new ChatServer({ [ALPHA.id]: ALPHA.name });
    chat.answerNow = () => ANSWER;
    const { bff, held: late, user, world, navigate, settle } = await openApp(EVENT_PAGE, (b) => {
      chat.serve(b);
      // 두 회원 모두 이전 대화가 없다.
      b.on("GET", "/api/chat/sessions/current", json({ conversation: null }));
      return b.holdResponse(method, path);
    });
    await openChat(user);
    await askQuestion(user, QUESTION);
    await late.arrived();
    const [previousSession] = chat.sessions.keys();

    // 이전 회원이 창을 닫고 로그아웃한다. 서버는 질문을 처리했지만 응답은 아직 오지 않았다.
    await user.keyboard("{Escape}");
    await logOut(user);
    await waitFor(() => expect(window.location.pathname).toBe("/login"));

    world.nextLogin = memberSession({ id: "member-2", displayName: OTHER_MEMBER_NAME });
    world.portfolio = disconnectedPortfolio();
    world.settings = watchSettings([]);
    await navigate(EVENT_PAGE);
    await logIn(user);
    await openChat(user);
    const before = bff.requests.length;

    late.respond(lost ? networkDown() : undefined);
    await settle();

    expect(showsEmptyConversation()).toBe(true);
    expect(chatText()).not.toContain(QUESTION);
    expect(chatText()).not.toContain(ANSWER);
    // 새 회원의 화면이 이전 회원의 대화·작업으로 쓰기·조회 요청을 보내지 않는다.
    const after = bff.requests.slice(before);
    expect(after.filter((r) => r.method !== "GET")).toEqual([]);
    const previousIds = [previousSession!, ...chat.jobs.keys()];
    expect(after.filter((r) => previousIds.some((id) => r.path.includes(id)))).toEqual([]);
  });
});
