// 가상 보유 평가 표시(FS039·FS054). BFF가 모의 수량과 같은 계산 시점에 읽은 시세로 평가금액·자산 비중을 계산해 보낸다.
// 비중은 현금을 뺀 주식 평가금액 합계 대비이고, 계산할 수 없으면 null이다. 화면은 null을 0%로 바꾸지 않고 '계산 불가'로 적는다.
import type { Schemas } from "@/api/client";

export type Holding = Schemas["HoldingOut"];

const percent = new Intl.NumberFormat("ko-KR", { style: "percent", maximumFractionDigits: 1 });

/** 자산 비중 값. null이면 '계산 불가'(사유는 valuation.weightUnavailableReason). */
export function formatWeight(weight: number | null): string {
  return weight === null ? "계산 불가" : percent.format(weight);
}

/** 목록 한 줄용: '비중 25%' 또는 '비중 계산 불가' */
export function holdingWeightText(holding: Pick<Holding, "weight">): string {
  return `비중 ${formatWeight(holding.weight)}`;
}
