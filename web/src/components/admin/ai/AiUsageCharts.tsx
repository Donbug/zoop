import { useRef, useState } from 'react';
import { Empty, Note, Table } from '@/components/admin/common/AdminUi';
import { TD, TH, count } from '@/components/admin/common/adminStyles';
import {
  sum,
  type AiUsageView,
  type DayTotals,
} from '@/components/admin/ai/aiUsageModel';
import type { AiFeatureUsage, AiUsageMembers } from '@/types/admin/briefings';

// A-ADM-04b AI 사용량 그래프 (강사 피드백 2026-10-24: 전체 회원 대비 AI 사용 비율, 날짜별 토큰, 브리핑·챗봇 비용 분리)
// - 색은 무채색 zoop 토큰만 쓴다. 입력 토큰은 zoop-ink, 출력 토큰은 zoop-line이고 범례·표 보기로 색에만 기대지 않는다.
// - 모르는 값(null)은 0으로 그리지 않고 '자료 없음'으로 둔다.

const compact = new Intl.NumberFormat('ko-KR', {
  notation: 'compact',
  maximumFractionDigits: 1,
});
const percent = new Intl.NumberFormat('ko-KR', {
  style: 'percent',
  maximumFractionDigits: 1,
});

const shortDate = (date: string) => {
  const [, month, day] = date.split('-');
  return `${Number(month)}/${Number(day)}`;
};
const longDate = (date: string) => {
  const [, month, day] = date.split('-');
  return `${Number(month)}월 ${Number(day)}일`;
};
const money = (value: number, currency: string | null) =>
  `${value.toLocaleString('ko-KR', { maximumFractionDigits: 4 })}${currency ? ` ${currency}` : ''}`;

/** 눈금이 깔끔하게 떨어지는 최댓값(1·2·5 × 10^n) */
function niceMax(value: number) {
  if (value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 5, 10].find((m) => m * power >= value) ?? 10;
  return step * power;
}

