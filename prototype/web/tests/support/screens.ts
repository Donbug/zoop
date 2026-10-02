// 화면에서 값을 읽는 도우미. 문구·역할 이름이 바뀌면 이 파일만 고친다(시험 본문은 "어떤 값이 보이는가"만 말한다).
import { screen, waitFor, within } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";
import { expect } from "vitest";
import type { Period } from "@/lib/company-timeline";
import { ALPHA, type TestCompany } from "./fixtures";

export const won = (value: number) => `${value.toLocaleString("ko-KR")}원`;

const text = (element: Element | null | undefined) => element?.textContent?.replace(/\s+/g, " ").trim() ?? null;

/** 기업 상세 화면이 지금 보여 주는 값 */
export interface CompanyScreen {
  /** 머리글(개요 영역). 개요가 아직 오지 않았으면 가려진 기본 제목이 읽힌다. */
  name: string | null;
  quote: string | null;
  metrics: string | null;
  /** 가상 계좌 보유 영역(보유하지 않은 기업이면 영역이 없다) */
  holding: string | null;
  /** 사건 목록의 제목들(위에서 아래로) */
  events: string[];
  /** 주가 차트의 요약 문장(없으면 null) */
  chart: string | null;
  /** 지금 떠 있는 오류 안내들 */
  alerts: string[];
}

export function readCompanyScreen(): CompanyScreen {
  const timeline = screen.queryByRole("list", { name: /사건 타임라인/ });
  const chart = screen.queryByRole("figure");
  return {
    name: text(screen.queryByRole("heading", { level: 1 })),
    quote: text(screen.queryByRole("region", { name: "시세" })),
    metrics: text(screen.queryByRole("region", { name: "주요 지표" })),
    holding: text(screen.queryByRole("region", { name: "가상 계좌 보유" })),
    events: timeline ? within(timeline).queryAllByRole("button").map((b) => text(b)!) : [],
    chart: text(chart?.querySelector("p")),
    alerts: screen.queryAllByRole("alert").map((a) => text(a)!),
  };
}

/** 기업 c의 period 값만으로 채워진, 오류 없는 완성 화면 */
export function shown(c: TestCompany, period: Period) {
  return {
    name: c.name,
    quote: expect.stringContaining(won(c.price)),
    metrics: expect.stringContaining(c.per),
    // 시험 세계의 회원은 알파전자 10주를 모의로 보유한다.
    holding: c.id === ALPHA.id ? expect.stringContaining("10주") : null,
    events: c.events[period].map((e) => e.title),
    chart: expect.stringContaining(won(c.closes[period].at(-1)!)),
    alerts: [],
  } satisfies Record<keyof CompanyScreen, unknown>;
}

const mainText = () => text(screen.getByRole("main")) ?? "";
const allPeriods: Period[] = ["1d", "1m", "1y"];
const periodValues = (c: TestCompany, period: Period) => [...c.events[period].map((e) => e.title), ...c.closes[period].map(won)];

/** 화면에 남아 있는 기업 c의 흔적(이름·현재가·모든 기간의 사건 제목·차트 종가). 비어 있어야 c의 값이 섞이지 않은 것이다. */
export function traceOfCompany(c: TestCompany): string[] {
  const body = mainText();
  return [c.name, won(c.price), ...allPeriods.flatMap((p) => periodValues(c, p))].filter((needle) => body.includes(needle));
}

/** 화면에 남아 있는 기업 c의 period 기간 값(사건 제목·차트 종가)의 흔적 */
export function traceOfPeriod(c: TestCompany, period: Period): string[] {
  const body = mainText();
  return periodValues(c, period).filter((needle) => body.includes(needle));
}

export const periodButton = (label: "1일" | "1개월" | "1년") => screen.getByRole("radio", { name: label });

/** 영역마다 오류 안내의 제목이 다르다. 제목으로 "어느 영역의 오류인가"를 가린다. */
export const errorTitle = {
  overview: "기업 정보를 불러오지 못했어요",
  quote: "시세를 불러오지 못했어요",
  metrics: "주요 지표를 불러오지 못했어요",
  chart: "주가 차트를 불러오지 못했어요",
  events: "사건 목록을 불러오지 못했어요",
  portfolio: "보유 종목을 불러오지 못했어요",
  holding: "가상 계좌 보유를 확인하지 못했어요",
  documents: "근거 문서를 불러오지 못했어요",
} as const;

/** 제목이 title인 오류 안내. 없으면 null. */
export const alertTitled = (title: string) => screen.queryAllByRole("alert").find((alert) => alert.textContent?.includes(title)) ?? null;

