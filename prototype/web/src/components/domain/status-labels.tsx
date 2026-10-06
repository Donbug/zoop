// 등락·고지 표기: PriceChange(등락 금액·등락률), SentimentLabel(근거가 있는 AI 판정), DisclaimerNote(투자 권유 아님 고지)
// 없는 값(감성·AI 요약 등)은 '준비 중'으로 적지 않고 자리 자체를 그리지 않는다(v3, QuietValue 폐기).
import { CircleHelp, CircleMinus, CirclePlus, Scale, type LucideIcon } from "lucide-react";
import type { Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Popover } from "@/components/ui/popover";
import { formatKst, sentimentLabel, type Sentiment } from "@/lib/labels";
import { AiBadge } from "./ai";
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

/** BFF에서 생성한 문서×기업 판정·발행 회차 판단 타입을 그대로 쓴다. */
export type SentimentJudgement = Schemas["DocumentSentiment"] | Schemas["BriefingOutlook"];

const sentimentIcon: Record<Sentiment, LucideIcon> = {
  positive: CirclePlus,
  negative: CircleMinus,
  mixed: Scale,
  undetermined: CircleHelp,
};

/** 판정이 없으면 자리 자체를 그리지 않는다. 등락색·방향 화살표 대신 중성 글자와 서로 다른 아이콘을 쓴다. */
export function SentimentLabel({ judgement, accessibleName, className }: {
  judgement: SentimentJudgement | null | undefined;
  accessibleName?: string;
  className?: string;
}) {
  if (!judgement) return null;
  const label = sentimentLabel[judgement.label];
  const Icon = sentimentIcon[judgement.label];
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-1.5", className)}>
      <Popover
        label={`${accessibleName ? `${accessibleName} · ` : ""}${label} 판정 근거`}
        align="start"
        trigger={
          <Button variant="ghost" size="sm" aria-label={`${accessibleName ? `${accessibleName} · ` : ""}${label} 판정 근거 보기`}>
            <Icon className="size-4" aria-hidden="true" />
            {label}
          </Button>
        }
      >
        <p className="font-semibold text-text-primary">{label} 판정 근거</p>
        <p className="break-words">{judgement.rationale}</p>
        {"quotes" in judgement && judgement.quotes.length > 0 && (
          <div className="flex flex-col gap-2">
            <p className="font-semibold text-text-primary">원문 인용</p>
            {judgement.quotes.map((quote, index) => <blockquote key={index} className="break-words">“{quote}”</blockquote>)}
          </div>
        )}
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 border-t border-border-subtle pt-2">
          <dt>판정 시각</dt><dd className="tabular-nums"><time dateTime={judgement.judgedAt}>{formatKst(judgement.judgedAt)}</time></dd>
          <dt>모델</dt><dd className="break-words">{judgement.model}</dd>
          <dt>프롬프트 버전</dt><dd className="break-words">{judgement.promptVersion}</dd>
        </dl>
      </Popover>
      <AiBadge label="AI 판정" />
    </span>
  );
}

export const disclaimerText = "본 정보는 참고용이며 투자 권유가 아니에요.";

/** 투자 권유 아님 고지. 브리핑·기업 상세 하단에 한 줄, 13px. */
export function DisclaimerNote({ className, children = disclaimerText }: { className?: string; children?: string }) {
  return <p className={cn("text-sm text-text-secondary", className)}>{children}</p>;
}
