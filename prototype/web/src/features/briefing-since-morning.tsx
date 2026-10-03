// 퇴근 브리핑의 「아침 이후 바뀐 내용」(화면계획서 M-BRF-01). 같은 날 발행된 출근 회차와 이슈 ID로 견준 결과를 시간순으로 보인다.
//  - 신규: 아침 핵심 이슈에 없던 이슈 / 이어짐: 아침에도 있던 이슈(아침 뒤 새 근거가 붙어 이 회차 범위에 들어옴) / 빠짐: 아침에만 있던 이슈.
//  - 상태는 색이 아니라 글자 표지(아이콘 + 신규·이어짐·빠짐)로 구분한다.
//  - 출근 회차가 없거나 쓸 수 없으면 이유 한 줄만 보인다.
import { Info, Minus, Plus, Repeat2, GitCompareArrows, type LucideIcon } from "lucide-react";
import { useId } from "react";
import { Link } from "react-router";
import type { Schemas } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { kstClock, monthDay } from "@/lib/briefing-market";
import { formatEventTime } from "@/lib/labels";

type Since = NonNullable<Schemas["BriefingResponse"]["sinceMorning"]>;
type Item = Extract<Since, { status: "available" }>["items"][number];

const changeMark: Record<Item["change"], { label: string; icon: LucideIcon }> = {
  new: { label: "신규", icon: Plus },
  continuing: { label: "이어짐", icon: Repeat2 },
  dropped: { label: "빠짐", icon: Minus },
};

/** 보도 시각 칸. 앞에 '보도'를 붙여 이슈 카드의 사건 날짜와 기준이 다름을 밝힌다: 같은 날이면 `보도 17:00`, 다른 날이면
 *  `보도 9월 17일` + 시각, 날짜만 알면 날짜만(0시로 그리지 않음), 없으면 `보도 시각 미상`. */
function ReportedAt({ iso, roundDate }: { iso: string | null; roundDate: string }) {
  if (!iso) return <span className="w-24 shrink-0 text-sm text-text-secondary">보도 시각 미상</span>;
  const date = iso.slice(0, 10);
  const time = iso.length > 10 ? kstClock(iso) : null;
  const sameDay = date === roundDate;
  return (
    <time dateTime={iso} className="flex w-24 shrink-0 flex-col text-sm text-text-secondary tabular-nums">
      <span>{sameDay && time ? `보도 ${time}` : `보도 ${monthDay(date)}`}</span>
      {!sameDay && time && <span>{time}</span>}
    </time>
  );
}

/** 둘째 줄. 제목이 같은 이슈가 목록에 여럿이면(같은 기사에서 나온 서로 다른 이슈) 이미 가진 구분 정보인 관련 기업·발생 시각을 앞에 붙인다. */
function detailText(item: Item, sharesTitle: boolean) {
  let evidence = `근거 ${item.evidenceCount}건`;
  if (item.change === "dropped") evidence = `이번 회차 핵심 이슈에는 없어요 · 근거 ${item.morningEvidenceCount}건`;
  else if (item.change === "continuing" && item.morningEvidenceCount !== item.evidenceCount) evidence = `근거 ${item.morningEvidenceCount}건 → ${item.evidenceCount}건`;
  if (!sharesTitle) return evidence;
  const names = item.companyNames;
  const companies = names.length > 0 ? `관련 기업 ${names.slice(0, 3).join(", ")}${names.length > 3 ? ` 외 ${names.length - 3}곳` : ""}` : null;
  const happened = item.eventTime && item.timePrecision !== "unknown" ? `발생 ${formatEventTime(item.eventTime, item.timePrecision)}` : formatEventTime(null, null);
  return [companies, happened, evidence].filter(Boolean).join(" · ");
}

export function SinceMorningSection({
  since,
  roundId,
  roundDate,
  graphHref,
}: {
  since: Since;
  /** 이 퇴근 회차 id */
  roundId: string;
  roundDate: string;
  /** 그 회차 기준 관계 그래프 주소 */
  graphHref: (roundId: string, eventId: string) => string;
}) {
  const titleId = useId();
  if (since.status === "unavailable") {
    return (
      <p className="flex items-center gap-2 border-t border-border-subtle py-3 text-sm text-text-secondary">
        <Info className="size-4 shrink-0" aria-hidden="true" />
        {since.reason}
      </p>
    );
  }
  const titleCount = new Map<string, number>();
  for (const item of since.items) titleCount.set(item.title, (titleCount.get(item.title) ?? 0) + 1);
  return (
    <section aria-labelledby={titleId} className="border-t border-border-subtle pt-4">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <h3 id={titleId} className="flex items-center gap-2 text-base font-semibold text-text-primary">
          <GitCompareArrows className="size-5 text-text-secondary" aria-hidden="true" />
          아침 이후 바뀐 내용
          <span className="font-normal text-text-secondary tabular-nums">{since.items.length}건</span>
        </h3>
        <Button variant="link" size="sm" asChild>
          <Link to={`/briefing?date=${roundDate}&edition=morning`}>출근 브리핑 보기</Link>
        </Button>
      </div>
      {since.items.length === 0 ? (
        <p className="py-3 text-sm text-text-secondary">출근 브리핑과 달라진 핵심 이슈가 없어요.</p>
      ) : (
        <ol className="stagger">
          {since.items.map((item) => {
            const mark = changeMark[item.change];
            const Icon = mark.icon;
            return (
              <li key={item.eventId} className="flex gap-3 border-b border-border-subtle py-3 last:border-b-0">
                <ReportedAt iso={item.reportedAt} roundDate={roundDate} />
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <div className="flex flex-wrap items-start gap-x-2 gap-y-1">
                    <Badge>
                      <Icon aria-hidden="true" />
                      {mark.label}
                    </Badge>
                    <Link
                      to={graphHref(item.change === "dropped" ? since.morningRoundId : roundId, item.eventId)}
                      className="min-w-0 flex-1 text-base font-medium text-text-primary underline decoration-border-strong underline-offset-4 hover:decoration-text-primary"
                    >
                      {item.title}
                    </Link>
                  </div>
                  <p className="text-sm text-text-secondary">{detailText(item, (titleCount.get(item.title) ?? 0) > 1)}</p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
