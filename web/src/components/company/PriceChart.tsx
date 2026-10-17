import type { ChartPeriod } from '@/types/company';
import type { EventDetail, Events } from '@/types/company/detail';
import { bucketKey, exactTime, timeRange } from './detail-model';

// D-COM-05 시세 차트. 가격 선과, 사건이 있던 시점에만 ⚡ 표식과 세로 점선을 그린다.
// 표식을 눌러도 기준 시점(asOf)은 바뀌지 않고 아래 타임라인에서 그 버킷의 사건을 보여 준다.
// 가격 봉 선택으로 기준 시점을 바꾸던 D-COM-06 동작은 두지 않는다.

const kstDate = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul',
  month: 'long',
  day: 'numeric',
});
const kstDateTime = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul',
  month: 'numeric',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});
const won = new Intl.NumberFormat('ko-KR');

function axisLabel(time: string, period: ChartPeriod) {
  const date = new Date(time);
  return period === '1d' || period === '1w'
    ? kstDateTime.format(date)
    : kstDate.format(date);
}

/** 버킷 표식을 놓을 시각. 정확한 사건 시각이 없으면 같은 버킷의 실제 가격 봉을 쓴다(시각을 지어내지 않는다). */
function markerTime(
  key: string,
  items: Events['items'],
  points: { time: string }[],
  period: ChartPeriod,
) {
  return (
    items.find(
      (item) => item.timePrecision === 'datetime' && exactTime(item.eventTime),
    )?.eventTime ??
    points.find(
      (point) =>
        bucketKey(
          { eventTime: point.time, timePrecision: 'datetime' },
          period,
        ) === key ||
        // 1일·1주에서 일 정밀도 사건은 같은 한국 날짜의 첫 봉에 표시한다.
        (key.endsWith(' · 일 정밀도') &&
          bucketKey(
            { eventTime: point.time, timePrecision: 'datetime' },
            '1m',
          ) === key.slice(0, 10)),
    )?.time
  );
}

export default function PriceChart({
  points,
  asOf,
  period,
  groups,
  selectedBucket,
  selectedEvent,
  onBucket,
}: {
  points: { time: string; close: number }[];
  asOf: string | null;
  period: ChartPeriod;
  groups: Map<string, Events['items']>;
  selectedBucket: string | null;
  selectedEvent: EventDetail | null;
  onBucket: (bucket: string) => void;
}) {
  if (!points.length)
    return <p className="text-xs text-zoop-muted">제공된 가격 봉이 없어요.</p>;
  const values = points.map((point) => point.close);
  const min = Math.min(...values),
    max = Math.max(...values);
  const range =
    asOf && exactTime(asOf)
      ? timeRange(asOf, period)
      : { from: points[0].time, to: points.at(-1)!.time };
  const start = Date.parse(range.from),
    end = Date.parse(range.to);
  const x = (time: string) =>
    end === start
      ? 300
      : 10 + ((Date.parse(time) - start) * 520) / (end - start);
  const y = (close: number) => 160 - ((close - min) * 140) / (max - min || 1);
  const markers = [...groups].flatMap(([key, items]) => {
    const at = markerTime(key, items, points, period);
    if (!at || Date.parse(at) < start || Date.parse(at) > end) return [];
    const selected =
      selectedBucket === key ||
      (!!selectedEvent && bucketKey(selectedEvent, period) === key);
    return [{ key, items, position: x(at), selected }];
  });

  return (
    <figure className="flex flex-col gap-1">
      <svg
        className="h-auto w-full"
        viewBox="0 0 600 205"
        role="group"
        aria-label="공급된 종가 차트"
      >
        {markers.map(({ key, position, selected }) => (
          <line
            key={`line-${key}`}
            x1={position}
            x2={position}
            y1="10"
            y2="178"
            strokeDasharray="3 3"
            className={selected ? 'stroke-zoop-ink' : 'stroke-zoop-faint'}
          />
        ))}
        <polyline
          points={points
            .map((point) => `${x(point.time)},${y(point.close)}`)
            .join(' ')}
          className="fill-none stroke-zoop-up stroke-[1.5]"
        />
        <text
          x="592"
          y={y(max) - 4}
          textAnchor="end"
          className="fill-zoop-muted text-[10px]"
        >
          {won.format(max)}
        </text>
        <text
          x="592"
          y={y(min) + 12}
          textAnchor="end"
          className="fill-zoop-muted text-[10px]"
        >
          {won.format(min)}
        </text>
        {markers.map(({ key, items, position, selected }) => (
          <g
            key={key}
            role="button"
            tabIndex={0}
            aria-label={`차트 사건 ${key} · 사건 ${items.length}건`}
            aria-pressed={selected}
            className="cursor-pointer focus-visible:outline-2 focus-visible:outline-zoop-ink"
            onClick={() => onBucket(key)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                onBucket(key);
              }
            }}
          >
            {/* 마우스를 올리면 그때의 사건 제목을 보여 준다. */}
            <title>{items.map((item) => item.title).join(' / ')}</title>
            <rect
              x={position - 9}
              y="181"
              width="18"
              height="18"
              rx="3"
              className={selected ? 'fill-zoop-ink' : 'fill-transparent'}
            />
            <path
              d={`M${position + 1.5} 183.5 L${position - 3.5} 191 H${position} L${position - 1.5} 196.5 L${position + 3.5} 189 H${position} Z`}
              strokeLinejoin="round"
              className={
                selected
                  ? 'fill-zoop-paper stroke-zoop-paper'
                  : 'fill-zoop-paper stroke-zoop-muted'
              }
            />
          </g>
        ))}
      </svg>
      <figcaption className="flex justify-between text-[11px] text-zoop-muted tabular-nums">
        <span>{axisLabel(range.from, period)}</span>
        <span>{axisLabel(range.to, period)}</span>
      </figcaption>
    </figure>
  );
}
