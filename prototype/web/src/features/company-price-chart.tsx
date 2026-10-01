// 기업 상세 주가 차트(요구 37). 사건 타임라인과 같은 기간으로 조회하고, 사건 날짜 위치에 표시를 둔다.
//  - 차트 라이브러리 없이 SVG 한 줄(종가)로 그린다. 선 색은 기간 첫 종가 대비 마지막 종가의 상승·하락이며,
//    같은 내용을 위 줄에 부호·화살표·글자로도 적는다(색만으로 구분하지 않음).
//  - 사건 표시는 '이 날 사건이 있었다'만 뜻한다. 주가 움직임의 원인이라고 말하지 않는다. 누르면 그 날짜 묶음을 펼친다.
//  - 키보드·스크린리더: 차트는 요약 문장으로 읽히고, [표로 보기]에 시각별 종가·거래량 표가 있다. 사건 표시는 버튼이다.
//  - 일시 장애는 이 영역만 [다시 시도], 자료 없음은 한 줄, 미연결·미지원 종목은 시세 영역이 이미 사유를 말하므로 그리지 않는다.
import { Table, Zap } from "lucide-react";
import { useId, useState } from "react";
import { ApiError } from "@/api/client";
import { useCompanyPrices } from "@/api/queries";
import { ErrorState, LoadingBlock, Skeleton } from "@/components/ui/feedback";
import { Tooltip } from "@/components/ui/tooltip";
import { periodLabel, type EventGroup, type Period } from "@/lib/company-timeline";
import { formatCompact, formatPrice, placeMarkers, pointLabel, toneOf, type Tone } from "@/lib/market";
import { cn } from "@/lib/utils";
import { PriceChange } from "@/components/domain/status-labels";
import { QuoteSourceHint, UnavailableLine } from "./company-quote";

const W = 1000;
const H = 200;
const PAD = 12;
const strokeClass: Record<Tone, string> = { up: "stroke-up", down: "stroke-down", flat: "stroke-text-secondary" };

interface Props {
  companyId: string;
  period: Period;
  /** 타임라인과 같은(관계 거르기를 거친) 날짜 묶음 */
  groups: EventGroup[];
  /** 사건 표시를 누르면 그 묶음들을 펼치고 첫 묶음으로 옮긴다 */
  onPick: (keys: string[]) => void;
}

export function CompanyPriceChart({ companyId, period, groups, onPick }: Props) {
  const prices = useCompanyPrices(companyId, period);
  const [hover, setHover] = useState<number | null>(null);
  const summaryId = useId();

  if (prices.isPending)
    return (
      <LoadingBlock label="주가 차트를 불러오고 있어요" className="flex flex-col gap-2">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-40 w-full md:h-48" />
      </LoadingBlock>
    );
  if (prices.isError) return <ErrorState compact error={prices.error} title="주가 차트를 불러오지 못했어요" onRetry={() => void prices.refetch()} />;
  const data = prices.data;
  if (data.status === "unavailable") {
    if (data.reasonCode === "temporary_failure")
      return <ErrorState compact title="주가 차트를 불러오지 못했어요" error={new ApiError(200, data.reasonCode, data.reason)} message={data.reason} onRetry={() => void prices.refetch()} />;
    return data.reasonCode === "no_data" ? <UnavailableLine>{data.reason}</UnavailableLine> : null;
  }

  const { points, currency, source } = data;
  const intraday = data.interval !== "1d";
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
  );
  const label = (i: number) => pointLabel(points[i]!.time, intraday);
  const sessionDate = pointLabel(first.time, false);
  const scope = intraday ? `최근 거래일(${sessionDate})` : periodLabel[period];
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
        {hover !== null ? (
          <span>
            {intraday ? `${sessionDate} ${label(hover)}` : label(hover)} · <span className="font-semibold text-text-primary">{formatPrice(points[hover]!.close, currency)}</span>
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
        onPointerMove={(e) => pick(e.clientX, e.currentTarget.getBoundingClientRect())}
        onPointerDown={(e) => pick(e.clientX, e.currentTarget.getBoundingClientRect())}
        onPointerLeave={() => setHover(null)}
      >
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="absolute inset-0 size-full overflow-visible" aria-hidden="true">
          {markers.map((m) => (
            <line key={m.keys.join()} x1={m.x * W} x2={m.x * W} y1={0} y2={H} className="stroke-border-strong" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
          ))}
          <path d={line} fill="none" strokeWidth={2} strokeLinejoin="round" className={strokeClass[tone]} vectorEffect="non-scaling-stroke" />
          {hover !== null && (
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
        <div className="relative h-11" role="group" aria-label="사건이 있었던 날">
          {markers.map((m) => {
            const when = m.dates.length > 1 ? `${pointLabel(m.dates.at(-1)!, false)}~${pointLabel(m.dates[0]!, false)}` : pointLabel(m.dates[0]!, false);
            const text = `${when} 사건 ${m.count}건`;
            return (
              <Tooltip key={m.keys.join()} content={text}>
                <button
                  type="button"
                  aria-label={`${text} 보기`}
                  onClick={() => onPick(m.keys)}
                  className="pressable absolute top-0 inline-flex size-11 -translate-x-1/2 items-center justify-center rounded-sm text-text-secondary hover:bg-surface-sunken"
                  style={{ left: `clamp(22px, ${(m.x * 100).toFixed(2)}%, calc(100% - 22px))` }}
                >
                  <Zap className="size-4" aria-hidden="true" />
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
          {source.name} · {intraday ? `${data.interval === "1m" ? "1분" : "5분"} 간격` : "일별 종가"}
        </span>
        <QuoteSourceHint source={source} />
      </figcaption>
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
                    <td className="py-1.5 pr-3">{label(i)}</td>
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
