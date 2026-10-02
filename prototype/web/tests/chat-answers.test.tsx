// AI 질문 — NFS002(답변은 요청한 대화·질문에만 붙는다)와 FS053(응답을 못 받아도 새 작업을 만들지 않고 회수한다).
// 서버(ChatServer)가 대화·작업의 원본이고, 시험은 응답이 늦거나 사라지는 상황만 만든다.
import { waitFor, within } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { openApp } from "./support/app";
import { ChatServer } from "./support/chat-server";
import { apiError, json, networkDown, type FakeBff, type Handler } from "./support/fake-bff";
import { ALPHA } from "./support/fixtures";
import { pageOf } from "./support/routes";
import { askQuestion, chatDialog, chatText, openChat, showsEmptyConversation, startNewConversation } from "./support/screens";
import type { Schemas } from "@/api/client";

const SUBMIT = "/api/chat/sessions/:sid/jobs";
const JOB = "/api/chat/jobs/:id";
const EVENT_PAGE = pageOf(ALPHA, "?event=ev-alpha-1m");

const Q1 = "이 사건은 언제 알려졌나요?";
const Q2 = "함께 언급된 기업은 어디인가요?";
const answerTo = (question: string) => `서버가 저장한 답변: ${question}`;

/** 서버는 접수한 질문에 바로 답변을 저장한다. 답변을 늦추려면 `answerNow`를 끈다. */
function newChatServer() {
  const chat = new ChatServer({ [ALPHA.id]: ALPHA.name });
  chat.answerNow = answerTo;
  return chat;
}

/** 질문 접수 요청을 서버가 처리하지만 응답은 연결이 끊겨 클라이언트에 닿지 않는다. */
const lostResponse =
  (chat: ChatServer): Handler =>
  (request, { sid }) => {
    chat.accept(sid!, request.body as Schemas["ChatJobRequest"]);
    return networkDown();
  };

const submits = (bff: FakeBff) => bff.calls("POST", SUBMIT);

describe("새 대화로 옮기는 중에 이전 질문의 답변이 도착할 때 (NFS002)", () => {
  test("접수 응답이 늦게 와도 새 대화에는 이전 질문도 답변도 붙지 않고, 이전 작업은 취소되지 않는다", async () => {
    const chat = newChatServer();
    const { bff, held: late, user, settle } = await openApp(EVENT_PAGE, (b) => {
      chat.serve(b);
      return b.holdResponse("POST", SUBMIT);
    });
    await openChat(user);

    await askQuestion(user, Q1);
    await late.arrived();
    await startNewConversation(user);
    await waitFor(() => expect(showsEmptyConversation()).toBe(true));
    expect(chatText()).not.toContain(Q1);

    late.respond();
    await settle();

    expect(showsEmptyConversation()).toBe(true);
    expect(chatText()).not.toContain(Q1);
    expect(chatText()).not.toContain(answerTo(Q1));

    // 새 대화는 막히지 않고, 거기에는 새 질문과 그 답변만 쌓인다.
    await askQuestion(user, Q2);
    await within(chatDialog()).findByText(answerTo(Q2));
    expect(chatText()).not.toContain(Q1);
    expect(chatText()).not.toContain(answerTo(Q1));

    // 화면이 이전 답변을 무시한 것은 서버 기록 삭제나 작업 취소가 아니다.
    const [first] = chat.jobs.values();
    expect(first?.question).toBe(Q1);
    expect(first?.status).toBe("completed");
    expect(bff.calls("POST", "/api/chat/jobs/:id/cancel")).toEqual([]);
  });

  test("응답을 못 받아 접수 여부를 확인하는 중에 새 대화로 옮겨도, 확인된 이전 작업이 새 대화에 붙지 않는다", async () => {
    const chat = newChatServer();
    const { held: check, user, settle } = await openApp(EVENT_PAGE, (b) => {
      chat.serve(b);
      b.on("POST", SUBMIT, lostResponse(chat));
      return b.hold("GET", JOB);
    });
    await openChat(user);

    await askQuestion(user, Q1);
    await check.arrived();
    await startNewConversation(user);
    await waitFor(() => expect(showsEmptyConversation()).toBe(true));

    check.respond(json([...chat.jobs.values()][0]));
    await settle();

    expect(showsEmptyConversation()).toBe(true);
    expect(chatText()).not.toContain(Q1);
    expect(chatText()).not.toContain(answerTo(Q1));
  });
});

