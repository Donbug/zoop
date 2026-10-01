// 통계·선호도 화면이 함께 쓰는 부품: 기간 선택, 지표 값 표기(표본이 작으면 비율 대신 건수), 표 안 막대.
// 막대는 값을 읽는 보조일 뿐이다. 수치는 항상 글자로 함께 적는다.
import { EyeOff } from "lucide-react";
import { Segmented } from "@/components/ui/segmented";
import type { StatsMetric, StatsWindow } from "./api";
import { formatCount } from "./format";
import { StatusLabel } from "./ui";

export const windowOptions: { value: StatsWindow; label: string }[] = [
  { value: "7d", label: "7일" },
  { value: "30d", label: "30일" },
  { value: "all", label: "전체" },
];

export function parseWindow(value: string | null): StatsWindow {
  return value === "30d" || value === "all" ? value : "7d";
}

export function WindowSwitch({ value, onChange }: { value: StatsWindow; onChange: (value: StatsWindow) => void }) {
  return <Segmented aria-label="집계 기간" value={value} onValueChange={onChange} options={windowOptions} />;
}

const percent = new Intl.NumberFormat("ko-KR", { style: "percent", maximumFractionDigits: 1 });
export const formatPercent = (rate: number) => percent.format(rate);

/** 비율은 분모가 기준(minSample) 이상일 때만 퍼센트로, 아니면 "표본 부족"으로 보여 준다. */
export function MetricValue({ metric }: { metric: StatsMetric }) {
  if (metric.kind === "count") {
    return (
      <span className="font-semibold whitespace-nowrap tabular-nums">
        {formatCount(metric.count)}
        <span className="ml-1 text-sm font-normal text-text-secondary">{metric.unit}</span>
      </span>
    );
  }
  if (metric.rate == null) return <StatusLabel icon={EyeOff} label="표본 부족" tone="warning" />;
  return <span className="font-semibold tabular-nums">{formatPercent(metric.rate)}</span>;
}

/** 산식: "3 / 12명". 비율을 숨겼으면 기준을 함께 적는다. */
export function MetricBasis({ metric, minSample }: { metric: StatsMetric; minSample: number }) {
  if (metric.kind === "count") return <span className="text-text-tertiary">–</span>;
  return (
    <span className="whitespace-nowrap tabular-nums">
      {formatCount(metric.numerator)} / {formatCount(metric.denominator)}
      {metric.unit}
      {metric.sampleHidden && <span className="ml-1 text-sm text-text-secondary">(분모 {minSample} 미만이라 비율 숨김)</span>}
    </span>
  );
}

/** 표 칸 안의 값 + 가는 막대(최대값 대비). 막대는 장식이다. */
export function BarCell({ value, max }: { value: number; max: number }) {
  return (
    <div className="flex min-w-20 flex-col items-end gap-1">
      <span>{formatCount(value)}</span>
      <span aria-hidden="true" className="block h-1 w-full rounded-sm bg-surface-sunken">
        <span className="block h-full rounded-sm bg-brand-primary" style={{ width: `${max > 0 ? Math.round((value / max) * 100) : 0}%` }} />
      </span>
    </div>
  );
}
