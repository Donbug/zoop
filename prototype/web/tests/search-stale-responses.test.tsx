// NFS002 응답과 화면 정합성 — 종목 검색(내 종목 화면).
// 검색어를 A에서 B로 바꿔 다시 검색하면, A의 늦은 정상·오류 응답이 B 결과를 바꾸지 않는다.
import { screen, waitFor, within } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";
import { describe, expect, test } from "vitest";
import { openApp } from "./support/app";
import { apiError, json, type Reply } from "./support/fake-bff";
import { ALPHA, BETA, companySummary, disconnectedPortfolio, metadata, watchSettings } from "./support/fixtures";

/** 검색 영역이 지금 보여 주는 것: 결과가 어느 검색어의 것인지, 결과 행, 오류 안내 */
function readSearch() {
  const results = screen.queryByRole("list", { name: /검색 결과/ });
  return {
    resultsFor: results?.getAttribute("aria-label") ?? null,
    rows: results ? within(results).queryAllByRole("button").map((row) => row.textContent ?? "") : [],
    alerts: screen.queryAllByRole("alert").map((alert) => alert.textContent ?? ""),
  };
}

async function searchFor(user: UserEvent, term: string) {
  const box = within(screen.getByRole("search")).getByRole("searchbox");
  await user.clear(box);
  await user.type(box, `${term}{Enter}`);
}

describe("검색어를 A에서 B로 바꿔 다시 검색할 때", () => {
  test.each<[string, Reply]>([
    ["정상 응답", json({ items: [companySummary(ALPHA)], metadata })],
    ["오류 응답", apiError(503, "bff_unreachable")],
  ])("A의 %s이 B 결과 뒤에 도착해도 B 결과만 남는다", async (_, late) => {
    const { held, user, settle } = await openApp("/me/stocks", (bff, world) => {
      world.settings = watchSettings([]);
      world.portfolio = disconnectedPortfolio();
      return bff.hold("GET", "/api/companies", (r) => r.query.get("q") === "알파");
    });
    await screen.findByRole("search");

    await searchFor(user, "알파");
    await held.arrived();
    await searchFor(user, "베타");
    await waitFor(() => expect(readSearch().rows).toHaveLength(1));
    expect(readSearch()).toEqual({ resultsFor: "‘베타’ 검색 결과", rows: [expect.stringContaining(BETA.name)], alerts: [] });

    held.respond(late);
    await settle();

    expect(readSearch()).toEqual({ resultsFor: "‘베타’ 검색 결과", rows: [expect.stringContaining(BETA.name)], alerts: [] });
  });
});
