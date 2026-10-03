// 등락·고지 표기: PriceChange(등락 금액·등락률), SentimentLabel(디자인시스템 전용 규격), DisclaimerNote(투자 권유 아님 고지)
// 없는 값(감성·AI 요약 등)은 '준비 중'으로 적지 않고 자리 자체를 그리지 않는다(v3, QuietValue 폐기).
import { formatPrice } from "@/lib/market";
import { cn } from "@/lib/utils";

/** 등락: 색 + 부호 + ▲/▼를 함께 쓴다(색만으로 전달 금지). 금액(change)과 통화가 있으면 `▲ +5,250원 (+1.96%)`,
 *  없으면 등락률만 `▲ +1.96%`. 통화가 아닌 값(지수 포인트 등)은 `formatAmount`로 절댓값 표기를 직접 준다.
 *  값이 둘 다 없으면 아무것도 그리지 않는다. */
export function PriceChange({
  changePercent,
  change = null,
  currency,
  formatAmount,
  className,
}: {
  changePercent: number | null;
  change?: number | null;
  currency?: string;
  formatAmount?: (absolute: number) => string;
  className?: string;
}) {
  const basis = change ?? changePercent;
  if (basis === null) return null;
  const up = basis > 0;
  const down = basis < 0;
  const percent = changePercent === null ? null : `${up ? "+" : ""}${changePercent.toFixed(2)}%`;
  const sign = up ? "+" : down ? "-" : "";
  const format = formatAmount ?? (currency ? (value: number) => formatPrice(value, currency) : null);
  const amount = change !== null && format ? `${sign}${format(Math.abs(change))}` : null;
  const text = [up ? "▲" : down ? "▼" : null, amount, amount && percent ? `(${percent})` : percent].filter(Boolean).join(" ");
  return (
    <data
      value={basis}
      className={cn("text-base font-semibold tabular-nums", up && "text-up", down && "text-down", !up && !down && "text-text-secondary", className)}
    >
      {text}
      <span className="sr-only">{up ? " 상승" : down ? " 하락" : " 보합"}</span>
    </data>
  );
}

export type Sentiment = "positive" | "negative" | "mixed" | "undetermined";

const sentimentStyle: Record<Sentiment, { label: string; hint: string; className: string }> = {
  positive: { label: "호재 가능성", hint: "긍정 요인이 보도됨", className: "text-up" },
  negative: { label: "악재 가능성", hint: "부정 요인이 보도됨", className: "text-down" },
  mixed: { label: "혼합", hint: "긍·부정 요인 공존", className: "text-text-primary" },
  undetermined: { label: "판단 보류", hint: "근거 불충분 또는 해석 대립", className: "text-text-secondary" },
};

/** 디자인시스템 전용 규격. 프로토타입 화면에는 감성 데이터가 없으므로 그리지 않는다. */
export function SentimentLabel({ value }: { value: Sentiment }) {
  const s = sentimentStyle[value];
  return (
    <span className={cn("inline-flex items-center gap-1 text-sm font-semibold", s.className)}>
      {s.label}
      <span className="font-normal text-text-secondary">({s.hint})</span>
    </span>
  );
}

export const disclaimerText = "본 정보는 참고용이며 투자 권유가 아니에요.";

/** 투자 권유 아님 고지. 브리핑·기업 상세 하단에 한 줄, 13px. */
export function DisclaimerNote({ className, children = disclaimerText }: { className?: string; children?: string }) {
  return <p className={cn("text-sm text-text-secondary", className)}>{children}</p>;
}
