import { useId, useState, type FormEvent } from 'react';
import { ApiError } from '@/apis/auth/ApiService';
import { decideAnalysisCandidate } from '@/apis/admin/pipeline';
import { Note } from '@/components/admin/common/AdminUi';
import {
  BUTTON,
  PRIMARY_BUTTON,
  TEXTAREA,
  adminActionErrorMessage,
} from '@/components/admin/common/adminStyles';
import { relationLabel } from '@/components/admin/pipeline/candidateLabels';
import { useIdempotencyKey } from '@/hooks/useIdempotencyKey';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import type {
  CandidateDecisionResponse,
  CandidateRelation,
} from '@/types/admin/pipeline';

function decisionError(error: Error) {
  if (error instanceof ApiError && error.code === 'REVISION_CONFLICT')
    return '그 사이 관계 상태나 AI 원천이 바뀌었어요. 상세를 새로 읽고 다시 확인해 주세요.';
  if (error instanceof ApiError && error.code === 'VALIDATION_FAILED')
    return '원문 인용이나 원천 권리 검사를 통과하지 못해 승인할 수 없어요.';
  return adminActionErrorMessage(error);
}

// A-ADM-03 후보 결정 (FS059·FS067-02, decideAnalysisCandidate)
// - 프로토타입 candidates.tsx의 관계 허용·거부와 ReasonDialog를 옮겼다. 결정은 관계 단위이고 사유가 있어야 보낸다.
// - 승인은 HOLD에 대한 운영자 최종 승인이며 공개가 아니다(publicChanged=false). 공개는 다음 그래프 버전에서 따로 한다.
export default function CandidateDecisionForm({
  candidateId,
  relation,
  decision,
  onCancel,
  onDone,
}: {
  candidateId: string;
  relation: CandidateRelation;
  decision: 'allow' | 'reject';
  onCancel: () => void;
  onDone: (result: CandidateDecisionResponse) => void;
}) {
  const allow = decision === 'allow';
  const title = allow ? '관계 승인' : '관계 거부';
  const reasonId = useId();
  const idempotency = useIdempotencyKey();
  const [reason, setReason] = useState('');
  const [invalid, setInvalid] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  // 세션이 바뀐 뒤 이전 관리자의 결정 결과를 새 관리자 화면에 반영하지 않는다.
  const owner = useAdminSessionStore.getState().revision;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const trimmed = reason.trim();
    setInvalid(!trimmed || trimmed.length > 500);
    if (!trimmed || trimmed.length > 500) return;
    setError(null);
    setPending(true);
    const request = {
      decision,
      reason: trimmed,
      relationId: relation.relationId,
      expectedRevision: relation.revision,
      expectedSourceVersion: relation.sourceVersion,
      expectedSourceRevision: relation.sourceRevision,
    };
    try {
      const result = await decideAnalysisCandidate(
        candidateId,
        request,
        idempotency.keyFor(request),
      );
      if (owner === useAdminSessionStore.getState().revision) onDone(result);
    } catch (caught) {
      idempotency.settle(caught);
      if (owner !== useAdminSessionStore.getState().revision) return;
      setError(caught instanceof Error ? caught : new Error(String(caught)));
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
      <p className="text-sm font-bold">
        {title} · {relationLabel(relation.relationType)} {relation.source} →{' '}
        {relation.target}
      </p>
      <Note>
        {allow
          ? '보류된 관계를 운영자가 최종 승인해요. 승인해도 바로 공개되지 않고, 다음 그래프 버전을 만들 때 반영돼요.'
          : '이 관계를 그래프 후보에서 빼요. 거부한 결정은 되돌릴 수 없어요.'}{' '}
        사유는 감사 로그에 남아요.
      </Note>
      <label htmlFor={reasonId} className="text-xs">
        {allow ? '승인 사유' : '거부 사유'}
      </label>
      <textarea
        id={reasonId}
        autoFocus
        value={reason}
        maxLength={500}
        disabled={pending}
        aria-invalid={invalid}
        aria-describedby={`${reasonId}-count`}
        onChange={(event) => setReason(event.target.value)}
        className={`${TEXTAREA} bg-zoop-paper`}
      />
      <p id={`${reasonId}-count`} className="text-[11px] text-zoop-muted">
        {reason.length}/500자
      </p>
      {invalid && (
        <p role="alert" className="text-xs text-zoop-alert">
          사유를 1~500자로 입력해 주세요.
        </p>
      )}
      {error && (
        <p role="alert" className="text-xs text-zoop-alert">
          {title}에 실패했어요. {decisionError(error)}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <button
          type="button"
          className={BUTTON}
          disabled={pending}
          onClick={onCancel}
        >
          취소
        </button>
        <button type="submit" className={PRIMARY_BUTTON} disabled={pending}>
          {pending ? '보내고 있어요' : allow ? '승인하기' : '거부하기'}
        </button>
      </div>
    </form>
  );
}
