// UI-08 출퇴근 브리핑(요구 26–31). 발행된 공통 회차를 날짜·출근/퇴근으로 골라 본다(모두에게 같은 발행본).
// 머리에 발행일·구분·예정/발행 시각·데이터 기준 시점, 본문은 핵심 이슈 최대 3개. 미준비·실패·제공 중단은 안내 한 줄,
// 정정은 발행 원문을 지우지 않고 원문과 나란히 따로 보여 준다. 예측·상승 확률 문구는 넣지 않는다.
import { Ban, CircleAlert, Clock, FilePen, Info, Moon, Network, Newspaper, Sun } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router";
import type { Schemas } from "@/api/client";
import { useBriefing, useBriefingRounds } from "@/api/queries";
import { BriefingCard } from "@/components/domain/briefing-card";
import { EventRow, IconCount } from "@/components/domain/event-row";
import { FeedbackButtons } from "@/components/domain/feedback-buttons";
import { DisclaimerNote } from "@/components/domain/status-labels";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/feedback";
import { Segmented } from "@/components/ui/segmented";
import { Select } from "@/components/ui/select";
import { formatKst } from "@/lib/labels";
import { track, useScreenView, useViewId } from "@/lib/track";

type Edition = "morning" | "evening";
type Briefing = Schemas["BriefingResponse"];
type Correction = Briefing["corrections"][number];

/** 브리핑 회차를 발행할 당시의 관계 그래프 주소(FS032). 이슈를 주면 그 이슈를 중심으로 연다. */
function roundGraphPath(roundId: string, focusEventId?: string) {
  const query = new URLSearchParams({ round: roundId });
  if (focusEventId) {
    query.set("focus", focusEventId);
    query.set("hops", "1");
  }
  return `/?${query}`;
}

const editionOptions = [
  { value: "morning" as const, label: <><Sun aria-hidden="true" />출근</>, ariaLabel: "출근" },
  { value: "evening" as const, label: <><Moon aria-hidden="true" />퇴근</>, ariaLabel: "퇴근" },
];

export function BriefingPage() {
  const [params, setParams] = useSearchParams();
  const dateParam = params.get("date");
  const editionParam = params.get("edition");
  const requestedEdition: Edition | null = editionParam === "morning" || editionParam === "evening" ? editionParam : null;
  const briefing = useBriefing(dateParam, requestedEdition);
  const rounds = useBriefingRounds();
  const shown = briefing.data;
  useScreenView("briefing");

  const select = (date: string, edition: Edition) => setParams({ date, edition }, { replace: true });
  const dates = [...new Set([...(rounds.data?.items.map((r) => r.date) ?? []), ...(shown ? [shown.date] : [])])].sort().reverse();

  return (
    <div className="mx-auto flex w-full max-w-3xl min-w-0 flex-col gap-4 py-6 md:px-6">
      <h1 className="flex items-center gap-2 px-4 text-2xl font-bold text-text-primary md:px-0">
        <Newspaper className="size-7 text-text-secondary" aria-hidden="true" />
        브리핑
      </h1>
      {shown && (
        <div className="flex flex-wrap items-end gap-3 px-4 md:px-0">
          <Select
            label="발행일"
            hideLabel
            value={shown.date}
            onValueChange={(date) => select(date, shown.edition)}
            options={dates.map((date) => ({ value: date, label: date }))}
            className="min-w-0 flex-1 md:flex-none"
          />
          <Segmented aria-label="브리핑 구분" value={shown.edition} onValueChange={(edition) => select(shown.date, edition)} options={editionOptions} className="md:w-56" fill />
        </div>
      )}
      {briefing.isPending && <SkeletonRows count={3} label="브리핑을 불러오고 있어요" />}
      {briefing.isError && (
        <ErrorState className="px-4 md:px-0" error={briefing.error} title="브리핑을 불러오지 못했어요" onRetry={() => void briefing.refetch()} />
      )}
      {shown && <BriefingView key={shown.id} briefing={shown} />}
      <DisclaimerNote className="px-4 md:px-0" />
    </div>
  );
}

/** 회차 상태 안내 한 줄(미준비·생성 중·실패·제공 중단). 발행됐으면 없음. */
function RoundNotice({ briefing }: { briefing: Briefing }) {
  const notice = briefing.notice;
  if (!notice) return null;
  const icon =
    notice.kind === "suspended" ? (
      <Ban className="mt-0.5 size-5 shrink-0 text-error" aria-hidden="true" />
    ) : notice.kind === "failed" ? (
      <CircleAlert className="mt-0.5 size-5 shrink-0 text-error" aria-hidden="true" />
    ) : (
      <Clock className="mt-0.5 size-5 shrink-0 text-text-secondary" aria-hidden="true" />
    );
  return (
    <div role="status" className="flex items-start gap-2 py-2">
      {icon}
      <div className="flex min-w-0 flex-col gap-0.5">
        <p className="text-base font-medium text-text-primary">{notice.message}</p>
        {notice.reason && <p className="text-sm text-text-secondary">사유: {notice.reason}</p>}
        {notice.at && <p className="text-sm text-text-secondary tabular-nums">{formatKst(notice.at)}</p>}
      </div>
    </div>
  );
}

