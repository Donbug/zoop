// BriefingCard: 출근/퇴근 브리핑 1회분. 회차 바깥 경계 1개만 두고 안쪽은 행(EventRow)으로 평탄화한다.
// 머리(회차·발행일·예정 시각·발행 시각·데이터 기준 시점) + 회차 안내(미준비·실패·제공 중단·정정) + 본문 + 꼬리(근거 문서 수).
// 출처·투자 고지는 화면 단위에서 한 번만. relations를 넘기면 본문을 [핵심 요약 | 관계도] 탭으로 나눈다(선택).
import { FileText, Moon, Sun } from "lucide-react";
import type { ReactNode } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { IconCount } from "./event-row";

interface BriefingCardProps {
  edition: "morning" | "evening";
  /** 발행일(회차 날짜, KST) */
  date: string;
  /** 예정 발행 시각 (예: "07:40") */
  scheduledAt: string;
  /** 실제 발행 시각(표시용 문자열, KST). 발행 전이면 없음. */
  publishedAt?: string | null;
  /** 데이터 기준 시점(표시용 문자열, KST) */
  dataAsOf?: string | null;
  /** 회차 상태 안내(미준비·실패·제공 중단). 있으면 본문 위에 한 줄로. */
  notice?: ReactNode;
  /** 회차 전체에 대한 정정(원문과 구분해 표시) */
  corrections?: ReactNode;
  /** 근거 문서 합계. 없으면 꼬리 줄을 그리지 않는다. */
  totalEvidence?: number;
  summary?: ReactNode;
  relations?: ReactNode;
  className?: string;
}

export const editionTitle = { morning: "출근 브리핑", evening: "퇴근 브리핑" } as const;

export function BriefingCard({ edition, date, scheduledAt, publishedAt, dataAsOf, notice, corrections, totalEvidence, summary, relations, className }: BriefingCardProps) {
  const EditionIcon = edition === "morning" ? Sun : Moon;
  return (
    <section className={cn("flex min-w-0 flex-col border-y border-border-subtle md:border-x", className)} aria-label={`${date} ${editionTitle[edition]}`}>
      <div className="flex flex-col gap-1 px-4 pt-4 pb-2">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-text-primary">
          <EditionIcon className="size-5 text-text-secondary" aria-hidden="true" />
          {editionTitle[edition]}
        </h2>
        <dl className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-text-secondary tabular-nums">
          <div className="flex gap-1">
            <dt>발행일</dt>
            <dd>
              <time dateTime={date}>{date}</time>
            </dd>
          </div>
          <div className="flex gap-1">
            <dt>예정</dt>
            <dd>{scheduledAt}</dd>
          </div>
          {publishedAt && (
            <div className="flex gap-1">
              <dt>발행</dt>
              <dd>{publishedAt}</dd>
            </div>
          )}
          {dataAsOf && (
            <div className="flex gap-1">
              <dt>데이터 기준</dt>
              <dd>{dataAsOf}</dd>
            </div>
          )}
        </dl>
      </div>
      {notice && <div className="px-4 pb-2">{notice}</div>}
      {corrections && <div className="px-4 pb-2">{corrections}</div>}
      {summary &&
        (relations ? (
          <Tabs defaultValue="summary" className="flex flex-col">
            <TabsList className="px-4">
              <TabsTrigger value="summary">핵심 요약</TabsTrigger>
              <TabsTrigger value="relations">관계도</TabsTrigger>
            </TabsList>
            <TabsContent value="summary" className="px-4">
              {summary}
            </TabsContent>
            <TabsContent value="relations" className="p-4">
              {relations}
            </TabsContent>
          </Tabs>
        ) : (
          <div className="px-4">{summary}</div>
        ))}
      {totalEvidence !== undefined && (
        <div className="border-t border-border-subtle px-4 py-3">
          <IconCount icon={FileText} label="근거 문서" count={totalEvidence} />
        </div>
      )}
    </section>
  );
}
