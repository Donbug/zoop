import { useId, useState, type FormEvent } from 'react';
import { ApiError } from '@/apis/auth/ApiService';
import { activateGraphVersion } from '@/apis/admin/graphVersions';
import {
  BUTTON,
  PRIMARY_BUTTON,
  TEXTAREA,
  adminActionErrorMessage,
} from '@/components/admin/common/adminStyles';
import { useIdempotencyKey } from '@/hooks/useIdempotencyKey';
import type {
  GraphVersion,
  GraphVersionActivated,
} from '@/types/admin/graphVersions';

/**
 * 전환 실패 문구. 409 REVISION_CONFLICT는 표시 버전이 바뀐 경우뿐 아니라 근거 철회·비공개·권한 변경으로
 * 공개 조건이 달라진 경우에도 오므로 원인을 단정하지 않는다.
 */
function activationErrorMessage(error: Error) {
  if (error instanceof ApiError && error.code === 'REVISION_CONFLICT')
    return '표시 버전이나 근거 공개 조건이 달라져 전환하지 못했어요. 목록을 새로 고친 뒤 다시 확인해 주세요.';
  if (error instanceof ApiError && error.code === 'RESOURCE_NOT_FOUND')
    return '이 버전을 찾을 수 없어요. 목록을 새로 고쳐 주세요.';
  return adminActionErrorMessage(error);
}

/**
 * 그래프 버전 전환(FS059, activateGraphVersion). 사유는 필수이고 감사 로그에 남는다.
 * 화면에서 본 현재 버전을 함께 보내 그 사이 다른 관리자가 바꿨으면 서버가 거절한다.
 * 응답을 받지 못해 같은 사유로 다시 보내면 같은 Idempotency-Key를 써서 한 번만 처리된다.
 */
export default function GraphVersionForm({
  version,
  activeVersionId,
  stale = false,
  onPendingChange,
  onCancel,
  onDone,
}: {
  version: GraphVersion;
  activeVersionId: string | null;
  /** 목록의 표시 버전이 페이지마다 달라 다시 읽어야 한다. 이때는 새로 제출하지 않는다. */
  stale?: boolean;
  /** 요청이 진행 중인지 상위에 알린다. 진행 중에는 다른 버전 선택·폼 교체를 막는다. */
  onPendingChange: (pending: boolean) => void;
  onCancel: () => void;
  onDone: (result: GraphVersionActivated) => void;
}) {
  const reasonId = useId();
  const idempotency = useIdempotencyKey();
  const [reason, setReason] = useState('');
  const [missing, setMissing] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || stale) return;
    const trimmed = reason.trim();
    setMissing(!trimmed);
    if (!trimmed) return;
    setError(null);
    setPending(true);
    onPendingChange(true);
    const key = idempotency.keyFor({
      versionId: version.id,
      activeVersionId,
      reason: trimmed,
    });
    try {
      const result = await activateGraphVersion(
        version.id,
        trimmed,
        activeVersionId,
        key,
      );
      onPendingChange(false);
      onDone(result);
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
      aria-label="그래프 버전 전환"
      onSubmit={(event) => void submit(event)}
      className="flex flex-col gap-3 rounded-[3px] border-[0.667px] border-zoop-ink bg-zoop-paper p-4"
    >
      <p className="text-sm font-bold">그래프 버전 전환</p>
      <p className="text-[11px] leading-relaxed text-zoop-muted">
        사용자에게 보이는 그래프를{' '}
        <strong className="font-inter text-zoop-ink">
          {activeVersionId ?? '없음'}
        </strong>
        에서 <strong className="font-inter text-zoop-ink">{version.id}</strong>
        로 바꿔요. 서버가 이 버전의 그래프와 근거를 다시 확인한 뒤에만 바뀌어요.
      </p>
      <div className="flex flex-col gap-1">
        <label htmlFor={reasonId} className="text-[11px] text-zoop-muted">
          전환 사유(감사 로그에 남아요)
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
      {stale && (
        <p role="alert" className="text-[11px] text-zoop-alert">
          목록을 다시 불러온 뒤 전환해 주세요.
        </p>
      )}
      {error && (
        <p role="alert" className="text-[11px] text-zoop-alert">
          버전을 바꾸지 못했어요. {activationErrorMessage(error)}
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
        <button
          type="submit"
          disabled={pending || stale}
          className={PRIMARY_BUTTON}
        >
          {pending ? '바꾸고 있어요' : `${version.id}로 전환`}
        </button>
      </div>
    </form>
  );
}
