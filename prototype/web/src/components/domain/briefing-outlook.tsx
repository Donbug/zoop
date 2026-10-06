import type { Schemas } from "@/api/client";
import { Button } from "@/components/ui/button";
import { SentimentLabel } from "./status-labels";

export function briefingIssueId(eventId: string) {
  return `briefing-issue-${eventId}`;
}

/** 발행본에 고정된 기사 판단. 근거 이슈는 같은 회차 본문의 실제 항목만 연결한다. */
export function BriefingOutlook({ outlook, issues }: {
  outlook: Schemas["BriefingOutlook"] | null | undefined;
  issues: { eventId: string; title: string; rank: number }[];
}) {
  if (!outlook) return null;
  const evidenceIssues = issues.filter((issue) => outlook.issueIds.includes(issue.eventId));
  return (
    <section aria-label="회차 판단" className="flex flex-col gap-2 border-t border-border-subtle py-3">
      <div className="flex flex-wrap items-center gap-x-3">
        <h3 className="text-base font-semibold text-text-primary">회차 판단</h3>
        <SentimentLabel judgement={outlook} accessibleName="회차" />
      </div>
      <p className="text-base text-text-primary">{outlook.rationale}</p>
      {evidenceIssues.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-sm text-text-secondary">근거 이슈</span>
          {evidenceIssues.map((issue) => (
            <Button key={issue.eventId} variant="link" size="sm" asChild className="max-w-full whitespace-normal text-left">
              <a href={`#${encodeURIComponent(briefingIssueId(issue.eventId))}`}>{issue.rank}. {issue.title}</a>
            </Button>
          ))}
        </div>
      )}
      <p className="text-sm text-text-secondary">주가 전망이 아니에요.</p>
    </section>
  );
}
