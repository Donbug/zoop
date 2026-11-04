import { useId, useState, type FormEvent } from 'react';
import { ApiError } from '@/apis/auth/ApiService';
import { retryGraphRound, startGraphRound } from '@/apis/admin/graphRounds';
import {
  BUTTON,
  PRIMARY_BUTTON,
  SELECT,
  adminActionErrorMessage,
} from '@/components/admin/common/adminStyles';
import { useIdempotencyKey } from '@/hooks/useIdempotencyKey';
import { retryCaution } from '@/constants/adminLabels';
import type { GraphRound } from '@/types/admin/graphRounds';
import { kstMinuteToIso } from '@/util/format';

export type GraphRoundAction =
  { kind: 'retry'; round: GraphRound } | { kind: 'start' };

/**
 * 명령 실패 문구. 404는 모르는 회차일 수도 있지만, 화면에서 고른 회차라면 대개 살아 있는 회차 실행기(writer)가 없는 경우다.
 * 재시도의 409는 실패 상태가 아니게 됐거나 회차 실행기가 그 회차를 처리 중(lease)인 것이다. 서버는 REVISION_CONFLICT를 보내고,
 * 계약 목록에는 JOB_NOT_RETRYABLE이 있어 둘 다 받는다. 시작의 409는 같은 시각의 회차가 이미 있는 것이다.
 * 422는 시각을 보냈을 때만 시각 입력 탓으로 안내한다(지금 시작에는 입력한 시각이 없다).
 */
function commandErrorMessage(
  error: Error,
  action: GraphRoundAction,
  sentSlot: boolean,
) {
  if (error instanceof ApiError) {
    if (error.code === 'RESOURCE_NOT_FOUND' || error.status === 404)
      return action.kind === 'retry'
        ? '회차 실행기가 동작하지 않거나 회차를 찾을 수 없어 접수하지 못했어요. 개요의 회차 실행기 상태를 확인해 주세요.'
        : '회차 실행기가 동작하지 않아 접수하지 못했어요. 개요의 회차 실행기 상태를 확인해 주세요.';
    if (
      error.code === 'REVISION_CONFLICT' ||
      error.code === 'JOB_NOT_RETRYABLE'
    )
      return action.kind === 'retry'
        ? '지금은 이 회차를 다시 열 수 없어요. 실패 상태가 아니거나 회차 실행기가 처리 중이에요. 상세를 새로 고쳐 주세요.'
        : '같은 시각의 회차가 이미 있어요. 목록에서 확인해 주세요.';
    if (error.code === 'SOURCE_UNAVAILABLE' || error.status === 503)
      return '회차 실행기 상태를 확인하지 못했어요. 잠시 후 다시 시도해 주세요.';
    if (sentSlot && (error.code === 'INVALID_REQUEST' || error.status === 422))
      return '시각을 분 단위로 입력해 주세요.';
  }
  return adminActionErrorMessage(error);
}

/**
 * 회차 재시도·수동 시작(retryGraphRound·startGraphRound). 두 명령은 본문에 사유가 없고 관리자 id로 감사 로그에 남는다.
 * 응답을 받지 못해 같은 내용으로 다시 보내면 같은 Idempotency-Key를 써서 한 번만 처리된다.
 */
export default function GraphRoundActionForm({
  action,
  onPendingChange,
  onCancel,
  onDone,
}: {
  action: GraphRoundAction;
  onPendingChange: (pending: boolean) => void;
  onCancel: () => void;
  onDone: (round: GraphRound) => void;
}) {
  const slotId = useId();
  const idempotency = useIdempotencyKey();
  const [when, setWhen] = useState<'now' | 'slot'>('now');
  const [slot, setSlot] = useState('');
  const [invalid, setInvalid] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  // 마지막으로 보낸 요청에 시각을 넣었는지. 422 안내를 정한다.
  const [sentSlot, setSentSlot] = useState(false);
  const retry = action.kind === 'retry';
  const title = retry ? '회차 재시도' : '회차 시작';
  const caution = retry ? retryCaution(action.round.failureCode) : null;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    let slotAt: string | null = null;
    setInvalid(false);
    if (!retry && when === 'slot') {
      slotAt = kstMinuteToIso(slot);
      setInvalid(slotAt === null);
      if (slotAt === null) return;
    }
    setError(null);
    setSentSlot(slotAt !== null);
    setPending(true);
    onPendingChange(true);
    try {
      const round = retry
        ? await retryGraphRound(
            action.round.roundId,
            idempotency.keyFor({ retry: action.round.roundId }),
          )
        : await startGraphRound(
            slotAt,
            idempotency.keyFor({ start: slotAt ?? 'now' }),
          );
      onPendingChange(false);
      onDone(round);
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
      data-admin-editing="true"
      noValidate
      aria-label={title}
      onSubmit={(event) => void submit(event)}
      className="flex flex-col gap-3 rounded-2xl bg-zoop-soft p-5"
    >
      <p className="text-body font-bold">{title}</p>
      {retry ? (
        <p className="text-caption leading-relaxed text-zoop-muted">
          <strong className="font-num text-zoop-ink">
            {action.round.roundId}
          </strong>
          를 같은 회차 ID로 멈춘 단계부터 다시 열어요. 실제 진행은 회차 실행기의
          다음 바퀴가 해요.
        </p>
      ) : (
        <>
          <p className="text-caption leading-relaxed text-zoop-muted">
            회차 행을 만들어요. 정기 회차와 같은 단계를 밟고, 실제 진행은 회차
            실행기의 다음 바퀴가 해요. 같은 시각의 회차가 이미 있으면 만들지
            않아요.
          </p>
          <fieldset className="flex flex-col gap-2" disabled={pending}>
            <legend className="sr-only">시작 시각</legend>
            <label className="flex items-center gap-2 text-caption">
              <input
                type="radio"
                name="when"
                checked={when === 'now'}
                onChange={() => setWhen('now')}
              />
              지금(현재 분)
            </label>
            <label className="flex items-center gap-2 text-caption">
              <input
                type="radio"
                name="when"
                checked={when === 'slot'}
                onChange={() => setWhen('slot')}
              />
              시각 지정(KST)
            </label>
            {when === 'slot' && (
              <div className="flex flex-col gap-1">
                <label
                  htmlFor={slotId}
                  className="text-caption text-zoop-muted"
                >
                  회차 시각(KST, 분 단위)
                </label>
                <input
                  id={slotId}
                  type="datetime-local"
                  value={slot}
                  aria-invalid={invalid}
                  onChange={(event) => setSlot(event.target.value)}
                  className={SELECT}
                />
                <p className="text-caption text-zoop-muted">
                  미래 시각은 그 시각이 된 뒤 처리돼요.
                </p>
              </div>
            )}
          </fieldset>
          {invalid && (
            <p role="alert" className="text-caption text-zoop-alert">
              회차 시각을 분 단위로 입력해 주세요.
            </p>
          )}
        </>
      )}
      {caution && (
        <p role="note" className="text-caption text-zoop-alert">
          {caution}
        </p>
      )}
      {error && (
        <p role="alert" className="text-caption text-zoop-alert">
          {retry ? '재시도' : '시작'}를 접수하지 못했어요.{' '}
          {commandErrorMessage(error, action, sentSlot)}
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
          {pending ? '접수하고 있어요' : retry ? '재시도하기' : '회차 시작하기'}
        </button>
      </div>
    </form>
  );
}
