// SourceIndicator: 데이터 출처(datasetKind)를 글자 없이 아이콘 버튼 하나로 밝힌다.
// 호버·포커스하면 툴팁, 누르면 한 문장 설명. 스크린리더 이름은 "데이터 출처: 합성 데이터"처럼 읽힌다.
// 노출 위치는 두 곳뿐: 앱 헤더(전역) 1회, 근거 창 머리 1회. 패널·브리핑마다 반복하지 않는다.
import { Archive, CircleDashed, FlaskConical, ShieldCheck, WifiOff, type LucideIcon } from "lucide-react";
import { IconHint } from "@/components/ui/icon-hint";
import { datasetDescription, datasetLabel, type DatasetKind } from "@/lib/labels";
import { cn } from "@/lib/utils";

interface SourceIndicatorProps {
  kind: DatasetKind | null | undefined;
  /** 서버에 닿지 못해 출처를 알 수 없을 때 */
  offline?: boolean;
  /** 보이는 크기: 헤더는 md(44px), 창 머리 등 문장 옆은 sm */
  size?: "sm" | "md";
  className?: string;
}

export const datasetIcon: Record<DatasetKind, LucideIcon> = {
  "approved-live": ShieldCheck,
  "approved-snapshot": Archive,
  "synthetic-preview": FlaskConical,
};

export function SourceIndicator({ kind, offline, size = "md", className }: SourceIndicatorProps) {
  if (offline) {
    return (
      <IconHint icon={WifiOff} label="서버 연결 끊김" tone="error" size={size} className={className}>
        <p>데이터 출처를 확인하지 못했어요. 잠시 후 새로고침해 주세요.</p>
      </IconHint>
    );
  }
  if (!kind) {
    return (
      <span role="status" aria-label="데이터 출처 확인 중" className={cn("inline-flex items-center justify-center text-text-tertiary", size === "md" ? "size-11" : "size-7", className)}>
        <CircleDashed className="size-5 motion-safe:animate-spin" aria-hidden="true" />
      </span>
    );
  }
  return (
    <IconHint icon={datasetIcon[kind]} label={`데이터 출처: ${datasetLabel[kind]}`} size={size} className={className}>
      <p>{datasetDescription[kind]}</p>
    </IconHint>
  );
}
