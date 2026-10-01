// 사유를 반드시 적어야 하는 관리자 행동(허용·거부·게시·되돌리기·제공 중단 등)의 확인 창.
// 사유는 감사 로그에 남는다. 무료 작업이면 그 사실을 한 줄로 밝힌다.
import { useId, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { ErrorState } from "@/components/ui/feedback";
import { cn } from "@/lib/utils";

export const textareaClass =
  "min-h-24 w-full rounded-sm border border-border-control bg-surface-raised px-3 py-2 text-base text-text-primary placeholder:text-text-tertiary transition-token hover:border-text-secondary focus-visible:border-border-focus aria-invalid:border-error";

interface ReasonDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** 무엇에 대한 행동인지 */
  target?: ReactNode;
  /** 확인 버튼 문구(결과를 예측할 수 있게: "허용하고 게시 대기열에 넣기") */
  confirmLabel: string;
  confirmIcon?: ReactNode;
  reasonLabel?: string;
  /** 사유 외에 함께 받을 본문(예: 정정 내용). 있으면 첫 칸으로 보인다. */
  bodyLabel?: string;
  pending: boolean;
  error: unknown;
  onConfirm: (input: { reason: string; body: string }) => void;
  children?: ReactNode;
}

export function ReasonDialog({ open, onOpenChange, title, target, confirmLabel, confirmIcon, reasonLabel = "사유", bodyLabel, pending, error, onConfirm, children }: ReasonDialogProps) {
  const [reason, setReason] = useState("");
  const [body, setBody] = useState("");
  const reasonId = useId();
  const bodyId = useId();
  const ready = reason.trim().length > 0 && (!bodyLabel || body.trim().length > 0);

  const change = (next: boolean) => {
    if (!next) {
      setReason("");
      setBody("");
    }
    onOpenChange(next);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={change}
      title={title}
      closeLabel={`${title} 창 닫기`}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => change(false)}>
            닫기
          </Button>
          <Button loading={pending} disabled={!ready} onClick={() => onConfirm({ reason: reason.trim(), body: body.trim() })}>
            {confirmIcon}
            {confirmLabel}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {target && <div className="text-base text-text-primary">{target}</div>}
        {children}
        {bodyLabel && (
          <div className="flex flex-col gap-1.5">
            <label htmlFor={bodyId} className="text-sm font-medium text-text-primary">
              {bodyLabel}
            </label>
            <textarea id={bodyId} className={cn(textareaClass, "min-h-32")} value={body} onChange={(e) => setBody(e.target.value)} maxLength={2000} />
          </div>
        )}
        <div className="flex flex-col gap-1.5">
          <label htmlFor={reasonId} className="text-sm font-medium text-text-primary">
            {reasonLabel}
          </label>
          <textarea id={reasonId} className={textareaClass} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
        </div>
        {error != null && <ErrorState error={error} title="처리하지 못했어요" compact />}
      </div>
    </Dialog>
  );
}
