import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { ApiError } from '@/apis/auth/ApiService';
import { setFeedback } from '@/apis/feedback/feedback';
import { selectMemberId, useAuthStore } from '@/stores/useAuthStore';
import type {
  FeedbackFeature,
  FeedbackItem,
  FeedbackValue,
} from '@/types/feedback';

const FOCUS_RING =
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink';
const TOGGLE = `inline-flex h-8 items-center gap-1 rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-paper px-2.5 text-[11px] font-semibold text-zoop-muted hover:bg-zoop-wash aria-pressed:border-zoop-ink aria-pressed:bg-zoop-ink aria-pressed:text-zoop-paper disabled:opacity-60 ${FOCUS_RING}`;

type Props = {
  feature: FeedbackFeature;
  targetId: string;
  /** 사용자가 본 결과 버전(브리핑은 feedbackVersion, 구버전 API는 graphVersion). 서버와 다르면 저장하지 않는다(409). */
  targetVersion?: string | null;
  /** 접근 가능한 이름에 쓰는 대상 이름(예: "이 브리핑", "핵심 이슈 1") */
  subject: string;
  /** 서버에 저장된 내 평가. 아직 모르면 undefined */
  saved?: FeedbackValue;
  savedReason?: string | null;
  /** 저장이 확인되면 부모의 상태를 바꾼다. */
  onSaved?: (item: FeedbackItem) => void;
};

/**
 * AI 결과 평가(FS066-01): 도움이 됐어요 / 도움이 안 됐어요.
 * - 로그인 회원만 평가한다. 비회원에게는 로그인 안내를 둔다.
 * - 원하는 최종 상태를 보낸다. 눌린 쪽을 다시 누르면 취소(none), 다른 쪽을 누르면 바꾼다.
 * - 저장이 확인된 상태만 눌린 상태로 보인다. 실패하면 이전 상태를 두고 같은 목표로 다시 시도할 수 있다.
 * - 싫어요에는 이유를 짧게 덧붙일 수 있다(선택).
 */
export default function FeedbackButtons(props: Props) {
  const memberId = useAuthStore(selectMemberId);
  const location = useLocation();
  const checking = useAuthStore((s) => s.status === 'checking');
  const revision = useAuthStore((s) => s.sessionRevision);
  if (checking)
    return (
      <p role="status" className="text-[11px] text-zoop-muted">
        로그인 상태를 확인하고 있어요.
      </p>
    );
  if (!memberId)
    return (
      <p className="flex flex-wrap items-center gap-x-2 text-[11px] text-zoop-muted">
        <span>평가는 로그인한 회원만 남길 수 있어요.</span>
        <Link
          to="/login"
          state={{ from: `${location.pathname}${location.search}` }}
          className={`font-semibold text-zoop-ink underline underline-offset-4 ${FOCUS_RING}`}
        >
          로그인하고 평가하기
        </Link>
      </p>
    );
  return (
    <MemberFeedback
      key={`${memberId}:${revision}:${props.feature}:${props.targetId}:${props.targetVersion ?? ''}`}
      {...props}
    />
  );
}

