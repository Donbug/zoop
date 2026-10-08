import { screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import { openApp } from "./support/app";

test("디자인시스템은 실제 문서 분석 컴포넌트로 합성 상태와 근거를 보여주며 API 분석을 실행하지 않는다", async () => {
  const app = await openApp("/design-system#c-document-analysis");
  await screen.findByRole("button", { name: /계정 메뉴: 시험회원/ });
  const example = within(await screen.findByRole("article", { name: "DocumentAnalysis · S1 문서 분석 상태" }));
  expect(example.getByText(/Figma 전면 스타일 전환은 아직 적용하지 않았어요/)).toBeTruthy();
  expect(example.getByText(/데모 예시/)).toBeTruthy();
  await app.user.click(example.getByRole("button", { name: "요약 1 근거 보기" }));
  const sheet = within(await screen.findByRole("dialog", { name: "가상 문서 요약 근거" }));
  expect(sheet.getByText("“예시전자는 공급 계약을 체결했다.”")).toBeTruthy();
  await app.user.keyboard("{Escape}");
  await app.user.click(example.getByRole("combobox", { name: "문서 분석 상태 예시" }));
  await app.user.click(await screen.findByRole("option", { name: "미요청 · null" }));
  expect(example.queryByText("AI 문서 요약")).toBeNull();
  expect(example.queryByRole("button", { name: /판정 근거 보기/ })).toBeNull();
  await app.user.click(example.getByRole("combobox", { name: "문서 분석 상태 예시" }));
  await app.user.click(await screen.findByRole("option", { name: "판단 보류 · 유효한 판정" }));
  expect(example.getByRole("button", { name: /판단 보류 판정 근거 보기/ })).toBeTruthy();
  expect(screen.getByText("올바른 이메일 주소를 입력해 주세요.")).toBeTruthy();
  expect(screen.queryByText("관심 종목을 1개 이상 골라 주세요.")).toBeNull();
  expect(app.bff.calls("GET", "/api/evidence/:id")).toEqual([]);
  expect(app.bff.calls("GET", "/api/companies/:id/documents")).toEqual([]);
  expect(app.bff.writes.filter((request) => request.path !== "/api/telemetry")).toEqual([]);
});
