// 근거 접근 상태(팀 화면계획서 슬라이드 39·40): 사건 상세의 인용 조회가 실패할 때,
// 지워졌거나(404) 볼 권한이 없는(403) 근거는 다시 시도할 오류가 아니라 상태로 알리고 내용은 그리지 않으며,
// 일시 장애(5xx)만 오류와 [다시 시도]를 보이고 그 근거만 다시 요청한다. 문서(제목·출처)는 사건 상세 값으로 그대로 남는다.
import { screen, waitFor } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { openApp } from "./support/app";
import type { Schemas } from "@/api/client";
import { apiError, json, type Reply } from "./support/fake-bff";
import { ALPHA, eventDetail, metadata } from "./support/fixtures";
import { pageOf } from "./support/routes";
import { alertTitled, retryIn } from "./support/screens";

const EVENT = ALPHA.events["1m"][0]!;
const ARTICLE_TITLE = "알파전자, 장비 공급 계약";
const ARTICLE: Schemas["ArticleOut"] = {
  id: "art-1",
  title: ARTICLE_TITLE,
  publisher: "시험일보",
  url: null,
  publishedAt: "2026-09-20T09:00:00+09:00",
  synthetic: true,
  relationType: "REPORTS",
};
const quoteOf = (id: string) => ({
  id,
  quote: `${id} 인용문`,
  start: 0,
  end: 10,
  articleId: ARTICLE.id,
  articleVersion: "1",
  article: { title: ARTICLE.title, publisher: ARTICLE.publisher, url: null, publishedAt: ARTICLE.publishedAt, synthetic: true },
  quoteVerified: true,
  eventIds: [EVENT.id],
  metadata,
});

/** 근거 id마다 응답(함수면 요청할 때마다 다시 정한다) */
function open(replies: Record<string, Reply | (() => Reply)>) {
  return openApp(pageOf(ALPHA, `?event=${EVENT.id}`), (bff) => {
    bff.on("GET", "/api/events/:id", json({ ...eventDetail(EVENT, ALPHA), articles: [ARTICLE], evidenceIds: Object.keys(replies) }));
    bff.on("GET", "/api/evidence/:id", (_, { id }) => {
      const reply = replies[id!]!;
      return typeof reply === "function" ? reply() : reply;
    });
  });
}

const goneNote = /근거 (\d+)건은 삭제됐거나 지금 볼 수 없는 자료예요/;

describe("사건 상세의 근거 인용을 받을 수 없을 때", () => {
  test("삭제(404)·권한 없음(403) 근거는 오류나 다시 시도 없이 건수만 알리고, 받은 인용과 문서 정보는 그대로 보인다", async () => {
    await open({ "ev-ok": json(quoteOf("ev-ok")), "ev-deleted": apiError(404, "evidence_not_found"), "ev-forbidden": apiError(403, "briefing_round_suspended") });

    expect((await screen.findByText(goneNote)).textContent).toMatch("근거 2건은");
    expect(screen.getByText(/ev-ok 인용문/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: ARTICLE_TITLE })).toBeTruthy();
    expect(screen.getByText("원문을 제공하지 않는 자료입니다")).toBeTruthy();
    expect(alertTitled("인용 일부를 불러오지 못했어요")).toBeNull();
    expect(screen.queryByText(/ev-deleted|ev-forbidden/)).toBeNull();
  });

  test("일시 장애 근거만 오류로 보이고, [다시 시도]는 그 근거만 다시 요청한다", async () => {
    let down = true;
    const { bff, user } = await open({
      "ev-gone": apiError(404, "evidence_not_found"),
      "ev-down": () => (down ? apiError(503, "bff_unreachable") : json(quoteOf("ev-down"))),
    });
    await waitFor(() => expect(alertTitled("인용 일부를 불러오지 못했어요")).not.toBeNull(), { timeout: 5000 });
    const alert = alertTitled("인용 일부를 불러오지 못했어요")!;
    expect(screen.getByText(goneNote).textContent).toMatch("근거 1건은");
    const goneCalls = bff.calls("GET", "/api/evidence/ev-gone").length;

    down = false;
    await user.click(retryIn(alert));

    expect(await screen.findByText(/ev-down 인용문/)).toBeTruthy();
    expect(alertTitled("인용 일부를 불러오지 못했어요")).toBeNull();
    expect(bff.calls("GET", "/api/evidence/ev-gone").length).toBe(goneCalls);
    expect(screen.getByText(goneNote).textContent).toMatch("근거 1건은");
  });
});
