import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { ApiError } from '@/apis/auth/ApiService';
import { listPublicationRules, setPublicationRule } from '@/apis/admin/rules';
import {
  Empty,
  ErrorBox,
  Loading,
  MoreButton,
  Note,
  Section,
} from '@/components/admin/common/AdminUi';
import {
  BUTTON,
  PRIMARY_BUTTON,
  TEXTAREA,
  adminActionErrorMessage,
} from '@/components/admin/common/adminStyles';
import { useCursorPages } from '@/hooks/useCursorPages';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import type { PublicationRule, RuleSwitchResponse } from '@/types/admin/rules';
import { formatKst } from '@/util/format';

function switchError(error: Error) {
  if (error instanceof ApiError && error.status === 409)
    return '규칙 상태가 달라졌어요. 목록을 다시 읽고 확인해 주세요.';
  if (error instanceof ApiError && error.status === 422)
    return '사유를 확인해 주세요. 1~500자 한 줄로 쓰고, 이메일(@)·웹 주소(http)·비밀번호나 인증 관련 단어·토큰처럼 보이는 긴 문자열은 넣지 마세요.';
  return adminActionErrorMessage(error);
}

function RuleSwitchForm({
  rule,
  onCancel,
  onDone,
  onPending,
}: {
  rule: PublicationRule;
  onCancel: () => void;
  onDone: (result: RuleSwitchResponse) => void;
  onPending: (pending: boolean) => void;
}) {
  const id = useId();
  const [reason, setReason] = useState('');
  const [invalid, setInvalid] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const busy = useRef(false);
  // A changed/expired session must never apply an old mutation to another admin.
  const owner = useAdminSessionStore.getState().revision;
  async function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = reason.trim();
    if (busy.current) return;
    setInvalid(!trimmed || trimmed.length > 500);
    if (!trimmed || trimmed.length > 500) return;
    busy.current = true;
    setPending(true);
    onPending(true);
    setError(null);
    try {
      const result = await setPublicationRule(rule.id, !rule.enabled, trimmed);
      if (owner === useAdminSessionStore.getState().revision) onDone(result);
    } catch (caught) {
      if (owner === useAdminSessionStore.getState().revision)
        setError(caught instanceof Error ? caught : new Error(String(caught)));
    } finally {
      busy.current = false;
      if (owner === useAdminSessionStore.getState().revision) {
        setPending(false);
        onPending(false);
      }
    }
  }
  return (
    <form
      data-admin-editing="true"
      aria-label={`${rule.title} 전환 사유`}
      noValidate
      onSubmit={(event) => void submit(event)}
      className="flex flex-col gap-3 rounded-2xl bg-zoop-soft p-5"
    >
      <p className="text-body font-bold">
        {rule.title} · {rule.enabled ? '규칙 끄기' : '규칙 켜기'}
      </p>
      <Note>
        규칙은 공개 적격인 내용을 숨기기만 해요. HOLD를 공개하거나 AI 판정을
        바꾸지 않아요. 변경은 다음 그래프 버전부터 반영돼요. 사유는 감사 로그에
        남아요.
      </Note>
      <label htmlFor={id} className="text-caption">
        전환 사유
      </label>
      <textarea
        id={id}
        autoFocus
        value={reason}
        maxLength={500}
        aria-invalid={invalid}
        aria-describedby={`${id}-count ${id}-guide`}
        disabled={pending}
        onChange={(event) => setReason(event.target.value)}
        className={TEXTAREA}
      />
      <p id={`${id}-count`} className="text-caption text-zoop-muted">
        {reason.length}/500자
      </p>
      <p id={`${id}-guide`} className="text-caption text-zoop-muted">
        1~500자 한 줄로 써 주세요. 이메일·웹 주소·비밀번호/인증 관련
        단어·토큰처럼 긴 문자열은 넣지 마세요.
      </p>
      {invalid && (
        <p role="alert" className="text-caption text-zoop-alert">
          사유를 1~500자로 입력해 주세요.
        </p>
      )}
      {error && (
        <p role="alert" className="text-caption text-zoop-alert">
          {switchError(error)}
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
          {pending
            ? '바꾸고 있어요'
            : rule.enabled
              ? '규칙 끄기 확인'
              : '규칙 켜기 확인'}
        </button>
      </div>
    </form>
  );
}

// A-ADM-03: prototype admin/pipeline/rules.tsx structure and history, main contract policy.
export default function PublicationRules() {
  const revision = useAdminSessionStore((state) => state.revision);
  return <RulesContent key={revision} />;
}
function RulesContent() {
  const rules = useCursorPages(listPublicationRules);
  const [target, setTarget] = useState<PublicationRule | null>(null);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const refreshButton = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef<string | null>(null);
  const buttonRefs = useRef(new Map<string, HTMLButtonElement>());
  useEffect(() => {
    if (rules.status === 'success' && restoreFocus.current) {
      (
        buttonRefs.current.get(restoreFocus.current) ?? refreshButton.current
      )?.focus();
      restoreFocus.current = null;
    }
  }, [rules.status]);
  function close(id: string) {
    setTarget(null);
    buttonRefs.current.get(id)?.focus();
  }
  function done(result: RuleSwitchResponse) {
    setMessage(
      `${result.idempotent ? '이미 같은 상태예요.' : result.rule.enabled ? '규칙을 켰어요.' : '규칙을 껐어요.'} 다음 그래프 버전부터 반영돼요.`,
    );
    restoreFocus.current = result.rule.id;
    close(result.rule.id);
    rules.reload();
  }
  const count = (value: number | null) =>
    value === null ? '–' : value.toLocaleString('ko-KR');
  return (
    <Section title="자동 검수 규칙">
      <Note>
        공개 그래프에서 조건에 맞는 내용을 숨기는 정책이에요. 제공되지 않는
        집계는 –로 표시해요.
      </Note>
      {message && (
        <p role="status" className="text-caption">
          {message}
        </p>
      )}
      {rules.status === 'loading' && <Loading>규칙을 불러오고 있어요.</Loading>}
      {rules.status === 'error' && rules.error && (
        <ErrorBox
          title="규칙을 불러오지 못했어요"
          error={rules.error}
          onRetry={rules.reload}
        />
      )}
      {rules.status === 'success' && (
        <>
          <div className="flex items-center justify-between gap-3">
            <Note>조회 {formatKst(rules.pages[0].asOf)}</Note>
            <button
              type="button"
              className={BUTTON}
              disabled={pending || target !== null || rules.loadingMore}
              ref={refreshButton}
              onClick={rules.reload}
            >
              규칙 새로 읽기
            </button>
          </div>
          {!rules.items.length && <Empty>등록된 규칙이 없어요.</Empty>}
          <ul className="flex flex-col divide-y divide-zoop-line">
            {rules.items.map((rule) => (
              <li key={rule.id} className="flex flex-col gap-3 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                    <h3 className="text-body font-bold">
                      {rule.title} · {rule.enabled ? '켜짐' : '꺼짐'}
                    </h3>
                    <p className="text-caption text-zoop-muted">{rule.id}</p>
                    <p className="text-caption">{rule.summary}</p>
                    <Note>
                      다루는 보류 후보 {count(rule.eligible)} · 활성 버전 공개
                      사건 {count(rule.publishedEvents)} · 공개 후보{' '}
                      {count(rule.publishedCandidates)}
                    </Note>
                    <Note>
                      {rule.changedAt
                        ? `${formatKst(rule.changedAt)} ${rule.changedBy ?? ''} · 사유: ${rule.reason ?? '–'}`
                        : `기본값(${rule.defaultEnabled ? '켜짐' : '꺼짐'}) 그대로예요.`}
                    </Note>
                  </div>
                  <button
                    type="button"
                    ref={(node) => {
                      if (node) buttonRefs.current.set(rule.id, node);
                      else buttonRefs.current.delete(rule.id);
                    }}
                    aria-label={`${rule.title} ${rule.enabled ? '규칙 끄기' : '규칙 켜기'}`}
                    className={BUTTON}
                    disabled={
                      pending ||
                      (target !== null && target.id !== rule.id) ||
                      rules.loadingMore
                    }
                    onClick={() => {
                      setMessage('');
                      setTarget(rule);
                    }}
                  >
                    {rule.enabled ? '규칙 끄기' : '규칙 켜기'}
                  </button>
                </div>
                {rule.history.length > 0 && (
                  <details className="text-caption">
                    <summary className="cursor-pointer">
                      전환 이력 {rule.history.length}건 · {rule.title}
                    </summary>
                    <ol className="mt-2 flex flex-col gap-2">
                      {rule.history.map((change) => (
                        <li key={change.id}>
                          <p>
                            {change.enabled ? '켬' : '끔'} ·{' '}
                            {formatKst(change.changedAt)}
                          </p>
                          <p className="text-zoop-muted">
                            {change.adminEmail}: {change.reason}
                          </p>
                        </li>
                      ))}
                    </ol>
                  </details>
                )}
                {target?.id === rule.id && (
                  <RuleSwitchForm
                    key={rule.id}
                    rule={target}
                    onCancel={() => close(rule.id)}
                    onDone={done}
                    onPending={setPending}
                  />
                )}
              </li>
            ))}
          </ul>
          {rules.hasMore && !pending && !target && (
            <MoreButton
              loading={rules.loadingMore}
              error={rules.moreError}
              onClick={rules.loadMore}
            />
          )}
        </>
      )}
    </Section>
  );
}