/** 정정 한 건: [정정] 표지 + 정정 내용, 원문이 있으면 '발행 원문'으로 구분해 함께, 사유·시각. */
function CorrectionNote({ correction }: { correction: Correction }) {
  return (
    <div className="flex flex-col gap-1 bg-surface-sunken px-3 py-2">
      <p className="flex items-center gap-1.5 text-sm font-semibold text-text-primary">
        <FilePen className="size-4 shrink-0 text-text-secondary" aria-hidden="true" />
        정정
        <span className="font-normal text-text-secondary tabular-nums">{formatKst(correction.createdAt)}</span>
      </p>
      {correction.original && (
        <p className="text-sm text-text-secondary">
          <span className="font-medium">발행 원문</span> {correction.original}
        </p>
      )}
      <p className="text-base text-text-primary">
        <span className="sr-only">정정 내용: </span>
        {correction.corrected}
      </p>
      <p className="text-sm text-text-secondary">사유: {correction.reason}</p>
    </div>
  );
}

function BriefingView({ briefing }: { briefing: Briefing }) {
  const location = useLocation();
  const navigate = useNavigate();
  const published = briefing.status === "published";
  const viewId = useViewId();
  useEffect(() => {
    if (published) track({ type: "briefing_view", targetId: briefing.id, viewId });
  }, [published, briefing.id, viewId]);
  const roundCorrections = briefing.corrections.filter((c) => !c.eventId);
  const totalEvidence = briefing.items.reduce((sum, item) => sum + item.evidenceCount, 0);
  const openIssue = (eventId: string) => track({ type: "briefing_issue_open", targetId: eventId, roundId: briefing.id, viewId });

  let summary: ReactNode = null;
  if (published && briefing.items.length === 0) {
    summary = <EmptyState title="이번 회차에 담을 핵심 이슈가 없어요" description="데이터 범위 안에서 선정 기준을 충족한 사건이 없었어요." />;
  } else if (published) {
    summary = (
      <section aria-labelledby="briefing-section-title">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 pt-4">
          <h3 id="briefing-section-title" className="text-base font-semibold text-text-primary">
            핵심 이슈
          </h3>
          <Button variant="link" size="sm" asChild>
            <Link to={roundGraphPath(briefing.id)}>
              <Network aria-hidden="true" />이 회차 전체 관계 그래프
            </Link>
          </Button>
        </div>
        <ol className="stagger">
          {briefing.items.map((item) => {
            const corrections = briefing.corrections.filter((c) => c.eventId === item.eventId);
            return (
              <li key={item.eventId} className="flex flex-col gap-2 border-b border-border-subtle pb-4 last:border-b-0">
                <EventRow
                  headingLevel="h4"
                  title={`${item.rank}. ${item.title}`}
                  eventTime={item.eventTime}
                  timePrecision={item.timePrecision}
                  companies={item.companies.map((c) => ({ id: c.id, name: c.name }))}
                  linkState={{ from: `${location.pathname}${location.search}` }}
                  evidenceCount={item.evidenceCount}
                  onSelect={() => {
                    openIssue(item.eventId);
                    navigate(roundGraphPath(briefing.id, item.eventId));
                  }}
                  divider={false}
                  className="pb-0"
                  meta={<IconCount icon={Newspaper} label="보도 기사" count={item.sourceSupport.articleCount} />}
                />
                <p className="text-sm text-text-secondary">
                  <span className="font-medium">선정 이유</span> {item.reason}
                </p>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                  <Button variant="link" size="sm" asChild>
                    <Link to={roundGraphPath(briefing.id, item.eventId)} onClick={() => openIssue(item.eventId)}>
                      <Network aria-hidden="true" />
                      이 회차 관계 그래프에서 보기
                    </Link>
                  </Button>
                </div>
                <FeedbackButtons feature="briefing_issue" targetId={`${briefing.id}/${item.eventId}`} targetVersion={briefing.graphVersion} subject={`핵심 이슈 ${item.rank}`} />
                {corrections.map((c) => (
                  <CorrectionNote key={c.id} correction={c} />
                ))}
              </li>
            );
          })}
        </ol>
        <div className="flex flex-wrap items-center gap-x-3 border-t border-border-subtle py-2">
          <span className="text-sm font-medium text-text-primary">이 회차가 도움이 됐나요?</span>
          <FeedbackButtons feature="briefing_round" targetId={briefing.id} targetVersion={briefing.graphVersion} subject="이 브리핑 회차" />
        </div>
        <p className="flex items-center gap-2 border-t border-border-subtle py-3 text-sm text-text-secondary">
          <Info className="size-4 shrink-0" aria-hidden="true" />
          시장 요약과 주요 시장 변수는 아직 제공하지 않아요.
        </p>
      </section>
    );
  }

  return (
    <BriefingCard
      edition={briefing.edition}
      date={briefing.date}
      scheduledAt={formatKst(briefing.scheduledAt).slice(11, 16)}
      publishedAt={briefing.publishedAt ? formatKst(briefing.publishedAt) : null}
      dataAsOf={briefing.dataAsOf ? formatKst(briefing.dataAsOf) : null}
      notice={<RoundNotice briefing={briefing} />}
      corrections={
        roundCorrections.length > 0 && (
          <div className="flex flex-col gap-2">
            {roundCorrections.map((c) => (
              <CorrectionNote key={c.id} correction={c} />
            ))}
          </div>
        )
      }
      totalEvidence={published ? totalEvidence : undefined}
      summary={summary}
    />
  );
}
