import { useId, useState, type FormEvent, type ReactNode } from 'react';
import {
  appendBriefingCorrection,
  reprocessBriefingRound,
  setBriefingSuspension,
} from '@/apis/admin/briefings';
import {
  BUTTON,
  PRIMARY_BUTTON,
  SELECT,
  TEXTAREA,
  adminActionErrorMessage,
} from '@/components/admin/common/adminStyles';
import { useIdempotencyKey } from '@/hooks/useIdempotencyKey';
import { editionLabel } from '@/constants/adminLabels';
import type { RoundDetail } from '@/types/admin/briefings';

export type RoundAction = 'reprocess' | 'correct' | 'suspend' | 'resume';

const COPY: Record<
  RoundAction,
  { title: string; reason: string; submit: string; done: string; hint?: string }
> = {
  reprocess: {
    title: '브리핑 재처리',
    reason: '재처리 사유',
    submit: '재처리 요청(무료)',
    done: '재처리를 요청했어요.',
    hint: '무료(모델을 다시 부르지 않아요). 지연·실패한 미발행 회차만 다시 처리해요. 새 회차를 만들거나 발행본을 덮어쓰지 않아요.',
  },
  correct: {
    title: '정정 등록',
    reason: '정정 사유',
    submit: '정정 등록하기',
    done: '정정을 등록했어요.',
    hint: '발행 원문은 그대로 두고, 정정 내용·사유·시점을 따로 남겨요.',
  },
  suspend: {
    title: '제공 중단',
    reason: '사용자에게 보일 중단 사유',
    submit: '제공 중단하기',
    done: '제공을 중단했어요.',
    hint: '중단 사유는 사용자 화면에 그대로 보여요. 내부 정보는 적지 마세요. 발행 이력은 보존돼요.',
  },
  resume: {
    title: '제공 재개',
    reason: '재개 사유',
    submit: '제공 다시 시작하기',
    done: '제공을 다시 시작했어요.',
  },
};

function Field({
  label,
  children,
}: {
  label: ReactNode;
  children: (id: string) => ReactNode;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-[11px] text-zoop-muted">
        {label}
      </label>
      {children(id)}
    </div>
  );
}

/**
 * 회차 관리 작업(재처리·정정·제공 중단/재개) 입력. 사유는 필수다.
 * 응답을 받지 못해 같은 내용을 다시 보내면 같은 Idempotency-Key를 써서 서버가 한 번만 처리한다.
 */
export default function RoundActionForm({
  round,
  action,
  onCancel,
  onDone,
}: {
  round: RoundDetail;
  action: RoundAction;
  onCancel: () => void;
  onDone: (message: string) => void;
}) {
  const copy = COPY[action];
  const items = round.published?.items ?? [];
  const idempotency = useIdempotencyKey();
  const [reason, setReason] = useState('');
  const [body, setBody] = useState('');
  const [target, setTarget] = useState('round');
  const [missing, setMissing] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const trimmedReason = reason.trim();
    const trimmedBody = body.trim();
    if (
      !trimmedReason ||
      trimmedReason.length > 500 ||
      (action === 'correct' && (!trimmedBody || trimmedBody.length > 2000))
    ) {
      setMissing(true);
      return;
    }
    setMissing(false);
    setError(null);
    setPending(true);
    const correction = {
      eventId: target === 'round' ? null : target,
      correctedText: trimmedBody,
      reason: trimmedReason,
    };
    const idempotencyKey = idempotency.keyFor(
      action === 'correct' ? correction : { action, reason: trimmedReason },
    );
    try {
      if (action === 'reprocess')
        await reprocessBriefingRound(round.id, trimmedReason, idempotencyKey);
      else if (action === 'correct')
        await appendBriefingCorrection(round.id, correction, idempotencyKey);
      else
        await setBriefingSuspension(
          round.id,
          action,
          trimmedReason,
          idempotencyKey,
        );
      onDone(copy.done);
    } catch (submitError) {
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
      data-admin-editing="true"
      noValidate
      aria-label={copy.title}
      onSubmit={(event) => void submit(event)}
      className="flex flex-col gap-3 rounded-2xl bg-zoop-soft p-5"
    >
      <div className="flex flex-col gap-0.5">
        <p className="text-sm font-bold">{copy.title}</p>
        <p className="text-[11px] text-zoop-muted tabular-nums">
          {round.date} {editionLabel[round.edition]} 브리핑
        </p>
      </div>
      {copy.hint && (
        <p className="text-[11px] leading-relaxed text-zoop-muted">
          {copy.hint}
        </p>
      )}
      {action === 'correct' && (
        <>
          <Field label="정정할 항목">
            {(id) => (
              <select
                id={id}
                value={target}
                disabled={pending}
                onChange={(event) => setTarget(event.target.value)}
                className={SELECT}
              >
                <option value="round">회차 전체</option>
                {items.map((item) => (
                  <option key={item.eventId} value={item.eventId}>
                    {item.rank}. {item.title}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="정정 내용">
            {(id) => (
              <textarea
                id={id}
                value={body}
                maxLength={2000}
                disabled={pending}
                aria-invalid={missing && !body.trim()}
                onChange={(event) => setBody(event.target.value)}
                className={TEXTAREA}
              />
            )}
          </Field>
        </>
      )}
      <Field label={copy.reason}>
        {(id) => (
          <textarea
            id={id}
            value={reason}
            maxLength={500}
            disabled={pending}
            aria-invalid={missing && !reason.trim()}
            onChange={(event) => setReason(event.target.value)}
            className={TEXTAREA}
          />
        )}
      </Field>
      <p className="text-[11px] text-zoop-muted">
        사유 {reason.length}/500자
        {action === 'correct' && ` · 정정 ${body.length}/2000자`}
      </p>
      {missing && (
        <p role="alert" className="text-[11px] text-zoop-alert">
          {action === 'correct'
            ? '정정 내용과 사유를 모두 입력해 주세요.'
            : '사유를 입력해 주세요.'}
        </p>
      )}
      {error && (
        <p role="alert" className="text-[11px] text-zoop-alert">
          {copy.title}에 실패했어요. {adminActionErrorMessage(error)}
        </p>
      )}
      <div className="flex flex-wrap justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={pending}
          className={`${BUTTON} h-9`}
        >
          취소
        </button>
        <button type="submit" disabled={pending} className={PRIMARY_BUTTON}>
          {pending ? '처리하고 있어요' : copy.submit}
        </button>
      </div>
    </form>
  );
}
