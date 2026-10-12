// FS040/FS041: 동일 기간의 실제 거래 바와 사건 버킷 표식. 휴장 시세를 채우지 않는다.
// 표식 선택은 버킷/사건 강조, 실제 바 선택은 공개 기준 asOf 변경이다.
// 클릭·화살표/Enter·시세 표 버튼으로 시점을 고를 수 있고 인과를 단정하지 않는다.
import { Table, Zap } from "lucide-react";
import { useId, useState } from "react";
import { useCompanyPrices } from "@/api/queries";
import { LoadingBlock, Skeleton } from "@/components/ui/feedback";
import { Tooltip } from "@/components/ui/tooltip";
import { periodLabel, type DetailRange, type EventGroup } from "@/lib/company-timeline";
import { formatCompact, formatPrice, placeMarkers, pointLabel, toneOf, type Tone } from "@/lib/market";
import { cn } from "@/lib/utils";
import { DisclaimerNote, PriceChange } from "@/components/domain/status-labels";
import { MarketErrorState, QuoteSourceHint, UnavailableLine } from "./company-quote";
import { formatKst } from "@/lib/labels";

const W = 1000;
const H = 200;
const PAD = 12;
const strokeClass: Record<Tone, string> = { up: "stroke-up", down: "stroke-down", flat: "stroke-text-secondary" };
const chartCausalityText = "차트와 사건의 시점이 겹쳐도 인과관계를 뜻하지는 않아요.";

interface Props {
  companyId: string;
  range: DetailRange;
  /** 타임라인과 같은(관계 거르기를 거친) 날짜 묶음 */
  groups: EventGroup[];
  /** 사건 표시를 누르면 그 날짜 묶음들을 고른다 */
  onPick: (keys: string[]) => void;
  /** 선택한 사건이 든 날짜 묶음 키(발생 날짜를 아는 사건만). 그 위치를 강조한다. */
  selectedKey: string | null;
  onAsOfChange?: (time: string) => void;
}