/** 오류 안내 안의 [다시 시도] 버튼 */
export const retryIn = (alert: HTMLElement) => within(alert).getByRole("button", { name: "다시 시도" });

// ---- AI 질문 창

export const chatDialog = () => screen.getByRole("dialog", { name: "AI에게 묻기" });

/** 창 안에 보이는 글 전체 */
export const chatText = () => text(chatDialog()) ?? "";

/** 사건 상세의 [AI에게 묻기]로 질문 창을 열고, 이전 대화를 확인해 질문을 쓸 수 있을 때까지 기다린다. */
export async function openChat(user: UserEvent) {
  await user.click(await screen.findByRole("button", { name: "AI에게 묻기" }));
  const dialog = await screen.findByRole("dialog", { name: "AI에게 묻기" });
  await waitFor(() => expect((within(dialog).getByRole("textbox", { name: "질문" }) as HTMLInputElement).disabled).toBe(false));
  return dialog;
}

export async function askQuestion(user: UserEvent, question: string) {
  await user.type(within(chatDialog()).getByRole("textbox", { name: "질문" }), question);
  await user.click(within(chatDialog()).getByRole("button", { name: "보내기" }));
}

export const startNewConversation = (user: UserEvent) => user.click(within(chatDialog()).getByRole("button", { name: "새 대화" }));

/** 빈 대화일 때만 보이는 추천 질문 영역 */
export const showsEmptyConversation = () => within(chatDialog()).queryByRole("heading", { name: "추천 질문" }) !== null;

// ---- 계정

/** 계정 메뉴에서 로그아웃을 누른다. */
export async function logOut(user: UserEvent) {
  await user.click(screen.getByRole("button", { name: /^계정 메뉴/ }));
  await user.click(await screen.findByRole("menuitem", { name: "로그아웃" }));
}

/** 로그인 화면에서 입력칸에 미리 들어 있는 계정으로 로그인한다. */
export async function logIn(user: UserEvent) {
  await user.click(await screen.findByRole("button", { name: "로그인" }));
}

/** 화면 본문과 헤더 어디에든 남아 있는 글 중 needles에 해당하는 것(개인 정보 노출 점검용) */
export function exposedIn(needles: string[]) {
  const page = text(document.body) ?? "";
  const labels = [...document.querySelectorAll("[aria-label]")].map((e) => e.getAttribute("aria-label") ?? "").join(" ");
  return needles.filter((needle) => page.includes(needle) || labels.includes(needle));
}

// ---- 사건 타임라인·차트의 사건 표시

/** 차트 위 사건 표시 버튼. label은 "9월 21일"처럼 날짜 표기. */
export const dateMarker = (label: string) => screen.getByRole("button", { name: new RegExp(`^${label} 사건 \\d+건`) });

export const isHighlighted = (marker: HTMLElement) => marker.getAttribute("aria-current") === "true";

/** 상세가 열려 있는 사건 카드의 제목들(제목은 titles 중에서만 센다) */
export function openedEventTitles(titles: string[]) {
  const timeline = screen.getByRole("list", { name: /사건 타임라인/ });
  return within(timeline)
    .queryAllByRole("button")
    .filter((button) => button.getAttribute("aria-expanded") === "true" && titles.includes(text(button) ?? ""))
    .map((button) => text(button)!);
}

/** 선택한 사건의 상세(영향 경로 등)가 화면에 있는가 */
export const eventDetailShown = () => screen.queryByRole("heading", { name: "영향 경로" }) !== null;

// ---- 메인 지도(캔버스 대역이 노드를 버튼 목록으로 보인다)

type MapMode = "시장 전체" | "내 종목";
const mapModes: MapMode[] = ["시장 전체", "내 종목"];

export const modeButton = (mode: MapMode) => screen.getByRole("radio", { name: mode });

/** 메인 지도가 지금 보여 주는 것 */
export function readMap() {
  const nodes = screen.queryByRole("list", { name: "지도의 노드" });
  const checked = screen.queryAllByRole("radio").find((radio) => radio.getAttribute("aria-checked") === "true" && mapModes.includes(text(radio) as MapMode));
  return {
    /** 화면 제목: 지금 보이는 지도의 이름 */
    title: text(screen.queryByRole("heading", { level: 1 })),
    /** 모드 전환 컨트롤이 선택한 모드 */
    mode: text(checked),
    nodes: nodes ? within(nodes).queryAllByRole("button").map((node) => text(node)!) : [],
    alerts: screen.queryAllByRole("alert").map((alert) => text(alert)!),
  };
}