describe("질문 응답을 받지 못했을 때 (FS053)", () => {
  test("서버가 처리 중이라 해도 새 작업을 만들지 않고, 이어지는 상태 확인으로 완료된 답변을 회수한다", async () => {
    const chat = newChatServer();
    chat.answerNow = null;
    const { bff, user } = await openApp(EVENT_PAGE, (b) => {
      chat.serve(b);
      b.on("POST", SUBMIT, lostResponse(chat));
    });
    await openChat(user);

    await askQuestion(user, Q1);
    await waitFor(() => expect(bff.calls("GET", JOB).length).toBeGreaterThan(0));
    expect(chat.jobs.size).toBe(1);

    const [jobId] = chat.jobs.keys();
    chat.complete(jobId!, answerTo(Q1));
    await within(chatDialog()).findByText(answerTo(Q1));

    expect(submits(bff)).toHaveLength(1);
    expect(chat.jobs.size).toBe(1);
  });

  test("상태 조회가 실패하면 접수 안 됨으로 단정하지 않고 같은 질문을 다시 만들지 않으며, 조회가 돌아오면 답변을 회수한다", async () => {
    const chat = newChatServer();
    const { bff, held: heal, user } = await openApp(EVENT_PAGE, (b) => {
      chat.serve(b);
      b.on("POST", SUBMIT, lostResponse(chat));
      return b.on("GET", JOB, apiError(503, "bff_unreachable"));
    });
    await openChat(user);

    await askQuestion(user, Q1);
    const recheck = await within(chatDialog()).findByRole("button", { name: "다시 확인" });
    expect(chatText()).toContain(Q1);
    // 새 질문으로 바꿔 보낼 수 없고, 새 작업 접수는 한 건도 늘지 않았다.
    expect((within(chatDialog()).getByRole("button", { name: "보내기" }) as HTMLButtonElement).disabled).toBe(true);
    expect(submits(bff)).toHaveLength(1);

    await user.click(recheck);
    await within(chatDialog()).findByRole("button", { name: "다시 확인" });
    expect(submits(bff)).toHaveLength(1);

    heal();
    await user.click(within(chatDialog()).getByRole("button", { name: "다시 확인" }));
    await within(chatDialog()).findByText(answerTo(Q1));
    expect(submits(bff)).toHaveLength(1);
    expect(chat.jobs.size).toBe(1);
  });

  test("서버가 작업이 없다고 확인하면 같은 작업 ID와 같은 질문·맥락으로 다시 접수한다", async () => {
    const chat = newChatServer();
    const { bff, user } = await openApp(EVENT_PAGE, (b) => {
      chat.serve(b);
      let attempts = 0;
      // 첫 요청은 서버에 닿기 전에 사라진다.
      b.on("POST", SUBMIT, (request, params) => {
        attempts += 1;
        return attempts === 1 ? networkDown() : chat.accept(params.sid!, request.body as Schemas["ChatJobRequest"]);
      });
    });
    await openChat(user);

    await askQuestion(user, Q1);
    await within(chatDialog()).findByText(answerTo(Q1));

    const sent = submits(bff);
    expect(sent).toHaveLength(2);
    expect(sent[1]!.body).toEqual(sent[0]!.body);
    expect(chat.jobs.size).toBe(1);
  });

  test("서버가 확인한 일시 실패는 [같은 조건으로 다시 시도]로 같은 작업을 다시 실행하고, 새 질문을 만들지 않는다", async () => {
    const chat = newChatServer();
    chat.answerNow = null;
    const { bff, user } = await openApp(EVENT_PAGE, (b) => chat.serve(b));
    await openChat(user);
    await askQuestion(user, Q1);
    await waitFor(() => expect(chat.jobs.size).toBe(1));
    const [jobId] = chat.jobs.keys();
    chat.fail(jobId!, { kind: "transient", reason: "model_unavailable", message: "일시적인 문제로 답변하지 못했어요.", retry: "rerun" });
    chat.answerNow = answerTo;

    await user.click(await within(chatDialog()).findByRole("button", { name: "같은 조건으로 다시 시도" }));
    await within(chatDialog()).findByText(answerTo(Q1));

    expect(bff.calls("POST", "/api/chat/jobs/:id/retry").map((r) => r.path)).toEqual([`/api/chat/jobs/${jobId}/retry`]);
    expect(submits(bff)).toHaveLength(1);
    expect(chat.jobs.size).toBe(1);
    expect(chat.jobs.get(jobId!)?.question).toBe(Q1);
  });
});

describe("답변 상태를 확인하지 못했을 때 (NFS004)", () => {
  test("상태 확인만 실패하면 질문은 그대로 두고, [다시 확인]은 상태만 다시 조회할 뿐 질문을 다시 보내거나 작업을 바꾸지 않는다", async () => {
    const chat = newChatServer();
    chat.answerNow = null;
    const { bff, held: heal, user } = await openApp(EVENT_PAGE, (b) => {
      chat.serve(b);
      // 대화 상태 조회(폴링)만 실패한다. "current" 조회는 그대로다.
      return b.on("GET", "/api/chat/sessions/:id", apiError(503, "bff_unreachable"), (r) => r.path !== "/api/chat/sessions/current");
    });
    await openChat(user);
    await askQuestion(user, Q1);

    const recheck = await within(chatDialog()).findByRole("button", { name: "다시 확인" });
    expect(chatText()).toContain(Q1);
    expect(chat.jobs.size).toBe(1);

    heal();
    await user.click(recheck);
    const [jobId] = chat.jobs.keys();
    chat.complete(jobId!, answerTo(Q1));
    await within(chatDialog()).findByText(answerTo(Q1));

    expect(submits(bff)).toHaveLength(1);
    expect(bff.calls("POST", "/api/chat/jobs/:id/retry")).toEqual([]);
    expect(bff.calls("POST", "/api/chat/jobs/:id/cancel")).toEqual([]);
    expect(chat.jobs.size).toBe(1);
  });
});