export function CompanyPriceChart({ companyId, range, groups, onPick, selectedKey, onAsOfChange }: Props) {
  const prices = useCompanyPrices(companyId, range);
  const period = range.period;
  const [hover, setHover] = useState<number | null>(null);
  const summaryId = useId();

  if (prices.isPending)
    return (
      <LoadingBlock label="주가 차트를 불러오고 있어요" className="flex flex-col gap-2">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-40 w-full md:h-48" />
      </LoadingBlock>
    );
  if (prices.isError) return <MarketErrorState error={prices.error} title="주가 차트를 불러오지 못했어요" onRetry={() => void prices.refetch()} />;
  const data = prices.data;
  // 출처 장애는 503 조회 오류(위)로 온다. 200 unavailable은 자료 없음만 사유를 적는다.
  if (data.status === "unavailable") return data.reasonCode === "no_data" ? <UnavailableLine>{data.reason}</UnavailableLine> : null;

  const { points, currency, source } = data;
  const intraday = data.interval === "5m" || data.interval === "1h";
  const n = points.length;
  const closes = points.map((p) => p.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const minAt = closes.indexOf(min);
  const maxAt = closes.indexOf(max);
  const xOf = (i: number) => (n === 1 ? W / 2 : (i / (n - 1)) * W);
  const yOf = (v: number) => (max === min ? H / 2 : PAD + ((max - v) / (max - min)) * (H - 2 * PAD));
  const line = closes.map((c, i) => `${i === 0 ? "M" : "L"}${xOf(i).toFixed(1)} ${yOf(c).toFixed(1)}`).join(" ");
  const first = points[0]!;
  const last = points[n - 1]!;
  const change = last.close - first.close;
  const tone = toneOf(change);
  const markers = placeMarkers(
    points.map((p) => p.time),
    intraday,
    groups,
    period,
  );
  const label = (i: number) => pointLabel(points[i]!.time, intraday);
  const sessionDate = pointLabel(first.time, false);
  const scope = period === "1d" ? `당일(${sessionDate})` : periodLabel[period];
  const summary =
    `${scope} 주가. 처음 ${label(0)} ${formatPrice(first.close, currency)}, 마지막 ${label(n - 1)} ${formatPrice(last.close, currency)}. ` +
    `최고 ${formatPrice(max, currency)}(${label(maxAt)}), 최저 ${formatPrice(min, currency)}(${label(minAt)}).` +
    (markers.length > 0 ? ` 사건이 있었던 날 ${markers.length}곳을 표시했어요.` : "");

  const pick = (clientX: number, rect: DOMRect) => {
    const frac = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    setHover(Math.round(frac * (n - 1)));
  };

  return (
    <figure className="flex flex-col gap-1" aria-labelledby={summaryId}>
      <p id={summaryId} className="sr-only">
        {summary}
      </p>
      <div className="flex min-h-7 flex-wrap items-center gap-x-2 text-sm text-text-secondary tabular-nums" aria-hidden="true">
        {hover !== null && points[hover] ? (
          <span>
            {intraday ? `${pointLabel(points[hover]!.time, false)} ${label(hover)}` : label(hover)} · <span className="font-semibold text-text-primary">{formatPrice(points[hover]!.close, currency)}</span>
          </span>
        ) : (
          <>
            <span>{scope} · 처음 시세 대비</span>
            <PriceChange change={change} changePercent={first.close ? (change / first.close) * 100 : null} currency={currency} className="text-sm font-normal" />
          </>
        )}
      </div>
      <div
        className="relative h-40 touch-pan-y md:h-48"
        role={onAsOfChange ? "slider" : undefined}
        tabIndex={onAsOfChange ? 0 : undefined}
        aria-label={onAsOfChange ? "차트 기준 시점. 화살표로 이동하고 Enter로 선택해요" : undefined}
        aria-valuemin={onAsOfChange ? 0 : undefined}
        aria-valuemax={onAsOfChange ? n - 1 : undefined}
        aria-valuenow={onAsOfChange ? Math.min(hover ?? n - 1, n - 1) : undefined}
        aria-valuetext={onAsOfChange ? `${label(Math.min(hover ?? n - 1, n - 1))} ${formatPrice(points[Math.min(hover ?? n - 1, n - 1)]!.close, currency)}` : undefined}
        onKeyDown={(event) => {
          const index = Math.min(hover ?? n - 1, n - 1);
          if (["ArrowLeft", "ArrowDown", "ArrowRight", "ArrowUp", "Home", "End", "Enter", " "].includes(event.key)) event.preventDefault();
          if (event.key === "ArrowLeft" || event.key === "ArrowDown") setHover(Math.max(0, index - 1));
          else if (event.key === "ArrowRight" || event.key === "ArrowUp") setHover(Math.min(n - 1, index + 1));
          else if (event.key === "Home") setHover(0);
          else if (event.key === "End") setHover(n - 1);
          else if (event.key === "Enter" || event.key === " ") onAsOfChange?.(points[index]!.time);
        }}
        onClick={(event) => {
          if (!onAsOfChange) return;
          const rect = event.currentTarget.getBoundingClientRect();
          const fraction = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
          onAsOfChange(points[Math.round(fraction * (n - 1))]!.time);
        }}
        onPointerMove={(e) => pick(e.clientX, e.currentTarget.getBoundingClientRect())}
        onPointerDown={(e) => pick(e.clientX, e.currentTarget.getBoundingClientRect())}
        onPointerLeave={() => setHover(null)}
      >
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="absolute inset-0 size-full overflow-visible" aria-hidden="true">
          {markers.map((m) => {
            const selected = selectedKey !== null && m.keys.includes(selectedKey);
            return (
              <line
                key={m.keys.join()}
                x1={m.x * W}
                x2={m.x * W}
                y1={0}
                y2={H}
                className={selected ? "stroke-text-primary" : "stroke-border-strong"}
                strokeDasharray={selected ? undefined : "4 4"}
                vectorEffect="non-scaling-stroke"
              />
            );
          })}
          <path d={line} fill="none" strokeWidth={2} strokeLinejoin="round" className={strokeClass[tone]} vectorEffect="non-scaling-stroke" />
          {hover !== null && hover < n && (
            <line x1={xOf(hover)} x2={xOf(hover)} y1={0} y2={H} className="stroke-text-tertiary" vectorEffect="non-scaling-stroke" />
          )}
        </svg>
        <span className="pointer-events-none absolute top-0 right-0 bg-surface-base/80 px-1 text-sm text-text-tertiary tabular-nums" aria-hidden="true">
          {formatPrice(max, currency)}
        </span>
        <span className="pointer-events-none absolute right-0 bottom-0 bg-surface-base/80 px-1 text-sm text-text-tertiary tabular-nums" aria-hidden="true">
          {formatPrice(min, currency)}
        </span>
      </div>
      {markers.length > 0 && (
        <div className="relative h-11" role="group" aria-label="사건이 있었던 시간 버킷">
          {markers.map((m) => {
            const when = m.dates.length > 1 ? `${pointLabel(m.dates.at(-1)!, false)}~${pointLabel(m.dates[0]!, false)}` : pointLabel(m.dates[0]!, false);
            const text = `${when} 사건 ${m.count}건`;
            const selected = selectedKey !== null && m.keys.includes(selectedKey);
            return (
              <Tooltip key={m.keys.join()} content={selected ? `${text} · 선택한 사건` : text}>
                <button
                  type="button"
                  aria-label={selected ? `${text}, 선택한 사건의 날짜` : `${text} 보기`}
                  aria-current={selected ? "true" : undefined}
                  onClick={() => onPick(m.keys)}
                  className={cn(
                    "pressable absolute top-0 inline-flex size-11 -translate-x-1/2 items-center justify-center rounded-sm hover:bg-surface-sunken",
                    selected ? "bg-surface-selected text-text-primary" : "text-text-secondary",
                  )}
                  style={{ left: `clamp(22px, ${(m.x * 100).toFixed(2)}%, calc(100% - 22px))` }}
                >
                  <Zap className={cn("size-4", selected && "fill-current")} aria-hidden="true" />
                  {m.count > 1 && <span className="text-sm tabular-nums">{m.count}</span>}
                </button>
              </Tooltip>
            );
          })}
        </div>
      )}
      <div className="flex justify-between text-sm text-text-tertiary tabular-nums" aria-hidden="true">
        <span>{intraday ? `${sessionDate} ${label(0)}` : label(0)}</span>
        <span>{label(n - 1)}</span>
      </div>
      <figcaption className="flex flex-wrap items-center gap-x-1 text-sm text-text-secondary">
        <span>
          {source.name} · {data.interval === "5m" ? "5분 간격" : data.interval === "1h" ? "시간 간격" : data.interval === "1wk" ? "주별 종가" : "일별 종가"}
        </span>
        <QuoteSourceHint source={source} />
        <span className="tabular-nums">마지막 시세 <time dateTime={last.time}>{formatKst(last.time)}</time></span>
      </figcaption>
      {/* 사건 표시와 같은 화면에 그리므로 시점 겹침을 인과로 읽지 않게 한 번 알린다(차트를 그릴 때만). */}
      <DisclaimerNote>{chartCausalityText}</DisclaimerNote>
      <details className="text-sm">
        <summary className="inline-flex min-h-11 cursor-pointer items-center gap-1 text-text-secondary">
          <Table className="size-4" aria-hidden="true" />
          표로 보기
        </summary>
        <div className="max-h-64 overflow-auto border-y border-border-subtle">
          <table className="w-full text-left tabular-nums">
            <caption className="sr-only">{scope} 시세 표</caption>
            <thead className="sticky top-0 bg-surface-base text-text-secondary">
              <tr>
                <th scope="col" className="py-2 pr-3 font-medium">
                  {intraday ? "시각(현지)" : "날짜"}
                </th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  종가
                </th>
                <th scope="col" className="py-2 text-right font-medium">
                  거래량
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-subtle text-text-primary">
              {points
                .map((p, i) => (
                  <tr key={p.time}>
                    <td className="py-1.5 pr-3">{onAsOfChange ? <button type="button" className="min-h-11 text-brand-primary underline underline-offset-4" onClick={() => onAsOfChange(p.time)} aria-label={`${pointLabel(p.time, false)} ${intraday ? label(i) : ""} 기준 시점 선택`}>{label(i)}</button> : label(i)}</td>
                    <td className="py-1.5 pr-3 text-right">{formatPrice(p.close, currency)}</td>
                    <td className={cn("py-1.5 text-right", p.volume == null && "text-text-tertiary")}>{p.volume != null ? formatCompact(p.volume) : "–"}</td>
                  </tr>
                ))
                .reverse()}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
