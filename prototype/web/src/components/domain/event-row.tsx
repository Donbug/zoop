// EventRow: 사건 1건을 카드 없이 한 행으로 보여준다(기존 IssueCard 대체).
// 날짜 → 제목 → 관련 기업 → [근거 N건 보기] [AI에게 묻기]. 아래 1px 구분선.
// 관계 유형·보도 수 같은 메타 정보는 글자 태그 대신 아이콘 + 숫자로(스크린리더에는 이름을 읽힌다).
import { FileText, MessageCircleQuestion, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { formatEventTime, relationLabel, type RelationType, type TimePrecision } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { EdgeGlyph } from "./relation-type-tag";

export interface EventRowProps {
  title: string;
  eventTime: string | null;
  timePrecision: TimePrecision | null;
  /** 관련 기업(최대 3곳 표시, 나머지는 '외 N곳') */
  companies?: { id: string; name: string }[];
  /** 관련 기업 링크에 실을 이력 state(예: 지도에서 온 경우 { from }) */
  linkState?: unknown;
  evidenceCount?: number;
  /** 한 목록에 관계 유형이 섞일 때만. 선 견본 아이콘 + 툴팁으로 보인다. */
  relationType?: RelationType;
  onShowEvidence?: () => void;
  onAsk?: () => void;
  /** 제목을 눌렀을 때(예: 지도에서 이 사건 선택) */
  onSelect?: () => void;
  /** 날짜 줄 오른쪽에 붙일 아이콘 메타(IconCount 등) */
  meta?: ReactNode;
  headingLevel?: "h3" | "h4";
  divider?: boolean;
  /** false면 행 안 발생 시각을 숨긴다(타임라인처럼 날짜 열을 따로 그릴 때) */
  showTime?: boolean;
  className?: string;
}

/** 아이콘 + 숫자 메타(예: 보도 기사 3건). 글자 라벨은 스크린리더에만. */
export function IconCount({ icon: Icon, label, count, className }: { icon: LucideIcon; label: string; count: number; className?: string }) {
  return (
    <Tooltip content={`${label} ${count}건`}>
      <span tabIndex={0} className={cn("inline-flex items-center gap-1 rounded-sm text-sm text-text-secondary tabular-nums", className)}>
        <Icon className="size-4 shrink-0" aria-hidden="true" />
        <span className="sr-only">{label}</span>
        {count}
      </span>
    </Tooltip>
  );
}

export function EventRow({
  title,
  eventTime,
  timePrecision,
  companies = [],
  evidenceCount,
  linkState,
  relationType,
  onShowEvidence,
  onAsk,
  onSelect,
  meta,
  headingLevel: Heading = "h3",
  divider = true,
  showTime = true,
  className,
}: EventRowProps) {
  const shown = companies.slice(0, 3);
  const hasActions = evidenceCount !== undefined || onAsk;
  const hasMetaLine = showTime || relationType || meta;
  return (
    <article className={cn("flex flex-col gap-1.5 py-4", divider && "border-b border-border-subtle", className)}>
      {hasMetaLine && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {showTime && (
            <time className="text-sm text-text-secondary" dateTime={eventTime ?? undefined}>
              {formatEventTime(eventTime, timePrecision)}
            </time>
          )}
          {relationType && (
            <Tooltip content={relationLabel[relationType]}>
              <span tabIndex={0} role="img" aria-label={`관계: ${relationLabel[relationType]}`} className="inline-flex rounded-sm">
                <EdgeGlyph type={relationType} className="w-6" />
              </span>
            </Tooltip>
          )}
          {meta}
        </div>
      )}
      <Heading className="text-base leading-snug font-medium text-text-primary">
        {onSelect ? (
          <button type="button" onClick={onSelect} className="text-left underline-offset-4 hover:underline">
            {title}
          </button>
        ) : (
          title
        )}
      </Heading>
      {shown.length > 0 && (
        <p className="text-sm text-text-secondary">
          <span className="sr-only">관련 기업: </span>
          {shown.map((company, i) => (
            <span key={company.id}>
              {i > 0 && ", "}
              <Link to={`/companies/${encodeURIComponent(company.id)}`} state={linkState} className="underline-offset-4 hover:text-text-primary hover:underline">
                {company.name}
              </Link>
            </span>
          ))}
          {companies.length > 3 && ` 외 ${companies.length - 3}곳`}
        </p>
      )}
      {hasActions && (
        <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-2">
          {evidenceCount !== undefined &&
            (onShowEvidence && evidenceCount > 0 ? (
              <Button variant="link" size="sm" onClick={onShowEvidence} className="tabular-nums">
                <FileText aria-hidden="true" />
                근거 {evidenceCount}건 보기
              </Button>
            ) : (
              <IconCount icon={FileText} label="근거" count={evidenceCount} />
            ))}
          {onAsk && (
            <Button variant="ghost" size="sm" onClick={onAsk} className="ml-auto">
              <MessageCircleQuestion aria-hidden="true" />
              AI에게 묻기
            </Button>
          )}
        </div>
      )}
    </article>
  );
}
