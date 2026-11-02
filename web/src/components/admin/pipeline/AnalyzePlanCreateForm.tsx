import {
  useEffect,
  useId,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from 'react';
import { ApiError } from '@/apis/auth/ApiService';
import { createAnalyzePlan } from '@/apis/admin/jobs';
import {
  PRIMARY_BUTTON,
  SEARCH_INPUT,
  TEXTAREA,
  adminActionErrorMessage,
} from '@/components/admin/common/adminStyles';
import { useIdempotencyKey } from '@/hooks/useIdempotencyKey';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import type { AnalyzePlanJobCreate, JobCreated } from '@/types/admin/jobs';

type Fields = { planId: string; planDigest: string; reason: string };
type Field = keyof Fields;
const LABELS: Record<Field, string> = {
  planId: 'planId',
  planDigest: 'planDigest',
  reason: '접수 사유(감사 로그에 남아요)',
};
const FIELDS: Field[] = ['planId', 'planDigest', 'reason'];
function fieldError(field: Field, value: string) {
  const trimmed = value.trim();
  if (field === 'planId' && !/^s2plan-[0-9a-f]{64}$/.test(trimmed))
    return 's2plan- 뒤에 소문자 16진수 64자리인 계획 ID를 입력해 주세요.';
  if (field === 'planDigest' && !/^[0-9a-f]{64}$/.test(trimmed))
    return '소문자 16진수 64자리인 계획 다이제스트를 입력해 주세요.';
  if (field === 'reason' && (!trimmed || trimmed.length > 500))
    return '접수 사유를 1~500자로 입력해 주세요.';
  return undefined;
}

/** A-ADM-03: exact reference only; uncertain acceptance is reconciled with the frozen request/key. */
export default function AnalyzePlanCreateForm({
  disabled,
  onPendingChange,
  onCreated,
}: {
  disabled: boolean;
  onPendingChange: (pending: boolean) => void;
  onCreated: (result: JobCreated) => void;
}) {
  const id = useId();
  const [fields, setFields] = useState<Fields>({
    planId: '',
    planDigest: '',
    reason: '',
  });
  const [errors, setErrors] = useState<Partial<Fields>>({});
  const [pending, setPending] = useState(false);
  const [unknown, setUnknown] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const idempotency = useIdempotencyKey();
  const inFlight = useRef(false);
  const frozen = useRef<{ request: AnalyzePlanJobCreate; key: string } | null>(
    null,
  );
  const alive = useRef(false);
  const inputs = useRef<
    Partial<Record<Field, HTMLInputElement | HTMLTextAreaElement>>
  >({});
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current || (disabled && !frozen.current)) return;
    if (!frozen.current) {
      const next = Object.fromEntries(
        FIELDS.map((field) => [field, fieldError(field, fields[field])]),
      ) as Partial<Fields>;
      setErrors(next);
      const invalid = FIELDS.find((field) => next[field]);
      if (invalid) {
        inputs.current[invalid]?.focus();
        return;
      }
      const request: AnalyzePlanJobCreate = {
        kind: 'analyze_plan',
        reason: fields.reason.trim(),
        plan: {
          planId: fields.planId.trim(),
          planDigest: fields.planDigest.trim(),
        },
      };
      frozen.current = { request, key: idempotency.keyFor(request) };
    }
    const { request, key } = frozen.current;
    const revision = useAdminSessionStore.getState().revision;
    const current = () =>
      alive.current && useAdminSessionStore.getState().revision === revision;
    inFlight.current = true;
    setPending(true);
    setMessage(null);
    onPendingChange(true);
    try {
      const result = await createAnalyzePlan(request, key);
      if (!current()) return;
      if (
        result.job.kind !== 'analyze_plan' ||
        !result.job.planRun ||
        result.job.planRun.planId !== request.plan.planId ||
        result.job.planRun.planDigest !== request.plan.planDigest
      )
        throw new Error('Unbound analysis plan response');
      frozen.current = null;
      setUnknown(false);
      onPendingChange(false);
      onCreated(result);
    } catch (error) {
      if (!current()) return;
      const rejected =
        error instanceof ApiError &&
        error.status >= 400 &&
        error.status < 500 &&
        error.status !== 429;
      if (rejected) {
        idempotency.settle(error);
        frozen.current = null;
        setUnknown(false);
        onPendingChange(false);
        setMessage(adminActionErrorMessage(error));
      } else {
        setUnknown(true);
        setMessage(
          '접수 결과를 확인하지 못했어요. 입력과 요청 키를 유지하고 있어요. 같은 요청 확인으로 접수 여부를 확인해 주세요.',
        );
      }
    } finally {
      if (current()) {
        inFlight.current = false;
        setPending(false);
      }
    }
  }

  return (
    <form
      data-admin-editing={pending || Object.values(fields).some(Boolean)}
      noValidate
      aria-label="분석계획 접수"
      onSubmit={(event) => void submit(event)}
      className="flex flex-col gap-3"
    >
      <h3 className="text-body font-bold">분석계획 접수</h3>
      <p className="text-caption leading-relaxed text-zoop-muted">
        준비된 분석계획의 정확한 참조를 입력해 주세요. 대기열 접수 후 AI 처리를
        진행하며, 기사 수집·검수 승인·공개 반영은 하지 않아요.
      </p>
      {FIELDS.map((field) => {
        const props = {
          id: `${id}-${field}`,
          value: fields[field],
          disabled: pending || unknown || disabled,
          'aria-invalid': !!errors[field],
          'aria-describedby': errors[field]
            ? `${id}-${field}-error`
            : undefined,
          onBlur: () =>
            setErrors((old) => ({
              ...old,
              [field]: fieldError(field, fields[field]),
            })),
          onChange: (
            event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
          ) => setFields((old) => ({ ...old, [field]: event.target.value })),
        };
        return (
          <div key={field} className="flex flex-col gap-1">
            <label htmlFor={props.id} className="text-caption text-zoop-muted">
              {LABELS[field]}
            </label>
            {field === 'reason' ? (
              <textarea
                {...props}
                ref={(node) => {
                  if (node) inputs.current[field] = node;
                }}
                maxLength={500}
                className={TEXTAREA}
              />
            ) : (
              <input
                {...props}
                ref={(node) => {
                  if (node) inputs.current[field] = node;
                }}
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                className={SEARCH_INPUT}
              />
            )}
            {errors[field] && (
              <p
                id={`${id}-${field}-error`}
                className="text-caption text-zoop-alert"
              >
                {errors[field]}
              </p>
            )}
          </div>
        );
      })}
      <div
        role="status"
        aria-live="polite"
        className="text-caption text-zoop-muted"
      >
        {pending ? '분석계획 접수 여부를 확인하고 있어요.' : message}
      </div>
      <button
        type="submit"
        disabled={pending || (disabled && !unknown)}
        className={PRIMARY_BUTTON}
      >
        {pending ? '확인 중' : unknown ? '같은 요청 확인' : '분석계획 접수'}
      </button>
    </form>
  );
}
