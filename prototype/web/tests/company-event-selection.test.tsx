// FS041 차트의 사건 날짜 선택 — 날짜를 고르면 이전 선택(상세·차트 강조)은 정리되고,
// 그 날짜의 사건이 한 건이면 상세까지 열리며, 여러 건이면 카드를 펼쳐 사용자가 고르게 한다.
import { screen, waitFor } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { openApp } from "./support/app";
import { ALPHA, type TestCompany } from "./support/fixtures";
import { pageOf } from "./support/routes";
import { dateMarker, eventDetailShown, isHighlighted, openedEventTitles } from "./support/screens";

const SUPPLY = { id: "ev-alpha-supply", title: "알파전자 장비 공급 계약 체결", eventTime: "2026-09-20" };
const DELIVERY = { id: "ev-alpha-delivery", title: "알파전자 장비 납품 일정 조정", eventTime: "2026-09-20" };
const PATENT = { id: "ev-alpha-patent", title: "알파전자 특허 소송 제기", eventTime: "2026-09-21" };

/** 9월 20일에 사건 두 건, 9월 21일에 한 건 */
const alpha: TestCompany = { ...ALPHA, events: { ...ALPHA.events, "1m": [PATENT, SUPPLY, DELIVERY] } };

const open = () => openApp(pageOf(alpha), (_, world) => world.companies.set(alpha.id, alpha));
const selectedEventParam = () => new URLSearchParams(window.location.search).get("event");

describe("차트에서 사건이 있었던 날짜를 고를 때", () => {
  test("그 날짜의 사건이 한 건이면 바로 선택되어 상세가 열리고, 그 날짜 표시가 강조된다", async () => {
    const { bff, user } = await open();
    await screen.findByRole("list", { name: /사건 타임라인/ });

    await user.click(await screen.findByRole("button", { name: /^9월 21일 사건 1건/ }));

    await waitFor(() => expect(eventDetailShown()).toBe(true));
    expect(selectedEventParam()).toBe(PATENT.id);
    expect(openedEventTitles([PATENT.title, SUPPLY.title, DELIVERY.title])).toEqual([PATENT.title]);
    expect(isHighlighted(dateMarker("9월 21일"))).toBe(true);
    expect(isHighlighted(dateMarker("9월 20일"))).toBe(false);
    expect(bff.calls("GET", "/api/events/:id").map((r) => r.path)).toEqual([`/api/events/${PATENT.id}`]);
  });

  test("그 날짜의 사건이 여러 건이면 상세를 정하지 않고 카드만 펼쳐, 사용자가 고른 사건의 상세만 연다", async () => {
    const { bff, user } = await open();
    await screen.findByRole("list", { name: /사건 타임라인/ });

    await user.click(await screen.findByRole("button", { name: /^9월 20일 사건 2건/ }));

    expect(await screen.findByRole("button", { name: SUPPLY.title })).toBeTruthy();
    expect(screen.getByRole("button", { name: DELIVERY.title })).toBeTruthy();
    expect(selectedEventParam()).toBeNull();
    expect(eventDetailShown()).toBe(false);
    expect(isHighlighted(dateMarker("9월 20일"))).toBe(false);
    expect(bff.calls("GET", "/api/events/:id")).toEqual([]);

    await user.click(screen.getByRole("button", { name: DELIVERY.title }));
    await waitFor(() => expect(eventDetailShown()).toBe(true));
    expect(openedEventTitles([PATENT.title, SUPPLY.title, DELIVERY.title])).toEqual([DELIVERY.title]);
    expect(isHighlighted(dateMarker("9월 20일"))).toBe(true);
  });

  test("다른 날짜를 고르면 이전에 고른 사건의 상세와 차트 강조가 정리된다", async () => {
    const { user } = await open();
    await screen.findByRole("list", { name: /사건 타임라인/ });
    await user.click(await screen.findByRole("button", { name: /^9월 21일 사건 1건/ }));
    await waitFor(() => expect(eventDetailShown()).toBe(true));

    await user.click(dateMarker("9월 20일"));

    await waitFor(() => expect(eventDetailShown()).toBe(false));
    expect(selectedEventParam()).toBeNull();
    expect(openedEventTitles([PATENT.title, SUPPLY.title, DELIVERY.title])).toEqual([]);
    expect(isHighlighted(dateMarker("9월 21일"))).toBe(false);
    expect(isHighlighted(dateMarker("9월 20일"))).toBe(false);
  });
});
