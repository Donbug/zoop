import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  completeSocialSignup,
  listSignupTerms,
  signUp,
} from '@/apis/auth/session';
import { useAuth } from '@/hooks/useAuth';
import { useAuthCompletion } from '@/hooks/useAuthCompletion';
import type { SignupTerm } from '@/types/auth/session';
import SessionStatus from './SessionStatus';
import MarkdownContent from '@/components/common/MarkdownContent';
import {
  authAlert,
  authHeading,
  authInput,
  authLabel,
  authLink,
  authPrimaryButton,
  authSmallButton,
  authStatus,
  authNote,
} from './authStyles';

const checkLabel =
  'flex min-h-8 items-center gap-2.5 text-sm font-medium text-gray-900';
const checkbox = 'size-[18px] shrink-0 accent-gray-950';

const usable = (term: SignupTerm) =>
  term.bodyAvailable && !!term.body?.trim() && !!term.version?.trim();
/**
 * D-AUT-02 회원가입. social이면 소셜 콜백이 검증한 신규 인증으로 가입을 마친다(/signup?social=pending).
 * 이때 이메일·비밀번호는 받지 않고 표시 이름과 약관 동의만 보낸다.
 */
export default function SignupForm({ social = false }: { social?: boolean }) {
  const auth = useAuth();
  const flow = useAuthCompletion();
  const [attempt, setAttempt] = useState(0);
  const [terms, setTerms] = useState<SignupTerm[] | null>(null);
  const [termsError, setTermsError] = useState(false);
  const [accepted, setAccepted] = useState<Record<string, boolean>>({});
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [validation, setValidation] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(async () => {
      if (!active) return;
      setTerms(null);
      setTermsError(false);
      setAccepted({});
      try {
        const result = await listSignupTerms();
        if (active) setTerms(result);
      } catch {
        if (active) setTermsError(true);
      }
    });
    return () => {
      active = false;
    };
  }, [attempt]);
  const required = terms?.filter((t) => t.required) ?? [];
  const unavailable =
    terms !== null &&
    (required.length === 0 || required.some((t) => !usable(t)));
  const consentReady =
    required.length > 0 && required.every((t) => usable(t) && accepted[t.id]);
  const frozen = flow.busy || flow.recovering;
  const message =
    validation ??
    (social && flow.error === 'ACCESS_DENIED'
      ? '소셜 인증이 만료됐거나 확인되지 않았어요. 로그인 화면에서 소셜 로그인을 다시 시작해 주세요.'
      : social && flow.error === 'SOCIAL_LINK_REQUIRED'
        ? '이미 같은 이메일로 가입한 계정이 있어요. 이메일로 로그인한 뒤 소셜 계정을 연결해 주세요.'
        : flow.error === 'EMAIL_TAKEN'
          ? '이미 가입된 이메일이에요. 다른 이메일을 입력하거나 로그인해 주세요.'
          : flow.error === 'TERMS_REQUIRED'
            ? '필수 약관과 동의한 버전을 다시 확인해 주세요.'
            : flow.error === 'RATE_LIMITED'
              ? '요청이 많아요. 잠시 후 다시 시도해 주세요.'
              : flow.error === 'INVALID_REQUEST'
                ? '입력한 가입 정보를 확인해 주세요. 비밀번호는 8자 이상 32자 이하이며 제어 문자와 흔한 비밀번호는 쓸 수 없어요.'
                : flow.error && flow.error.match(/^[A-Z_]+$/)
                  ? '가입하지 못했어요. 입력 내용을 확인하고 다시 시도해 주세요.'
                  : flow.error);
  if (
    (auth.status !== 'ready' && !submitted) ||
    (auth.isAuthenticated && !submitted)
  )
    return <SessionStatus />;
  return (
    <>
      {frozen ? (
        <span
          aria-disabled="true"
          className="text-sm font-semibold text-gray-400"
        >
          ← 시작 화면으로
        </span>
      ) : (
        <Link
          to="/login"
          className="self-start text-sm font-semibold text-gray-700 hover:text-gray-950"
        >
          ← 시작 화면으로
        </Link>
      )}
      <h1 className={authHeading}>
        {social ? '소셜 계정으로 가입하기' : '이메일로 가입하기'}
      </h1>
      {social && (
        <p className={authNote}>
          소셜 계정에서 확인한 이메일로 가입해요. 표시 이름과 약관 동의만
          확인하면 돼요.
        </p>
      )}
      <form
        className="flex flex-col gap-2.5"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          if (frozen || !terms || termsError || unavailable) return;
          if (social) {
            if (!consentReady) {
              setValidation('필수 약관에 동의해 주세요.');
              return;
            }
            setValidation(null);
            setSubmitted(true);
            void flow.run(() =>
              completeSocialSignup({
                ...(name.trim() ? { displayName: name.trim() } : {}),
                agreements: terms.filter(usable).map((t) => ({
                  id: t.id,
                  version: t.version!,
                  accepted: !!accepted[t.id],
                })),
              }),
            );
            return;
          }
          const trimmed = email.trim();
          if (!trimmed || !password) {
            setValidation('이메일과 비밀번호를 입력해 주세요.');
            return;
          }
          if (
            trimmed.length > 254 ||
            !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)
          ) {
            setValidation('올바른 이메일 형식을 입력해 주세요.');
            return;
          }
          // SignupRequest.password: 8~32 Unicode code point, trim 없음. 제어 문자·흔한 비밀번호는 서버가 거절한다.
          const length = [...password].length;
          if (length < 8 || length > 32) {
            setValidation('비밀번호는 8자 이상 32자 이하로 입력해 주세요.');
            return;
          }
          if (!consentReady) {
            setValidation('필수 약관에 동의해 주세요.');
            return;
          }
          setValidation(null);
          setSubmitted(true);
          void flow.run(
            () =>
              signUp({
                email: trimmed,
                password,
                ...(name.trim() ? { displayName: name.trim() } : {}),
                agreements: terms.filter(usable).map((t) => ({
                  id: t.id,
                  version: t.version!,
                  accepted: !!accepted[t.id],
                })),
              }),
            trimmed,
          );
        }}
      >
        {!social && (
          <>
            <label htmlFor="signup-email" className={authLabel}>
              이메일
            </label>
            <input
              id="signup-email"
              className={authInput}
              type="email"
              autoComplete="email"
              placeholder="name@example.com"
              value={email}
              disabled={frozen}
              onChange={(e) => setEmail(e.target.value)}
            />
            <label htmlFor="signup-password" className={authLabel}>
              비밀번호
            </label>
            <input
              id="signup-password"
              className={authInput}
              type="password"
              autoComplete="new-password"
              value={password}
              disabled={frozen}
              onChange={(e) => setPassword(e.target.value)}
              aria-describedby="signup-password-rule"
            />
            <p id="signup-password-rule" className={authNote}>
              8자 이상 32자 이하로 입력해 주세요. 공백은 그대로 사용되며, 제어
              문자와 흔한 비밀번호는 쓸 수 없어요.
            </p>
          </>
        )}
        <label htmlFor="signup-name" className={authLabel}>
          표시 이름 (선택)
        </label>
        <input
          id="signup-name"
          className={authInput}
          autoComplete="nickname"
          value={name}
          disabled={frozen}
          onChange={(e) => setName(e.target.value)}
        />
        <fieldset disabled={frozen} className="mt-3 flex flex-col gap-2">
          <legend className={authLabel}>약관 동의</legend>
          {terms === null && !termsError && (
            <p role="status" className={authStatus}>
              약관을 불러오고 있어요.
            </p>
          )}
          {(termsError || unavailable) && (
            <div role="alert" className="flex flex-col gap-2">
              <p className={authAlert}>
                {termsError
                  ? '약관을 불러오지 못했어요.'
                  : '가입에 필요한 약관 본문이 준비되지 않았어요.'}
              </p>
              <button
                type="button"
                className={authSmallButton}
                onClick={() => setAttempt((v) => v + 1)}
              >
                약관 다시 조회
              </button>
            </div>
          )}
          {terms && terms.length > 0 && (
            <>
              <label className={`${checkLabel} border-b border-gray-200 pb-2`}>
                <input
                  type="checkbox"
                  className={checkbox}
                  aria-label="모두 동의"
                  checked={
                    terms.filter(usable).length > 0 &&
                    terms.filter(usable).every((t) => accepted[t.id])
                  }
                  onChange={(e) =>
                    setAccepted(
                      Object.fromEntries(
                        terms
                          .filter(usable)
                          .map((t) => [t.id, e.target.checked]),
                      ),
                    )
                  }
                />
                모두 동의
              </label>
              {terms.map((t) => (
                <div key={t.id} className="mt-2" data-term-id={t.id}>
                  <label className={checkLabel}>
                    <input
                      type="checkbox"
                      className={checkbox}
                      disabled={!usable(t)}
                      checked={!!accepted[t.id]}
                      onChange={(e) =>
                        setAccepted((old) => ({
                          ...old,
                          [t.id]: e.target.checked,
                        }))
                      }
                    />
                    {t.title}{' '}
                    <span className="text-zoop-muted">
                      {t.required ? '(필수)' : '(선택)'}
                    </span>
                  </label>
                  <details className="ml-7 text-xs text-zoop-muted">
                    <summary className="cursor-pointer py-1">
                      {t.title} 본문 보기
                    </summary>
                    <div className="mt-1 max-h-[200px] overflow-auto bg-white p-3 text-gray-700">
                      {usable(t) ? (
                        <MarkdownContent source={t.body!} headingOffset={1} />
                      ) : (
                        '약관 본문 준비 중'
                      )}
                    </div>
                  </details>
                </div>
              ))}
            </>
          )}
        </fieldset>
        {message && (
          <p role="alert" id="signup-error" className={authAlert}>
            {message}
          </p>
        )}
        {social &&
          (flow.error === 'ACCESS_DENIED' ||
            flow.error === 'SOCIAL_LINK_REQUIRED') && (
            <Link to="/login" className={authLink}>
              로그인 화면으로
            </Link>
          )}
        {flow.recovering ? (
          <>
            <button
              type="button"
              className={authPrimaryButton}
              disabled={flow.busy}
              onClick={() => void flow.run(undefined, email.trim())}
            >
              가입 상태 다시 확인
            </button>
            <Link to="/login" className={authLink}>
              로그인으로 계정 확인
            </Link>
          </>
        ) : (
          <button
            className={authPrimaryButton}
            disabled={flow.busy || terms === null || termsError || unavailable}
          >
            {flow.busy
              ? '가입과 로그인 상태를 확인하고 있어요…'
              : '가입하고 시작하기'}
          </button>
        )}
        {flow.error === 'TERMS_REQUIRED' && (
          <button
            type="button"
            className={authSmallButton}
            disabled={frozen}
            onClick={() => setAttempt((v) => v + 1)}
          >
            약관 새로 확인
          </button>
        )}
      </form>
    </>
  );
}