function MemberFeedback({
  feature,
  targetId,
  targetVersion,
  subject,
  saved,
  savedReason,
  onSaved,
}: Props) {
  const revision = useAuthStore((s) => s.sessionRevision);
  const active = useRef(true);
  const locked = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const [value, setValue] = useState<FeedbackValue | undefined>(saved);
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState<{
    error: unknown;
    value: FeedbackValue;
    reason?: string;
  } | null>(null);
  const [reasonOpen, setReasonOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [storedReason, setStoredReason] = useState<string | null | undefined>(
    undefined,
  );
  const currentReason =
    storedReason !== undefined ? storedReason : (savedReason ?? null);
  const current = value ?? saved ?? 'none';

  async function send(next: FeedbackValue, withReason?: string) {
    if (
      locked.current ||
      !active.current ||
      useAuthStore.getState().sessionRevision !== revision ||
      saved === undefined
    )
      return;
    locked.current = true;
    setPending(true);
    setFailed(null);
    try {
      const item = await setFeedback({
        feature,
        targetId,
        value: next,
        targetVersion: targetVersion ?? null,
        reason: next === 'down' ? withReason?.trim() || null : null,
      });
      if (
        !active.current ||
        useAuthStore.getState().sessionRevision !== revision
      )
        return;
      if (
        item.feature !== feature ||
        item.targetId !== targetId ||
        item.targetVersion !== (targetVersion ?? null) ||
        item.value !== next
      )
        throw new Error('평가 저장 응답이 요청과 일치하지 않아요.');
      setValue(item.value);
      setStoredReason(item.reason);
      setReason(item.reason ?? '');
      onSaved?.(item);
      setReasonOpen(item.value === 'down' && withReason === undefined);
      if (item.value !== 'down') setReason('');
    } catch (error) {
      if (
        active.current &&
        useAuthStore.getState().sessionRevision === revision
      )
        setFailed({ error, value: next, reason: withReason });
    } finally {
      locked.current = false;
      if (active.current) setPending(false);
    }
  }

  function submitReason(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = reason.trim();
    void send('down', text);
  }

  const toggle = (kind: 'up' | 'down', label: string) => (
    <button
      type="button"
      aria-pressed={current === kind}
      aria-label={`${subject}: ${label}`}
      disabled={pending || saved === undefined}
      onClick={() => void send(current === kind ? 'none' : kind)}
      className={TOGGLE}
    >
      {label}
    </button>
  );

  return (
    <div className="flex flex-col gap-1.5">
      <div
        role="group"
        aria-label={`${subject} 평가`}
        className="flex flex-wrap items-center gap-1.5"
      >
        {toggle('up', '도움이 됐어요')}
        {toggle('down', '도움이 안 됐어요')}
        <span role="status" className="text-[11px] text-zoop-muted">
          {current === 'up' && '도움이 됐다고 남겼어요'}
          {current === 'down' && '도움이 안 됐다고 남겼어요'}
        </span>
      </div>
      {!reasonOpen && current === 'down' && (
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-zoop-muted">
          {currentReason && <p>남긴 이유: {currentReason}</p>}
          <button
            type="button"
            className={TOGGLE}
            disabled={pending}
            onClick={() => {
              setReason(currentReason ?? '');
              setReasonOpen(true);
            }}
          >
            {currentReason ? '이유 수정' : '이유 추가'}
          </button>
        </div>
      )}
      {reasonOpen && current === 'down' && (
        <form
          onSubmit={submitReason}
          className="flex flex-wrap items-center gap-2"
        >
          <label className="sr-only" htmlFor={`reason-${feature}-${targetId}`}>
            이유(선택)
          </label>
          <input
            id={`reason-${feature}-${targetId}`}
            value={reason}
            disabled={pending || saved === undefined}
            maxLength={200}
            placeholder="어떤 점이 아쉬웠나요? (선택)"
            onChange={(event) => setReason(event.target.value)}
            className={`h-8 min-w-0 flex-1 rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-paper px-2.5 text-[11px] text-zoop-ink ${FOCUS_RING}`}
          />
          <button
            type="submit"
            disabled={pending}
            className={`${TOGGLE} text-zoop-ink`}
          >
            이유 보내기
          </button>
        </form>
      )}
      {failed && (
        <p
          role="alert"
          className="flex flex-wrap items-center gap-2 text-[11px] text-zoop-alert"
        >
          {failed.error instanceof ApiError && failed.error.status === 409
            ? '결과가 바뀌어 평가를 저장하지 않았어요. 화면을 새로 고친 뒤 다시 평가해 주세요.'
            : '평가를 저장하지 못했어요. 이전 평가는 그대로예요.'}
          {/* 409는 같은 버전으로 다시 보내도 거절되므로 새로 고침을 안내하고 다시 시도는 두지 않는다. */}
          {!(
            failed.error instanceof ApiError && failed.error.status === 409
          ) && (
            <button
              type="button"
              disabled={pending}
              onClick={() => void send(failed.value, failed.reason)}
              className={`font-semibold text-zoop-ink underline ${FOCUS_RING}`}
            >
              다시 시도
            </button>
          )}
        </p>
      )}
    </div>
  );
}
