// FS032(D03) 브리핑에서 연 관계 그래프: 어느 회차·기준 시점에 고정된 그래프인지 알리고 현재 그래프로 넘어가는 자리.
//  - BriefingGraphBasisBar: 그래프 위 한 줄. 회차(발행일·출근/퇴근)와 데이터 기준 시점, [현재 그래프로 보기], [브리핑으로].
//  - BriefingGraphGate: 그래프를 읽을 수 없을 때(불러오는 중·조회 실패·제공 중단·발행 전·기준 시점 자료 없음)의 안내.
//    BFF가 준 사유를 그대로 보이고, 최신 그래프로 대신 보여주지 않는다.
import type { UseQueryResult } from "@tanstack/react-query";
import { FilePen, History } from "lucide-react";
import { Link } from "react-router";
import type { Schemas } from "@/api/client";
import { ApiError } from "@/api/client";
import { editionTitle } from "@/components/domain/briefing-card";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingBlock, Skeleton } from "@/components/ui/feedback";
import { formatKst } from "@/lib/labels";
import { cn } from "@/lib/utils";

type Basis = Schemas["BriefingGraphBasis"];

/** 이 회차의 브리핑 화면 주소 */
export function briefingPath(basis: Pick<Basis, "date" | "edition">) {
  return `/briefing?date=${basis.date}&edition=${basis.edition}`;
}

export function BriefingGraphBasisBar({ basis, onShowCurrent, className }: { basis: Basis; onShowCurrent: () => void; className?: string }) {
  return (
    <div
      role="region"
      aria-label="회차 기준 그래프"
      className={cn("flex flex-wrap items-center gap-x-4 gap-y-2 border-y border-border-subtle bg-surface-sunken px-3 py-2", className)}
    >
      <History className="size-5 shrink-0 text-text-secondary" aria-hidden="true" />
      <div className="flex min-w-0 flex-1 basis-56 flex-col">
        <p className="text-base font-semibold text-text-primary">
          <time dateTime={basis.date}>{basis.date}</time> {editionTitle[basis.edition]} 기준 그래프
        </p>
        <p className="flex flex-wrap items-center gap-x-3 text-sm text-text-secondary tabular-nums">
          <span>발행 당시의 관계·근거 · 데이터 기준 {formatKst(basis.dataAsOf)}</span>
          {basis.correctionCount > 0 && (
            <span className="inline-flex items-center gap-1">
              <FilePen className="size-4 shrink-0" aria-hidden="true" />
              정정 {basis.correctionCount}건은 브리핑에서 확인
            </span>
          )}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" onClick={onShowCurrent}>
          현재 그래프로 보기
        </Button>
        <Button variant="ghost" size="sm" asChild>
          <Link to={briefingPath(basis)}>브리핑으로</Link>
        </Button>
      </div>
    </div>
  );
}

/** 기준 정보를 받는 동안·받지 못했을 때·그래프를 보여줄 수 없는 상태일 때 그래프 자리에 놓는 안내. available이면 쓰지 않는다. */
export function BriefingGraphGate({
  query,
  onShowCurrent,
  className,
}: {
  query: UseQueryResult<Basis>;
  onShowCurrent: () => void;
  className?: string;
}) {
  if (query.isPending) {
    return (
      <LoadingBlock label="회차 기준 그래프를 확인하고 있어요" className={cn("flex min-h-[360px] flex-1", className)}>
        <Skeleton className="flex-1 rounded-none" />
      </LoadingBlock>
    );
  }
  if (query.isError) {
    if (query.error instanceof ApiError && query.error.code === "briefing_round_not_found") {
      return (
        <EmptyState
          className={className}
          title="찾을 수 없는 브리핑 회차예요."
          action={
            <>
              <Button asChild>
                <Link to="/briefing">브리핑 보기</Link>
              </Button>
              <Button variant="ghost" onClick={onShowCurrent}>
                현재 그래프 보기
              </Button>
            </>
          }
        />
      );
    }
    return <ErrorState className={className} error={query.error} title="회차 기준 그래프를 불러오지 못했어요" onRetry={() => void query.refetch()} />;
  }
  const basis = query.data;
  return (
    <EmptyState
      className={className}
      title={basis.message ?? "이 회차의 그래프를 보여드릴 수 없어요."}
      description={`${basis.date} ${editionTitle[basis.edition]}${basis.reason ? ` · 사유: ${basis.reason}` : ""}`}
      action={
        <>
          <Button asChild>
            <Link to={briefingPath(basis)}>브리핑으로 돌아가기</Link>
          </Button>
          <Button variant="ghost" onClick={onShowCurrent}>
            현재 그래프 보기
          </Button>
        </>
      }
    />
  );
}
