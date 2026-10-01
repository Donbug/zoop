// AI 생성물 고지(인공지능기본법 제31조): 화면·블록마다 한 번만, 짧게.
// AiBadge(AI 생성 표시) · AiNotice(한 줄 고지) · AiDisclosure(생성 방식 상세는 눌러서 여는 팝오버)
import { Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Popover } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export function AiBadge({ label = "AI 요약", className }: { label?: string; className?: string }) {
  return (
    <Badge className={className}>
      <Sparkles aria-hidden="true" />
      {label}
    </Badge>
  );
}

export const aiNoticeText = "AI가 수집된 기사로 만든 요약이에요. 원문을 대체하지 않아요.";

/** AI 생성물 아래 한 줄 고지(13px). 상자나 색 배경 없이. */
export function AiNotice({ children = aiNoticeText, className }: { children?: string; className?: string }) {
  return (
    <p className={cn("flex items-start gap-1.5 text-sm text-text-secondary", className)}>
      <Sparkles className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
      <span>{children}</span>
    </p>
  );
}

interface AiDisclosureProps {
  /** BFF가 알려준 생성 주체(metadata.generatedBy). 없으면 그 줄을 그리지 않는다. */
  generatedBy?: string | null;
  /** 원문 범위 설명 (예: "근거 3건") */
  sourceScope?: string;
  asOf?: string;
}

/** "이 요약은 어떻게 만들었나요?" 링크 → 생성 주체·원문 범위·검수 여부 팝오버 */
export function AiDisclosure({ generatedBy, sourceScope, asOf }: AiDisclosureProps) {
  return (
    <Popover
      label="AI 요약 생성 방식"
      align="start"
      trigger={
        <Button variant="link" size="sm">
          이 요약은 어떻게 만들었나요?
        </Button>
      }
    >
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2">
        {generatedBy && (
          <>
            <dt className="font-semibold text-text-primary">만든 주체</dt>
            <dd>{generatedBy}</dd>
          </>
        )}
        <dt className="font-semibold text-text-primary">원문 범위</dt>
        <dd>
          {sourceScope ?? "화면에 표시된 근거 문서"} · 기준 <span className="tabular-nums">{asOf ?? "시각 미상"}</span>
        </dd>
        <dt className="font-semibold text-text-primary">사람 검수</dt>
        <dd>거치지 않은 자동 요약이에요.</dd>
      </dl>
    </Popover>
  );
}
