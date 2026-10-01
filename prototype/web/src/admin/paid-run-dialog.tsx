// 유료 모델 작업 확인 대화상자(요구 76). 모델 호출 상한(기본 50, 서버 최대값까지)과 사유를 적고,
// 유료 호출이 생긴다는 확인란을 체크해야만 실행 버튼이 켜진다.
import { CircleDollarSign } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { ErrorState } from "@/components/ui/feedback";
import { Input } from "@/components/ui/input";
import { formatCount } from "./format";
import { textareaClass } from "./reason-dialog";

interface PaidRunDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** 무엇을 다시 처리하는지 */
  target: ReactNode;
  defaultLimit: number;
  maxLimit: number;
  pending: boolean;
  error: unknown;
  onConfirm: (input: { maxModelCalls: number; reason: string }) => void;
}

export function PaidRunDialog({ open, onOpenChange, title, target, defaultLimit, maxLimit, pending, error, onConfirm }: PaidRunDialogProps) {
  const initialLimit = String(Math.min(defaultLimit, maxLimit));
  const [limitText, setLimitText] = useState(initialLimit);
  const [reason, setReason] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const checkId = useId();
  const reasonId = useId();
  const limit = Number(limitText);
  const limitValid = Number.isInteger(limit) && limit >= 1 && limit <= maxLimit;
  const limitError = limitValid
    ? undefined
    : Number.isInteger(limit) && limit > maxLimit
      ? `서버 최대값 ${formatCount(maxLimit)}회를 넘을 수 없어요.`
      : "1 이상의 정수를 넣어 주세요.";

  const change = (next: boolean) => {
    if (!next) {
      setLimitText(initialLimit);
      setReason("");
      setAcknowledged(false);
    }
    onOpenChange(next);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={change}
      title={title}
      closeLabel="유료 작업 확인 창 닫기"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => change(false)}>
            닫기
          </Button>
          <Button loading={pending} disabled={!acknowledged || !limitValid || reason.trim().length === 0} onClick={() => onConfirm({ maxModelCalls: limit, reason: reason.trim() })}>
            <CircleDollarSign aria-hidden="true" />
            유료 재처리 실행
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="text-base text-text-primary">{target}</div>
        <p className="flex items-start gap-2 text-base text-text-primary">
          <CircleDollarSign className="mt-0.5 size-5 shrink-0 text-warning" aria-hidden="true" />
          <span>
            실행하면 외부 AI 모델을 호출해 <strong className="font-semibold">유료 사용량이 생겨요.</strong> 호출은 아래 상한에서 멈춰요.
          </span>
        </p>
        <Input
          label="모델 호출 상한(회)"
          type="number"
          inputMode="numeric"
          min={1}
          max={maxLimit}
          step={1}
          value={limitText}
          onChange={(e) => setLimitText(e.target.value)}
          hint={`기본 ${formatCount(defaultLimit)}회 · 최대 ${formatCount(maxLimit)}회`}
          error={limitError}
          className="max-w-60"
        />
        <div className="flex flex-col gap-1.5">
          <label htmlFor={reasonId} className="text-sm font-medium text-text-primary">
            실행 사유
          </label>
          <textarea id={reasonId} className={textareaClass} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
        </div>
        <label htmlFor={checkId} className="flex min-h-11 cursor-pointer items-center gap-3 text-base text-text-primary">
          <input
            id={checkId}
            type="checkbox"
            checked={acknowledged}
            onChange={(e) => setAcknowledged(e.target.checked)}
            className="size-5 shrink-0 accent-(--color-brand-primary)"
          />
          유료 모델 호출이 최대 {limitValid ? formatCount(limit) : "–"}회 생길 수 있음을 확인했어요
        </label>
        {error != null && <ErrorState error={error} title="재처리를 시작하지 못했어요" compact />}
      </div>
    </Dialog>
  );
}
