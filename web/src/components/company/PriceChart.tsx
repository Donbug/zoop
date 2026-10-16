import type { ChartPeriod } from '@/types/company';
import type { EventDetail, Events } from '@/types/company/detail';
import { bucketKey, exactTime, timeRange } from './detail-model';

export default function PriceChart({
  points,
  onSelect,
  asOf,
  period,
  groups,
  selectedBucket,
  selectedEvent,
  onBucket,
}: {
  points: { time: string; close: number }[];
  onSelect: (time: string) => void;
  asOf: string | null;
  period: ChartPeriod;
  groups: Map<string, Events['items']>;
  selectedBucket: string | null;
  selectedEvent: EventDetail | null;
  onBucket: (bucket: string) => void;
}) {
  if (!points.length) return <p>제공된 가격 봉이 없어요.</p>;
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
      : 15 + ((Date.parse(time) - start) * 570) / (end - start);
  const y = (close: number) => 180 - ((close - min) * 150) / (max - min || 1);
  return (
    <svg
      className="h-auto w-full"
      viewBox="0 0 600 210"
      role="img"
      aria-label="공급된 종가 차트"
    >
      <polyline
        points={points
          .map((point) => `${x(point.time)},${y(point.close)}`)
          .join(' ')}
        className="fill-none stroke-zoop-up stroke-2"
      />
      {points.map((point) => (
        <g
          key={point.time}
          role="button"
          tabIndex={0}
          className="cursor-pointer focus-visible:outline-2 focus-visible:outline-zoop-ink"
          aria-label={`차트 ${point.time} 선택`}
          aria-pressed={!!asOf && Date.parse(asOf) === Date.parse(point.time)}
          onClick={() => exactTime(point.time) && onSelect(point.time)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              if (exactTime(point.time)) onSelect(point.time);
            }
          }}
        >
          <circle
            cx={x(point.time)}
            cy={y(point.close)}
            r="6"
            className={
              asOf && Date.parse(asOf) === Date.parse(point.time)
                ? 'fill-zoop-ink stroke-white stroke-2'
                : 'fill-zoop-up'
            }
          />
        </g>
      ))}
      {[...groups].map(([key, items]) => {
        // A bucket marker does not require a price bar at the event's time.
        // For coarse dates, use an existing matching price bucket rather than inventing an exact event time.
        const at =
          items.find(
            (item) =>
              item.timePrecision === 'datetime' && exactTime(item.eventTime),
          )?.eventTime ??
          points.find(
            (point) =>
              bucketKey(
                { eventTime: point.time, timePrecision: 'datetime' },
                period,
              ) === key,
          )?.time;
        if (!at || Date.parse(at) < start || Date.parse(at) > end) return null;
        const selected =
          selectedBucket === key ||
          (selectedEvent && bucketKey(selectedEvent, period) === key);
        const position = x(at);
        return (
          <g key={key}>
            {selected && (
              <line
                x1={position}
                x2={position}
                y1="15"
                y2="185"
                className="stroke-zoop-ink stroke-1"
                strokeDasharray="4 4"
              />
            )}
            <g
              role="button"
              tabIndex={0}
              aria-label={`차트 사건 ${key} · 사건 ${items.length}건`}
              aria-pressed={!!selected}
              className="cursor-pointer focus-visible:outline-2 focus-visible:outline-zoop-ink"
              onClick={() => onBucket(key)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  onBucket(key);
                }
              }}
            >
              <rect
                x={position - 12}
                y="0"
                width="24"
                height="15"
                rx="3"
                className="fill-zoop-ink"
              />
              <text
                x={position}
                y="11"
                textAnchor="middle"
                className="fill-white text-[10px]"
              >
                {items.length}
              </text>
            </g>
          </g>
        );
      })}
      <text x="12" y="205" className="fill-zoop-ink text-[10px]">
        {range.from}
      </text>
      <text
        x="588"
        y="205"
        textAnchor="end"
        className="fill-zoop-ink text-[10px]"
      >
        {range.to}
      </text>
    </svg>
  );
}
