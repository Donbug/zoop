import { screen, waitFor, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { openApp } from "./support/app";
import { ALPHA, BETA } from "./support/fixtures";
import { pageOf } from "./support/routes";

const savedTime = "2026-10-02T00:00:00.000Z";

test("상세 주소는 기간·기준 시점·탭·이슈를 복원한다", async () => {
  await openApp(pageOf(ALPHA, `?period=1m&asOf=${encodeURIComponent(savedTime)}&tab=events&issue=ev-alpha-1m`));
  const timeline = await screen.findByRole("list", { name: /사건 타임라인/ });
  expect((await within(timeline).findByRole("button", { name: ALPHA.events["1m"][0]!.title })).getAttribute("aria-expanded")).toBe("true");
  expect(screen.getByRole("radio", { name: "1개월" }).getAttribute("aria-checked")).toBe("true");
  expect(new URLSearchParams(window.location.search).get("asOf")).toBe(savedTime);
});

test("기업 전환 시트의 검색으로 기업을 바꿔도 기간·탭·기준 시점은 유지한다", async () => {
  const { user } = await openApp(pageOf(ALPHA, `?period=1w&asOf=${encodeURIComponent(savedTime)}&tab=documents`));
  await screen.findByRole("heading", { level: 1, name: ALPHA.name });
  await user.click(screen.getByRole("button", { name: `${ALPHA.name} · 다른 기업 보기` }));
  const dialog = await screen.findByRole("dialog", { name: "기업 전환" });
  await user.type(within(dialog).getByRole("searchbox", { name: "기업 검색" }), BETA.name);
  await user.click(within(dialog).getByRole("button", { name: "검색" }));
  const results = await within(dialog).findByRole("list", { name: `‘${BETA.name}’ 검색 결과` });
  await user.click(within(results).getByRole("button", { name: new RegExp(BETA.name) }));
  await screen.findByRole("heading", { level: 1, name: BETA.name });
  const params = new URLSearchParams(window.location.search);
  expect(params.get("period")).toBe("1w");
  expect(params.get("asOf")).toBe(savedTime);
  expect(params.get("tab")).toBe("documents");
  expect(params.has("issue")).toBe(false);
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});
