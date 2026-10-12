// FS004: 신규 소셜 가입·연동에서 이메일을 못 받으면 로그인 방법을 다시 선택할 수 있다.
import { screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { openApp } from "./support/app";
import { anonymousSession } from "./support/fixtures";

test("소셜 이메일 미수신 안내와 이메일 로그인 경로를 보여 준다", async () => {
  const { bff, settle } = await openApp("/login?social=email_required", (_bff, world) => {
    world.session = anonymousSession();
  });
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain("이메일 제공에 동의하고 다시 시도하거나 다른 로그인 방법을 선택해 주세요");
  expect(screen.getByRole("heading", { name: "이메일로 로그인" })).toBeTruthy();
  await settle();
  expect(bff.writes).toEqual([]);
});