const W = 640;
const H = 180;
const PAD = { left: 44, right: 8, top: 10, bottom: 24 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

/** 아래는 막대 바닥, 위쪽 두 모서리만 4px 둥글린 막대 */
function topRounded(x: number, y: number, width: number, height: number) {
  const r = Math.min(4, width / 2, height);
  return `M${x},${y + height}V${y + r}Q${x},${y} ${x + r},${y}H${x + width - r}Q${x + width},${y} ${x + width},${y + r}V${y + height}Z`;
}

type Segment = { value: number | null; className: string };

/**
 * 날짜별 막대 그래프. segments를 아래에서 위로 쌓고, 조각 사이에 2px 틈을 둔다.
 * 막대마다 막대보다 넓은 투명 영역이 있어 마우스·키보드 포커스로 값을 본다.
 */
function DayBars({
  label,
  days,
  segments,
  describe,
  tick,
}: {
  label: string;
  days: string[];
  segments: (index: number) => Segment[];
  describe: (index: number) => string[];
  tick: (value: number) => string;
}) {
  const [active, setActive] = useState<number | null>(null);
  // 키보드: 그래프 전체가 Tab 한 칸이고, 그 안에서 ←→·Home·End로 날짜를 옮긴다(날짜마다 Tab 칸을 만들지 않는다).
  const [cursor, setCursor] = useState<number | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const totals = days.map((_, index) =>
    segments(index).reduce((total, part) => total + (part.value ?? 0), 0),
  );
  const max = niceMax(Math.max(0, ...totals));
  const slot = PLOT_W / Math.max(1, days.length);
  const barWidth = Math.max(2, Math.min(28, slot * 0.6));
  const y = (value: number) => PAD.top + PLOT_H - (value / max) * PLOT_H;
  const labelEvery = Math.ceil(days.length / 8);

  // 고른 날(없으면 마지막 날)의 값을 그래프 위 한 줄에 보여 준다.
  const focusIndex = Math.min(cursor ?? days.length - 1, days.length - 1);
  const shown = active ?? focusIndex;
  const move = (next: number) => {
    const index = Math.max(0, Math.min(days.length - 1, next));
    setCursor(index);
    setActive(index);
    svg.current
      ?.querySelector<SVGRectElement>(`[data-day-index="${index}"]`)
      ?.focus();
  };
  return (
    <div className="flex flex-col gap-1">
      <p
        aria-live="polite"
        className="min-h-4 text-[11px] text-zoop-muted tabular-nums"
      >
        {shown >= 0 && (
          <>
            <span className="font-semibold text-zoop-ink">
              {longDate(days[shown])}
            </span>{' '}
            {describe(shown).join(' · ')}
          </>
        )}
      </p>
      {/* 좁은 창에서는 그래프를 줄이지 않고 가로로 넘긴다. 줄이면 축 글씨(10px)가 함께 작아진다. */}
      <div className="overflow-x-auto">
        <svg
          ref={svg}
          viewBox={`0 0 ${W} ${H}`}
          role="group"
          aria-label={`${label} (←→로 날짜 이동)`}
          className="block h-auto w-full min-w-[560px] overflow-visible"
          onMouseLeave={() => setActive(null)}
          onKeyDown={(event) => {
            const keys: Record<string, number> = {
              ArrowLeft: focusIndex - 1,
              ArrowRight: focusIndex + 1,
              Home: 0,
              End: days.length - 1,
            };
            if (!(event.key in keys)) return;
            event.preventDefault();
            move(keys[event.key]);
          }}
        >
          {[0, 0.5, 1].map((ratio) => (
            <g key={ratio}>
              <line
                x1={PAD.left}
                x2={W - PAD.right}
                y1={y(max * ratio)}
                y2={y(max * ratio)}
                className="stroke-zoop-line"
                strokeWidth={ratio === 0 ? 1 : 0.5}
                strokeDasharray={ratio === 0 ? undefined : '2 3'}
              />
              <text
                x={PAD.left - 6}
                y={y(max * ratio)}
                textAnchor="end"
                dominantBaseline="middle"
                className="fill-zoop-muted text-[10px] tabular-nums"
              >
                {tick(max * ratio)}
              </text>
            </g>
          ))}
          {days.map((date, index) => {
            const x = PAD.left + slot * index + (slot - barWidth) / 2;
            const parts = segments(index).filter(
              (part): part is { value: number; className: string } =>
                part.value !== null && part.value > 0,
            );
            let base = 0;
            return (
              <g key={date}>
                {parts.map((part, partIndex) => {
                  const top = y(base + part.value);
                  const bottom = y(base) - (partIndex > 0 ? 2 : 0);
                  base += part.value;
                  const height = Math.max(0, bottom - top);
                  return partIndex === parts.length - 1 ? (
                    <path
                      key={partIndex}
                      d={topRounded(x, top, barWidth, height)}
                      className={part.className}
                    />
                  ) : (
                    <rect
                      key={partIndex}
                      x={x}
                      y={top}
                      width={barWidth}
                      height={height}
                      className={part.className}
                    />
                  );
                })}
                {index % labelEvery === 0 && (
                  <text
                    x={PAD.left + slot * index + slot / 2}
                    y={H - 6}
                    textAnchor="middle"
                    className="fill-zoop-muted text-[10px] tabular-nums"
                  >
                    {shortDate(date)}
                  </text>
                )}
                {active === index && (
                  // 고른 날: 옅은 바탕만으로는 잘 안 보여 진한 테두리를 함께 그린다.
                  <rect
                    aria-hidden="true"
                    x={PAD.left + slot * index + 1}
                    y={PAD.top}
                    width={Math.max(1, slot - 2)}
                    height={PLOT_H}
                    rx={3}
                    className="pointer-events-none fill-zoop-ink/5 stroke-zoop-ink"
                    strokeWidth={1.5}
                  />
                )}
                <rect
                  data-day-index={index}
                  x={PAD.left + slot * index}
                  y={PAD.top}
                  width={slot}
                  height={PLOT_H}
                  tabIndex={index === focusIndex ? 0 : -1}
                  role="img"
                  aria-label={`${longDate(date)} ${describe(index).join(', ')}`}
                  onMouseEnter={() => setActive(index)}
                  onFocus={() => {
                    setCursor(index);
                    setActive(index);
                  }}
                  onBlur={() => setActive(null)}
                  className="fill-transparent outline-none"
                />
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

function Legend({ items }: { items: { label: string; swatch: string }[] }) {
  return (
    <ul className="flex flex-wrap items-center gap-4 text-[11px] text-zoop-muted">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className={`inline-block size-2.5 rounded-[2px] ${item.swatch}`}
          />
          {item.label}
        </li>
      ))}
    </ul>
  );
}

const tokenLine = (label: string, value: number | null) =>
  `${label} ${value === null ? '자료 없음' : count(value)}`;

/** 날짜별 입력·출력 토큰(쌓은 막대) */
export function DailyTokenChart({
  title,
  days,
}: {
  title: string;
  days: DayTotals[];
}) {
  if (days.every((day) => day.input === null && day.output === null))
    return <Empty>이 기간에 기록된 토큰 사용량이 없어요.</Empty>;
  return (
    <div className="flex flex-col gap-3">
      <Legend
        items={[
          { label: '입력 토큰', swatch: 'bg-zoop-ink' },
          { label: '출력 토큰', swatch: 'bg-zoop-line' },
        ]}
      />
      <DayBars
        label={title}
        days={days.map((day) => day.date)}
        segments={(index) => [
          { value: days[index].input, className: 'fill-zoop-ink' },
          { value: days[index].output, className: 'fill-zoop-line' },
        ]}
        describe={(index) => {
          const day = days[index];
          return [
            tokenLine('입력', day.input),
            tokenLine('출력', day.output),
            tokenLine('모델 호출', day.calls),
          ];
        }}
        tick={(value) => compact.format(value)}
      />
      <details className="text-[11px]">
        <summary className="cursor-pointer text-zoop-muted">표로 보기</summary>
        <Table caption={`${title} 표`}>
          <thead>
            <tr>
              <th className={TH}>날짜</th>
              <th className={`${TH} text-right`}>모델 호출</th>
              <th className={`${TH} text-right`}>입력 토큰</th>
              <th className={`${TH} text-right`}>출력 토큰</th>
            </tr>
          </thead>
          <tbody>
            {days.map((day) => (
              <tr key={day.date}>
                <td className={`${TD} font-inter tabular-nums`}>{day.date}</td>
                <td className={`${TD} text-right tabular-nums`}>
                  {count(day.calls)}
                </td>
                <td className={`${TD} text-right tabular-nums`}>
                  {count(day.input)}
                </td>
                <td className={`${TD} text-right tabular-nums`}>
                  {count(day.output)}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      </details>
    </div>
  );
}

/** 날짜별 비용(막대 하나). 실제 청구액이 있는 날은 실제, 없으면 추정이라고 적는다. */
export function DailyCostChart({
  title,
  days,
  currency,
}: {
  title: string;
  days: DayTotals[];
  currency: string | null;
}) {
  if (days.every((day) => day.cost === null))
    return (
      <Empty>
        이 기간의 비용 자료가 없어요. 모델 호출 비용은 0으로 채우지 않아요.
      </Empty>
    );
  const kinds = new Set(days.map((day) => day.costKind).filter(Boolean));
  return (
    <div className="flex flex-col gap-3">
      <Note>
        {kinds.size > 1 || kinds.has('mixed')
          ? '실제 청구액이 있는 기능은 실제, 없는 기능은 추정 비용으로 더했어요.'
          : kinds.has('actual')
            ? '실제 청구 비용이에요.'
            : '추정 비용이에요. 실제 청구액과 다를 수 있어요.'}
        {currency && ` 단위 ${currency}`}
      </Note>
      <DayBars
        label={title}
        days={days.map((day) => day.date)}
        segments={(index) => [
          { value: days[index].cost, className: 'fill-zoop-ink' },
        ]}
        describe={(index) => {
          const day = days[index];
          return [
            day.cost === null
              ? '비용 자료 없음'
              : `${day.costKind === 'actual' ? '실제' : day.costKind === 'mixed' ? '실제+추정' : '추정'} ${money(day.cost, currency)}`,
          ];
        }}
        tick={(value) =>
          value.toLocaleString('ko-KR', { maximumFractionDigits: 2 })
        }
      />
    </div>
  );
}

/** 0..1 비율 막대. 폭은 SVG 속성으로 정한다(인라인 style을 쓰지 않는다). */
function Bar({ ratio }: { ratio: number | null }) {
  return (
    <svg
      aria-hidden="true"
      className="block h-2 w-full"
      preserveAspectRatio="none"
    >
      <rect width="100%" height="100%" rx={4} className="fill-zoop-soft" />
      {ratio !== null && ratio > 0 && (
        <rect
          width={`${Math.min(100, ratio * 100)}%`}
          height="100%"
          rx={4}
          className="fill-zoop-ink"
        />
      )}
    </svg>
  );
}

/** 전체 회원 대비 AI를 쓴 회원 비율. 회원 수를 모르면 비율을 만들지 않는다. */
export function MemberRate({
  members,
  view,
}: {
  members: AiUsageMembers;
  view: AiUsageView;
}) {
  const used =
    view === 'chatbot'
      ? members.chatbotMembers
      : view === 'briefing'
        ? members.briefingMembers
        : members.aiMembers;
  const subject =
    view === 'chatbot' ? 'AI 챗봇' : view === 'briefing' ? '브리핑' : 'AI 기능';
  const rate =
    used !== null && members.totalMembers > 0
      ? used / members.totalMembers
      : null;
  return (
    <div className="flex flex-col gap-2">
      <dl className="flex flex-wrap items-end gap-x-6 gap-y-1">
        <div className="flex flex-col gap-1">
          <dt className="text-[11px] text-zoop-muted">
            {subject}을 쓴 회원 비율
          </dt>
          <dd className="text-2xl font-[750] tracking-[-0.03em] tabular-nums">
            {rate === null ? '–' : percent.format(rate)}
          </dd>
        </div>
        <div className="flex flex-col gap-1 pb-1">
          <dt className="sr-only">회원 수</dt>
          <dd className="text-xs text-zoop-muted tabular-nums">
            {used === null ? '측정 안 함' : `${count(used)}명`} / 전체{' '}
            {count(members.totalMembers)}명
          </dd>
        </div>
      </dl>
      {rate !== null && (
        <div
          role="meter"
          aria-label={`${subject}을 쓴 회원 비율`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(rate * 1000) / 10}
          className="w-full max-w-md"
        >
          <Bar ratio={rate} />
        </div>
      )}
      {members.note && <Note>{members.note}</Note>}
    </div>
  );
}

/** 전체 화면: 기능별 토큰(입력+출력) 비중. 토큰을 모르는 기능은 따로 적는다. */
export function FeatureShare({ features }: { features: AiFeatureUsage[] }) {
  const rows = features
    .map((feature) => ({
      feature,
      tokens: sum([feature.usage.inputTokens, feature.usage.outputTokens]),
    }))
    .sort((a, b) => (b.tokens ?? -1) - (a.tokens ?? -1));
  const total = rows.reduce((value, row) => value + (row.tokens ?? 0), 0);
  if (total === 0) return <Empty>이 기간에 기록된 토큰 사용량이 없어요.</Empty>;
  return (
    <ul aria-label="기능별 토큰 비중" className="flex flex-col gap-2.5">
      {rows.map(({ feature, tokens }) => (
        <li
          key={feature.feature}
          className="grid grid-cols-[8rem_minmax(0,1fr)_7rem] items-center gap-3 text-xs"
        >
          <span className="truncate font-semibold">{feature.label}</span>
          <Bar ratio={tokens === null ? null : tokens / total} />
          <span className="text-right text-zoop-muted tabular-nums">
            {tokens === null
              ? '자료 없음'
              : `${percent.format(tokens / total)} · ${compact.format(tokens)}`}
          </span>
        </li>
      ))}
    </ul>
  );
}
