import { useEffect, useRef, useState, type FormEvent } from 'react';
import { FOCUS_RING, NOTE } from './briefingStyles';

type Value = 'up' | 'down' | 'none';
type Target = {
  roundId: string;
  resultVersion: string;
  feature: 'briefing_round' | 'briefing_issue';
  targetId: string;
};
type Rating = Target & {
  storage: 'local_preview';
  value: Value;
  reason: string | null;
  csrfToken?: string;
};
const endpoint = '/api/local/briefing-feedback';
// Serialize reads so the first HttpOnly reviewer cookie is established before
// other cards load; parallel first visits would otherwise create different voters.
let readQueue: Promise<unknown> = Promise.resolve();
function loadRating(wanted: Target, signal: AbortSignal) {
  const request = readQueue.then(async () => {
    const response = await fetch(`${endpoint}?${new URLSearchParams(wanted)}`, {
      credentials: 'same-origin',
      cache: 'no-store',
      signal,
    });
    return readResponse(response, wanted);
  });
  readQueue = request.catch(() => undefined);
  return request;
}
const BUTTON = `inline-flex min-h-11 items-center gap-2 rounded-md border border-zoop-line px-3 text-xs font-semibold hover:bg-zoop-wash aria-pressed:border-zoop-ink aria-pressed:bg-zoop-ink aria-pressed:text-zoop-paper disabled:opacity-50 ${FOCUS_RING}`;

function Thumb({ down = false }: { down?: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      className={`size-4 ${down ? 'rotate-180' : ''}`}
    >
      <path d="M7 10v10H3V10h4Zm0 0 5-7c2 0 2 2 1 6h6a2 2 0 0 1 2 2l-2 7a2 2 0 0 1-2 2H7" />
    </svg>
  );
}

