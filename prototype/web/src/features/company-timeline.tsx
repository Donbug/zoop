// 기업 상세 사건 탭(요구 37·38·40·41, 명세 v1.2 FS040·D05).
//  - 기간(1일·1개월·1년, 기본 1개월)은 발생 시각 기준이며, 범위는 KST 조회 시각까지다(종료 시각 뒤 예정 사건은 없다).
//    발생 날짜를 모르는 사건은 보도 시각이 범위 안인 것만 맨 아래 '발생 시점 미상' 묶음에 따로 둔다.
//  - 같은 날짜의 사건이 여럿이면 날짜 묶음에 사건 수를 적고, 누르면 사건별 카드를 펼친다(사건을 합치지 않는다).
//  - 날짜 선택(FS041): 묶음을 펼치거나 차트의 사건 표시를 누르면 이전 상세·강조를 먼저 거둔다. 그 날짜(들)의 사건이 1건이면 바로 선택해
//    상세를 조회하고, 여러 건이면 카드를 펼쳐 두고 사용자가 고를 때까지 상세를 정하지 않는다.
//  - 사건 카드를 고르면 그 자리에서 상세가 열린다: 영향 경로(이 기업 ↔ 사건 ↔ 다른 기업 목록), 근거 문서, [지도에서 보기].
//  - 기간·선택·펼친 묶음은 페이지가 주소로 관리한다. 이 파일은 받은 값을 그리고 바뀔 값을 알린다.
//  - 주가 차트(company-price-chart)를 기간 도구 아래에 같은 기간·같은 거르기로 그리고, 선택한 사건의 발생 날짜를 차트에서 강조한다.
import { CalendarClock, ChevronDown, Clock, FileText, Map as MapIcon, MessageCircleQuestion, Newspaper, Route, Zap } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import type { Schemas } from "@/api/client";
import type { UseQueryResult } from "@tanstack/react-query";
import { useCompanies, useEvidenceItems } from "@/api/queries";
import { ApprovalNote, RoleUnconfirmed } from "@/components/domain/approval-note";
import { CompanyMark } from "@/components/domain/company-mark";
import { DocumentItem, documentRelationLabel } from "@/components/domain/document-item";
import { UnavailableEvidenceNote, isEvidenceGone } from "@/components/domain/evidence";
import { IconCount } from "@/components/domain/event-row";
import { EdgeGlyph } from "@/components/domain/relation-type-tag";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SkeletonLines, SkeletonRows } from "@/components/ui/feedback";
import { IconHint } from "@/components/ui/icon-hint";
import { Segmented } from "@/components/ui/segmented";
import { Tooltip } from "@/components/ui/tooltip";
import {
  eventEndDate,
  groupEvents,
  kstDate,
  periodLabel,
  periodPhrase,
  periods,
  widerPeriodFor,
  type DetailRange,
  type Period,
} from "@/lib/company-timeline";
import { assertionStatusLabel, formatEventTime, formatKst, relationLabel, type RelationType } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { CompanyPriceChart } from "./company-price-chart";

type Filter = "all" | "INVOLVES" | "STRUCTURALLY_RELATED_TO";

const filterOptions: { value: Filter; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "INVOLVES", label: relationLabel.INVOLVES },
  { value: "STRUCTURALLY_RELATED_TO", label: relationLabel.STRUCTURALLY_RELATED_TO },
];

const periodOptions = periods.map((p) => ({ value: p, label: periodLabel[p] }));

interface TimelineProps {
  companyId: string;
  /** 기업 조회가 끝나기 전에는 관계(직접·구조적) 표시와 거르기를 두지 않는다. */
  company: Schemas["CompanyDetail"] | undefined;
  events: UseQueryResult<Schemas["EventListResponse"]>;
  selectedEvent: UseQueryResult<Schemas["EventDetail"]>;
  /** 차트와 함께 쓰는 조회 범위(기간·공통 종료 시각) */
  range: DetailRange;
  onPeriodChange: (period: Period) => void;
  selectedId: string | null;
  onSelect: (eventId: string | null) => void;
  openGroups: ReadonlySet<string>;
  /** 날짜 묶음 펼침(expand)/접힘. 묶음의 사건 id를 함께 알려 이전 선택 정리에 쓴다. */
  onToggleGroup: (key: string, eventIds: string[], expand: boolean) => void;
  onShowOnMap: (event: Schemas["EventDetail"]) => void;
  onAsk: (event: Schemas["EventDetail"]) => void;
  /** 날짜 선택(차트 사건 표시): 묶음들을 펼치고, 그 날짜 사건이 1건이면 그 사건을 고른다. */
  onPickDate: (keys: string[], eventIds: string[]) => void;
}

