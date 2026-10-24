import { useId, useState, type FormEvent } from 'react';
import { ApiError } from '@/apis/auth/ApiService';
import { cancelAnalysisJob, retryAnalysisJob } from '@/apis/admin/jobs';
import {
  BUTTON,
  PRIMARY_BUTTON,
  TEXTAREA,
  adminActionErrorMessage,
} from '@/components/admin/common/adminStyles';
import { jobKindLabel } from '@/constants/adminLabels';
import { useIdempotencyKey } from '@/hooks/useIdempotencyKey';
import type { AnalysisJob, JobCreated } from '@/types/admin/jobs';

/** 사유 최대 길이(JobReasonRequest @Size(max = 500)) */
const REASON_MAX = 500;

export type JobAction = 'retry' | 'cancel';

const COPY: Record<
  JobAction,
  { title: string; reasonLabel: string; submit: string; pending: string }
> = {
  retry: {
    title: '작업 다시 실행',
    reasonLabel: '실행 사유(감사 로그에 남아요)',
    submit: '다시 실행하기',
    pending: '요청하고 있어요',
  },
  cancel: {
    title: '작업 취소',
    reasonLabel: '취소 사유(감사 로그에 남아요)',
    submit: '작업 취소하기',
    pending: '취소하고 있어요',
  },
};

/** 409 REVISION_CONFLICT는 그 사이 작업 상태가 바뀐 경우다. 원인은 상세를 새로 고쳐 확인하게 한다. */
function jobActionErrorMessage(action: JobAction, error: Error) {
  if (error instanceof ApiError && error.code === 'REVISION_CONFLICT')
    return action === 'retry'
      ? '작업 상태가 바뀌어 다시 실행할 수 없어요. 상세를 새로 고친 뒤 확인해 주세요.'
      : '이미 끝난 작업이라 취소할 수 없어요. 상세를 새로 고친 뒤 확인해 주세요.';
  if (error instanceof ApiError && error.code === 'RESOURCE_NOT_FOUND')
    return '이 작업을 찾을 수 없어요. 목록을 새로 고쳐 주세요.';
  return adminActionErrorMessage(error);
}

/**
 * 작업 다시 실행·취소(FS067-03, retryAnalysisJob·cancelAnalysisJob). 사유는 필수이고 감사 로그에 남는다.
 * 응답을 받지 못해 같은 사유로 다시 보내면 같은 Idempotency-Key를 써서 한 번만 처리된다.
 */
export default function JobActionForm({
  action,
  job,
  onPendingChange,
  onCancel,
  onRetried,
  onCancelled,
}: {
  action: JobAction;
  job: AnalysisJob;
  /** 요청이 진행 중인지 상위에 알린다. 진행 중에는 다른 작업 선택·폼 교체를 막는다. */
  onPendingChange: (pending: boolean) => void;
  onCancel: () => void;
  onRetried: (result: JobCreated) => void;
  onCancelled: (job: AnalysisJob) => void;
}) {
  const reasonId = useId();
  const idempotency = useIdempotencyKey();
  const [reason, setReason] = useState('');
  const [missing, setMissing] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const copy = COPY[action];
  const name = jobKindLabel[job.kind] ?? job.label;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const trimmed = reason.trim();
    setMissing(!trimmed);
    if (!trimmed) return;
    setError(null);
    setPending(true);
    onPendingChange(true);
    const key = idempotency.keyFor({ action, jobId: job.id, reason: trimmed });
    try {
      if (action === 'retry') {
        const result = await retryAnalysisJob(job.id, trimmed, key);
        onPendingChange(false);
        onRetried(result);
      } else {
        const result = await cancelAnalysisJob(job.id, trimmed, key);
        onPendingChange(false);
        onCancelled(result);
      }
    } catch (submitError) {
      onPendingChange(false);
      idempotency.settle(submitError);
      setError(
        submitError instanceof Error
          ? submitError
          : new Error(String(submitError)),
      );
      setPending(false);
    }
  }

  return (
    <form
      noValidate
      aria-label={copy.title}
      onSubmit={(event) => void submit(event)}
      className="flex flex-col gap-3 rounded-[3px] border-[0.667px] border-zoop-ink bg-zoop-paper p-4"
    >
      <p className="text-sm font-bold">{copy.title}</p>
      <p className="text-[11px] leading-relaxed text-zoop-muted">
        {action === 'retry'
          ? `${name} 작업을 같은 입력의 새 작업으로 대기열에 넣어요. 이 작업은 그대로 남아요.`
          : job.status === 'running'
            ? `실행 중인 ${name} 작업에 취소를 요청해요. 이미 처리한 결과는 원장에 남아요.`
            : `대기 중인 ${name} 작업을 바로 취소해요.`}
      </p>
      <div className="flex flex-col gap-1">
        <label htmlFor={reasonId} className="text-[11px] text-zoop-muted">
          {copy.reasonLabel}
        </label>
        <textarea
          id={reasonId}
          value={reason}
          maxLength={REASON_MAX}
          disabled={pending}
          aria-invalid={missing}
          onChange={(event) => setReason(event.target.value)}
          className={TEXTAREA}
        />
        <p className="self-end text-[10px] text-zoop-faint tabular-nums">
          {reason.length}/{REASON_MAX}
        </p>
      </div>
      {missing && (
        <p role="alert" className="text-[11px] text-zoop-alert">
          사유를 입력해 주세요.
        </p>
      )}
      {error && (
        <p role="alert" className="text-[11px] text-zoop-alert">
          {action === 'retry'
            ? '다시 실행하지 못했어요.'
            : '작업을 취소하지 못했어요.'}{' '}
          {jobActionErrorMessage(action, error)}
        </p>
      )}
      <div className="flex flex-wrap justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={pending}
          className={`${BUTTON} h-9`}
        >
          닫기
        </button>
        <button type="submit" disabled={pending} className={PRIMARY_BUTTON}>
          {pending ? copy.pending : copy.submit}
        </button>
      </div>
    </form>
  );
}