/** D-BRF-01/02: local preview votes never impersonate a member or rate another revision. */
type Props = Target & {
  subject: string;
};
export default function BriefingPreviewFeedback(props: Props) {
  return (
    <PreviewFeedbackForm
      key={JSON.stringify([
        props.roundId,
        props.resultVersion,
        props.feature,
        props.targetId,
      ])}
      {...props}
    />
  );
}
function PreviewFeedbackForm({ subject, ...target }: Props) {
  const identity = JSON.stringify(target);
  const [saved, setSaved] = useState<Rating | null>(null);
  const [pending, setPending] = useState(false);
  const [reason, setReason] = useState('');
  const [reasonOpen, setReasonOpen] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState<{
    message: string;
    vote?: { value: Value; reason: string | null };
  } | null>(null);
  const active = useRef(true);
  const locked = useRef(false);
  const generation = useRef(0);

  useEffect(() => {
    active.current = true;
    generation.current += 1;
    const controller = new AbortController();
    const wanted = JSON.parse(identity) as Target;
    async function load() {
      try {
        const data = await loadRating(wanted, controller.signal);
        if (!data.csrfToken) throw new Error('평가 상태를 확인하지 못했어요.');
        if (!controller.signal.aborted) {
          setSaved(data);
          setReason(data.reason ?? '');
          setReasonOpen(data.value === 'down');
        }
      } catch (error) {
        if (!controller.signal.aborted) setError({ message: message(error) });
      }
    }
    void load();
    return () => {
      active.current = false;
      generation.current += 1;
      controller.abort();
    };
  }, [identity, attempt]);

  async function send(value: Value, explanation: string | null = null) {
    if (!saved || locked.current) return;
    const epoch = generation.current;
    locked.current = true;
    setPending(true);
    setError(null);
    try {
      const response = await fetch(endpoint, {
        method: 'PUT',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-Preview-CSRF-Token': saved.csrfToken!,
        },
        body: JSON.stringify({ ...target, value, reason: explanation }),
      });
      const data = await readResponse(response, target);
      if (data.value !== value || data.reason !== explanation)
        throw new Error('저장 결과가 요청과 달라요. 다시 확인해 주세요.');
      if (active.current && generation.current === epoch) {
        setSaved({ ...data, csrfToken: saved.csrfToken });
        setReason(data.reason ?? '');
        setReasonOpen(value === 'down');
      }
    } catch (error) {
      if (active.current && generation.current === epoch)
        setError({
          message: message(error),
          vote: { value, reason: explanation },
        });
    } finally {
      locked.current = false;
      if (active.current && generation.current === epoch) setPending(false);
    }
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    void send('down', reason.trim() || null);
  }

  return (
    <div className="flex flex-col gap-2" aria-label={`${subject} 평가`}>
      <div
        role="group"
        aria-label={`${subject} 평가 선택`}
        className="flex flex-wrap gap-2"
      >
        <button
          type="button"
          className={BUTTON}
          disabled={!saved || pending}
          aria-pressed={saved?.value === 'up'}
          aria-label={`${subject}: 도움이 됐어요`}
          onClick={() => void send(saved?.value === 'up' ? 'none' : 'up')}
        >
          <Thumb /> 도움이 됐어요
        </button>
        <button
          type="button"
          className={BUTTON}
          disabled={!saved || pending}
          aria-pressed={saved?.value === 'down'}
          aria-label={`${subject}: 도움이 안 됐어요`}
          onClick={() => void send(saved?.value === 'down' ? 'none' : 'down')}
        >
          <Thumb down /> 도움이 안 됐어요
        </button>
      </div>
      <p role="status" aria-live="polite" className={NOTE}>
        {pending
          ? '평가를 저장하고 있어요.'
          : !saved && !error
            ? '내 평가를 확인하고 있어요.'
            : ''}
      </p>
      {reasonOpen && saved?.value === 'down' && (
        <form onSubmit={submit} className="flex flex-col gap-2">
          <label
            className="text-xs font-semibold"
            htmlFor={`preview-reason-${target.feature}-${target.targetId}`}
          >
            어떤 점이 아쉬웠나요?{' '}
            <span className="font-normal text-zoop-muted">(선택)</span>
          </label>
          <textarea
            id={`preview-reason-${target.feature}-${target.targetId}`}
            maxLength={200}
            rows={3}
            value={reason}
            disabled={pending}
            onChange={(event) => setReason(event.target.value)}
            placeholder="예: 선정 이유를 더 자세히 알고 싶어요."
            className={`w-full rounded-md border border-zoop-line bg-zoop-paper p-3 text-xs ${FOCUS_RING}`}
          />
          <div className="flex items-center justify-between gap-2">
            <span className={NOTE}>{reason.length}/200자</span>
            <button
              type="submit"
              disabled={pending || !saved}
              className={BUTTON}
            >
              확인
            </button>
          </div>
        </form>
      )}
      {error && (
        <div
          role={error.vote ? 'alert' : 'status'}
          className={`text-xs ${error.vote ? 'text-zoop-alert' : 'text-zoop-muted'}`}
        >
          <p>{error.message}</p>
          {error.vote && saved && (
            <button
              type="button"
              className={`${BUTTON} mt-2`}
              disabled={pending}
              onClick={() => void send(error.vote!.value, error.vote!.reason)}
            >
              같은 평가 다시 저장
            </button>
          )}
          <button
            type="button"
            disabled={pending}
            className={`${BUTTON} mt-2`}
            onClick={() => {
              setSaved(null);
              setError(null);
              setAttempt((n) => n + 1);
            }}
          >
            내 평가 다시 확인
          </button>
        </div>
      )}
    </div>
  );
}

function message(error: unknown) {
  return error instanceof Error
    ? error.message
    : '평가를 저장하지 못했어요. 다시 시도해 주세요.';
}
async function readResponse(
  response: Response,
  target: Target,
): Promise<Rating> {
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      data?.error?.message ?? '미리보기 평가에 연결하지 못했어요.',
    );
  if (
    data.storage !== 'local_preview' ||
    !['up', 'down', 'none'].includes(data.value) ||
    (data.reason !== null &&
      (typeof data.reason !== 'string' ||
        data.reason.length > 200 ||
        data.value !== 'down')) ||
    Object.entries(target).some(([key, value]) => data[key] !== value)
  )
    throw new Error('다른 회차·버전의 평가 응답이에요. 다시 확인해 주세요.');
  return data as Rating;
}