export function CompanyTimeline(props: TimelineProps) {
  const { company, events, range, onPeriodChange, openGroups, onToggleGroup } = props;
  const { period, today } = range;
  const [filter, setFilter] = useState<Filter>("all");
  const [focusGroup, setFocusGroup] = useState<string | null>(null);

  const relationOf = new Map<string, RelationType>([
    ...(company?.structuralIssues ?? []).map((i) => [i.issueId, "STRUCTURALLY_RELATED_TO"] as const),
    ...(company?.directIssues ?? []).map((i) => [i.issueId, "INVOLVES"] as const),
  ]);

  const toolbar = (
    <div className="flex flex-col gap-2 md:flex-row md:items-center">
      <div className="flex items-center gap-1">
        <Segmented aria-label="조회 기간" value={period} onValueChange={onPeriodChange} options={periodOptions} fill className="min-w-0 flex-1 md:w-60 md:flex-none" />
        <IconHint icon={Clock} label="기간 기준">
          <p>지금(한국 시간)부터 거슬러 {periodLabel[period]} 안에 일어난 사건이에요. 1일은 오늘 0시부터예요.</p>
          <p>일어난 날짜를 확인하지 못한 사건은 기사가 이 기간에 보도된 것만 ‘발생 시점 미상’에 따로 모았어요. 보도 시각은 일어난 때가 아니에요.</p>
          {events.data && <p>자료 기준 {formatKst(events.data.metadata.asOf)}</p>}
        </IconHint>
      </div>
      {company && (
        <Segmented aria-label="관계로 거르기" value={filter} onValueChange={setFilter} options={filterOptions} fill className="md:w-auto md:flex-none" />
      )}
    </div>
  );

  // 차트 표시용 날짜 묶음: 타임라인과 같은 거르기를 거친, 발생 시각이 있는 사건만.
  const keepRelation = (e: Schemas["EventSummary"]) => filter === "all" || relationOf.get(e.id) === filter;
  const chartGroups = events.data ? groupEvents(events.data.items.filter(keepRelation), []) : [];

  let body;
  if (events.isPending) body = <SkeletonRows count={3} label="사건 목록을 불러오고 있어요" />;
  else if (events.isError) body = <ErrorState error={events.error} title="사건 목록을 불러오지 못했어요" onRetry={() => void events.refetch()} />;
  else {
    const items = events.data.items.filter(keepRelation);
    const undated = events.data.unknownTimeItems.filter(keepRelation);
    const groups = groupEvents(items, undated);
    const hasMixedRelations = new Set([...items, ...undated].map((e) => relationOf.get(e.id))).size > 1;
    const total = items.length + undated.length;

    if (total === 0 && filter !== "all") {
      body = (
        <EmptyState
          title="이 관계의 사건이 없어요"
          action={
            <Button variant="secondary" onClick={() => setFilter("all")}>
              전체 보기
            </Button>
          }
        />
      );
    } else if (total === 0) {
      body = <PeriodEmpty meta={events.data.metadata} period={period} today={today} onPeriodChange={onPeriodChange} />;
    } else {
      body = (
        <>
          <p className="text-sm text-text-secondary tabular-nums" aria-live="polite">
            {periodLabel[period]} · 사건 {total}건
          </p>
          <ol aria-label={`${company?.name ?? "이 기업"} 사건 타임라인`}>
            {groups.map((group) => {
              const multi = group.items.length > 1;
              const expanded = !multi || openGroups.has(group.key) || groups.length === 1 || group.items.some((e) => e.id === props.selectedId);
              const listId = `group-${group.key}`;
              return (
                <li
                  key={group.key}
                  data-group-key={group.key}
                  tabIndex={-1}
                  className="grid scroll-mt-16 grid-cols-1 gap-x-3 border-b border-border-subtle last:border-b-0 md:grid-cols-[8rem_minmax(0,1fr)]"
                >
                  <div className="flex items-center gap-1 px-3 pt-3 text-sm text-text-secondary tabular-nums md:items-start md:px-0 md:pt-4">
                    {group.unknown ? (
                      <>
                        <span>{group.label}</span>
                        <IconHint icon={CalendarClock} label="발생 시점 미상">
                          <p>일어난 날짜를 확인하지 못한 사건이에요. 보도 시각이 이 기간 안이라 함께 보여 드려요. 보도 시각은 사건이 일어난 때가 아니에요.</p>
                        </IconHint>
                      </>
                    ) : (
                      <time dateTime={group.items[0]!.eventTime ?? undefined}>{group.label}</time>
                    )}
                  </div>
                  <div className="min-w-0">
                    {multi && (
                      <button
                        type="button"
                        aria-expanded={expanded}
                        aria-controls={listId}
                        onClick={() => onToggleGroup(group.key, group.items.map((e) => e.id), !expanded)}
                        className="flex min-h-12 w-full items-center gap-2 px-3 py-3 text-left text-base transition-token hover:bg-surface-sunken"
                      >
                        <Zap className="size-4 shrink-0 text-text-secondary" aria-hidden="true" />
                        <span className="font-semibold text-text-primary tabular-nums">사건 {group.items.length}건</span>
                        {!expanded && <span className="min-w-0 flex-1 truncate text-text-secondary">{group.items[0]!.title}</span>}
                        <ChevronDown
                          className={cn("ml-auto size-5 shrink-0 text-text-secondary transition-transform duration-(--zoop-motion-duration-d4) ease-standard", expanded && "rotate-180")}
                          aria-hidden="true"
                        />
                      </button>
                    )}
                    {expanded && (
                      <ol id={listId} className={cn(multi && "stagger divide-y divide-border-subtle border-t border-border-subtle")}>
                        {group.items.map((e) => (
                          <li key={e.id}>
                            <EventCard
                              {...props}
                              summary={e}
                              undated={group.unknown}
                              relationType={hasMixedRelations ? relationOf.get(e.id) : undefined}
                            />
                          </li>
                        ))}
                      </ol>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        </>
      );
    }
  }

  // 차트 위 사건 표시: 날짜를 고르고(1건이면 선택, 여러 건이면 펼침) 그 묶음이 그려진 뒤 그 묶음으로 옮겨 포커스한다.
  const pickGroups = (keys: string[]) => {
    const picked = chartGroups.filter((g) => keys.includes(g.key)).flatMap((g) => g.items.map((e) => e.id));
    setFocusGroup(keys[0]!);
    props.onPickDate(keys, picked);
  };
  const selectedKey = chartGroups.find((g) => g.items.some((e) => e.id === props.selectedId))?.key ?? null;
  useEffect(() => {
    if (!focusGroup || !openGroups.has(focusGroup)) return;
    const target = document.querySelector<HTMLElement>(`[data-group-key="${CSS.escape(focusGroup)}"]`);
    setFocusGroup(null);
    if (!target) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    target.scrollIntoView({ block: "start", behavior: reduce ? "auto" : "smooth" });
    target.focus({ preventScroll: true });
  }, [focusGroup, openGroups]);

  return (
    <div className="flex flex-col gap-3 pt-2">
      <h2 className="sr-only">사건 타임라인</h2>
      {toolbar}
      <CompanyPriceChart companyId={props.companyId} range={range} groups={chartGroups} onPick={pickGroups} selectedKey={selectedKey} />
      {body}
    </div>
  );
}

/** 이 기간에 사건이 없을 때: 가장 최근 사건(없으면 가장 최근 보도) 날짜와, 그 날짜가 들어가는 더 넓은 기간으로 옮기는 버튼. */
function PeriodEmpty({ meta, period, today, onPeriodChange }: { meta: Schemas["EventListMetadata"]; period: Period; today: string; onPeriodChange: (p: Period) => void }) {
  const latestEvent = eventEndDate(meta.latestEventTime);
  const latestReport = meta.latestReportedAt ? kstDate(meta.latestReportedAt) : null;
  if (!latestEvent && !latestReport) return <EmptyState title="이 기업과 연결된 사건이 없어요" description="검증을 통과한 사건이 생기면 이곳에 보여 드려요." />;
  const anchor = [latestEvent, latestReport].filter((d): d is string => Boolean(d)).sort().at(-1)!;
  const wider = widerPeriodFor(anchor, period, today);
  const description = latestEvent
    ? `가장 최근 사건은 ${latestEvent}에 일어났어요.`
    : `일어난 때를 확인한 사건은 없고, 가장 최근 보도는 ${latestReport}이에요.`;
  return (
    <EmptyState
      title={`${periodPhrase[period]} 일어난 사건이 없어요`}
      description={description}
      action={
        wider && (
          <Button variant="secondary" onClick={() => onPeriodChange(wider)}>
            <CalendarClock aria-hidden="true" />
            {periodLabel[wider]}
            {wider === "1y" ? "으로" : "로"} 넓혀 보기
          </Button>
        )
      }
    />
  );
}

function EventCard({
  summary,
  undated,
  relationType,
  selectedId,
  onSelect,
  ...rest
}: TimelineProps & { summary: Schemas["EventSummary"]; undated: boolean; relationType?: RelationType }) {
  const selected = selectedId === summary.id;
  const detailId = `event-detail-${summary.id}`;
  return (
    <article id={`event-${summary.id}`} className={cn("flex flex-col gap-1.5 px-3 py-4", selected && "bg-surface-selected")}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-text-secondary">
        {undated && (
          <span className="tabular-nums">
            보도 <time dateTime={summary.reportedAt ?? undefined}>{summary.reportedAt ? kstDate(summary.reportedAt) : "시각 미상"}</time>
          </span>
        )}
        {relationType && (
          <Tooltip content={relationLabel[relationType]}>
            <span tabIndex={0} role="img" aria-label={`관계: ${relationLabel[relationType]}`} className="inline-flex rounded-sm">
              <EdgeGlyph type={relationType} className="w-6" />
            </span>
          </Tooltip>
        )}
        <IconCount icon={Newspaper} label="근거 문서" count={summary.articleCount} />
      </div>
      <h3 className="text-base leading-snug">
        <button
          type="button"
          aria-expanded={selected}
          aria-controls={selected ? detailId : undefined}
          onClick={() => onSelect(selected ? null : summary.id)}
          className={cn("min-h-11 w-full text-left text-text-primary underline-offset-4 hover:underline", selected ? "font-semibold" : "font-medium")}
        >
          {summary.title}
        </button>
      </h3>
      {summary.target && <p className="line-clamp-2 text-sm text-text-secondary">{summary.target}</p>}
      {selected && <EventDetailPanel id={detailId} {...rest} summary={summary} />}
    </article>
  );
}

function EventDetailPanel({
  id,
  companyId,
  company,
  selectedEvent,
  summary,
  onShowOnMap,
  onAsk,
}: Pick<TimelineProps, "companyId" | "company" | "selectedEvent" | "onShowOnMap" | "onAsk"> & { id: string; summary: Schemas["EventSummary"] }) {
  const event = selectedEvent.data;
  const companyIds = event ? event.companies.map((c) => c.id) : [];
  const marks = useCompanies(companyIds);
  const evidence = useEvidenceItems(event?.evidenceIds ?? []);

  if (selectedEvent.isPending) return <div id={id}><SkeletonLines lines={3} label="사건 상세를 불러오고 있어요" /></div>;
  if (selectedEvent.isError || !event)
    return (
      <div id={id}>
        <ErrorState compact error={selectedEvent.error} title="사건 상세를 불러오지 못했어요" onRetry={() => void selectedEvent.refetch()} />
      </div>
    );

  const markOf = (cid: string) => marks[companyIds.indexOf(cid)]?.data;
  const self = event.companies.find((c) => c.id === companyId);
  const others = event.companies.filter((c) => c.id !== companyId);
  const selfName = self?.name ?? company?.name ?? companyId;
  const quotesByArticle = new Map<string, { id: string; quote: string; quoteVerified: boolean | null }[]>();
  for (const q of evidence) {
    if (!q.data) continue;
    const list = quotesByArticle.get(q.data.articleId) ?? [];
    list.push({ id: q.data.id, quote: q.data.quote, quoteVerified: q.data.quoteVerified });
    quotesByArticle.set(q.data.articleId, list);
  }
  // 일시 장애만 다시 시도한다. 지워졌거나(404) 볼 권한이 없는(403) 인용은 건수만 알리고 문서(제목·출처)는 사건 상세 값으로 그대로 둔다.
  const evidenceFailed = evidence.filter((q) => q.isError && !isEvidenceGone(q.error));
  const evidenceGone = evidence.filter((q) => q.isError && isEvidenceGone(q.error)).length;
  const statusOf = (c: Schemas["CompanyLink"]) => event.relations.find((r) => r.source === event.id && r.target === c.id)?.assertionStatus;

  const pathRow = (c: Schemas["CompanyLink"], isSelf: boolean) => {
    const mark = markOf(c.id);
    const status = statusOf(c);
    const name = isSelf ? (
      <span className="font-semibold text-text-primary">{c.name}</span>
    ) : (
      <Link to={`/companies/${encodeURIComponent(c.id)}`} className="font-medium text-text-primary underline underline-offset-4">
        {c.name}
      </Link>
    );
    return (
      <li key={c.id} className="relative flex items-start gap-3 py-2 before:absolute before:top-0 before:bottom-0 before:left-3 before:w-px before:bg-border-subtle first:before:top-1/2 last:before:bottom-1/2">
        <CompanyMark id={c.id} name={c.name} brandColor={mark?.brandColor} logoUrl={mark?.logoUrl} size={24} className="relative" />
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <p className="flex flex-wrap items-center gap-x-2 text-base">
            {name}
            {isSelf && <span className="text-sm text-text-secondary">이 기업</span>}
          </p>
          <p className="flex flex-wrap items-center gap-x-2 text-sm text-text-secondary">
            <EdgeGlyph type={c.relationType} className="w-6" />
            <span>{relationLabel[c.relationType]}</span>
            {c.role ? <span>· {c.role}</span> : c.roleUnconfirmed && <span className="inline-flex items-center gap-1">· <RoleUnconfirmed /></span>}
            {status && <span>· {assertionStatusLabel(status)}</span>}
          </p>
        </div>
      </li>
    );
  };

  return (
    <div id={id} className="mt-2 flex flex-col gap-4 border-t border-border-subtle pt-4">
      <p className="text-sm text-text-secondary tabular-nums">
        {event.timePrecision === "unknown"
          ? `발생 시점 미상 · 최근 보도 ${summary.reportedAt ? formatKst(summary.reportedAt) : "시각 미상"}`
          : `발생 ${formatEventTime(event.eventTime, event.timePrecision)}${event.timePrecision === "day" ? " · 시각 미상" : ""}`}
        {event.period ? ` · 대상 기간 ${event.period}` : ""}
      </p>
      <ApprovalNote approval={event.approval} />

      <section aria-labelledby={`${id}-path`} className="flex flex-col gap-1">
        <h4 id={`${id}-path`} className="flex items-center gap-2 text-base font-semibold text-text-primary">
          <Route className="size-4 text-text-secondary" aria-hidden="true" />
          영향 경로
        </h4>
        <ol aria-label={`${selfName}에서 사건을 거쳐 이어지는 기업`}>
          {self && pathRow(self, true)}
          <li className="relative flex items-start gap-3 py-2 before:absolute before:top-0 before:bottom-0 before:left-3 before:w-px before:bg-border-subtle last:before:bottom-1/2">
            <span className="relative flex size-6 shrink-0 items-center justify-center rounded-full bg-graph-node-issue text-graph-node-glyph">
              <Zap className="size-3.5" aria-hidden="true" />
            </span>
            <p className="min-w-0 flex-1 text-base font-medium text-text-primary">{event.title}</p>
          </li>
          {others.map((c) => pathRow(c, false))}
        </ol>
        {others.length === 0 && <p className="text-sm text-text-secondary">이 사건에 연결된 다른 기업은 없어요.</p>}
      </section>

      <section aria-labelledby={`${id}-docs`} className="flex flex-col gap-2">
        <h4 id={`${id}-docs`} className="flex items-center gap-2 text-base font-semibold text-text-primary tabular-nums">
          <FileText className="size-4 text-text-secondary" aria-hidden="true" />
          근거 문서 {event.articles.length}건
        </h4>
        {evidenceFailed.length > 0 && (
          <ErrorState
            compact
            error={evidenceFailed[0]!.error}
            title="인용 일부를 불러오지 못했어요"
            onRetry={() => evidenceFailed.forEach((q) => void q.refetch())}
          />
        )}
        {evidenceGone > 0 && <UnavailableEvidenceNote count={evidenceGone} />}
        {event.articles.length === 0 ? (
          <p className="text-sm text-text-secondary">연결된 근거 문서가 없어요.</p>
        ) : (
          <ol className="flex flex-col divide-y divide-border-subtle">
            {event.articles.map((a) => (
              <li key={a.id} className="py-3 first:pt-0">
                <DocumentItem
                  headingLevel="h4"
                  title={a.title}
                  publisher={a.publisher}
                  url={a.url}
                  publishedAt={a.publishedAt}
                  relation={a.relationType ? documentRelationLabel[a.relationType] : undefined}
                  quotes={quotesByArticle.get(a.id)}
                />
              </li>
            ))}
          </ol>
        )}
      </section>

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" onClick={() => onShowOnMap(event)}>
          <MapIcon aria-hidden="true" />
          지도에서 보기
        </Button>
        <Button variant="ghost" onClick={() => onAsk(event)}>
          <MessageCircleQuestion aria-hidden="true" />
          AI에게 묻기
        </Button>
      </div>
    </div>
  );
}
