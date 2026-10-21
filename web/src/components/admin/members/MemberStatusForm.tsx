import { useId, useState, type FormEvent } from 'react';
import { blockMember, unblockMember } from '@/apis/admin/members';
import {
  BUTTON,
  PRIMARY_BUTTON,
  TEXTAREA,
  adminActionErrorMessage,
} from '@/components/admin/common/adminStyles';
import { useIdempotencyKey } from '@/hooks/useIdempotencyKey';
import type { MemberRow, MemberStatusResult } from '@/types/admin/members';

/**
 * 회원 차단·차단 해제 입력(FS069-02). 사유는 필수이고 감사 로그에 남는다.
 * 응답을 받지 못해 같은 사유로 다시 보내면 같은 Idempotency-Key를 써서 한 번만 처리된다.
 */
export default function MemberStatusForm({
  member,
  onCancel,
  onDone,
}: {
  member: MemberRow;
  onCancel: () => void;
  onDone: (result: MemberStatusResult) => void;
}) {
  const block = member.status === 'active';
  const title = block ? '회원 차단' : '회원 차단 해제';
  const reasonId = useId();
  const idempotency = useIdempotencyKey();
  const [reason, setReason] = useState('');
  const [missing, setMissing] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const trimmed = reason.trim();
    setMissing(!trimmed);
    if (!trimmed) return;
    setError(null);
    setPending(true);
    const idempotencyKey = idempotency.keyFor({ block, reason: trimmed });
    try {
      const result = block
        ? await blockMember(member.id, trimmed, idempotencyKey)
        : await unblockMember(member.id, trimmed, idempotencyKey);
      onDone(result);
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
      noValidate
      aria-label={title}
      onSubmit={(event) => void submit(event)}
      className="flex flex-col gap-3 rounded-[3px] border-[0.667px] border-zoop-ink bg-zoop-paper p-4"
    >
      <p className="text-sm font-bold">{title}</p>
      <p className="text-[11px] leading-relaxed text-zoop-muted">
        <strong className="font-inter text-zoop-ink">{member.id}</strong>(
        {member.emailMasked})
        {block
          ? '을 차단해요. 열려 있는 모든 세션이 지금 끝나고, 다시 로그인할 수 없어요.'
          : '의 차단을 풀어요. 이 회원은 다시 로그인할 수 있어요.'}
      </p>
      <div className="flex flex-col gap-1">
        <label htmlFor={reasonId} className="text-[11px] text-zoop-muted">
          {block ? '차단 사유' : '해제 사유'}(감사 로그에 남아요)
        </label>
        <textarea
          id={reasonId}
          value={reason}
          disabled={pending}
          aria-invalid={missing}
          onChange={(event) => setReason(event.target.value)}
          className={TEXTAREA}
        />
      </div>
      {missing && (
        <p role="alert" className="text-[11px] text-zoop-alert">
          사유를 입력해 주세요.
        </p>
      )}
      {error && (
        <p role="alert" className="text-[11px] text-zoop-alert">
          {title}에 실패했어요. {adminActionErrorMessage(error)}
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
          {pending ? '처리하고 있어요' : block ? '차단하기' : '차단 해제하기'}
        </button>
      </div>
    </form>
  );
}
