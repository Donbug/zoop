import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listSignupTerms, signUp } from '@/apis/auth/session';
import { useAuth } from '@/hooks/useAuth';
import { useAuthCompletion } from '@/hooks/useAuthCompletion';
import type { SignupTerm } from '@/types/auth/session';
import SessionStatus from './SessionStatus';

const usable = (term: SignupTerm) =>
  term.bodyAvailable && !!term.body?.trim() && !!term.version?.trim();
export default function SignupForm() {
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
    (flow.error === 'EMAIL_TAKEN'
      ? '이미 가입된 이메일이에요. 다른 이메일을 입력하거나 로그인해 주세요.'
      : flow.error === 'TERMS_REQUIRED'
        ? '필수 약관과 동의한 버전을 다시 확인해 주세요.'
        : flow.error === 'RATE_LIMITED'
          ? '요청이 많아요. 잠시 후 다시 시도해 주세요.'
          : flow.error === 'INVALID_REQUEST'
            ? '입력한 가입 정보를 확인해 주세요.'
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
        <span aria-disabled="true">← 시작 화면으로</span>
      ) : (
        <Link to="/login">← 시작 화면으로</Link>
      )}
      <h1>이메일로 가입하기</h1>
      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          if (frozen || !terms || termsError || unavailable) return;
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
        <label htmlFor="signup-email">이메일</label>
        <input
          id="signup-email"
          type="email"
          autoComplete="email"
          placeholder="name@example.com"
          value={email}
          disabled={frozen}
          onChange={(e) => setEmail(e.target.value)}
        />
        <label htmlFor="signup-password">비밀번호</label>
        <input
          id="signup-password"
          type="password"
          autoComplete="new-password"
          value={password}
          disabled={frozen}
          onChange={(e) => setPassword(e.target.value)}
        />
        <label htmlFor="signup-name">표시 이름 (선택)</label>
        <input
          id="signup-name"
          autoComplete="nickname"
          value={name}
          disabled={frozen}
          onChange={(e) => setName(e.target.value)}
        />
        <fieldset disabled={frozen}>
          <legend>약관 동의</legend>
          {terms === null && !termsError && (
            <p role="status">약관을 불러오고 있어요.</p>
          )}
          {(termsError || unavailable) && (
            <div role="alert">
              <p>
                {termsError
                  ? '약관을 불러오지 못했어요.'
                  : '가입에 필요한 약관 본문이 준비되지 않았어요.'}
              </p>
              <button type="button" onClick={() => setAttempt((v) => v + 1)}>
                약관 다시 조회
              </button>
            </div>
          )}
          {terms && terms.length > 0 && (
            <>
              <label className="auth-check">
                <input
                  type="checkbox"
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
                <div key={t.id} className="auth-term">
                  <label className="auth-check">
                    <input
                      type="checkbox"
                      disabled={!usable(t)}
                      checked={!!accepted[t.id]}
                      onChange={(e) =>
                        setAccepted((old) => ({
                          ...old,
                          [t.id]: e.target.checked,
                        }))
                      }
                    />
                    {t.title} {t.required ? '(필수)' : '(선택)'}
                  </label>
                  <details>
                    <summary>{t.title} 본문 보기</summary>
                    <p>{usable(t) ? t.body : '약관 본문 준비 중'}</p>
                  </details>
                </div>
              ))}
            </>
          )}
        </fieldset>
        {message && (
          <p role="alert" id="signup-error">
            {message}
          </p>
        )}
        {flow.recovering ? (
          <>
            <button
              type="button"
              className="auth-primary"
              disabled={flow.busy}
              onClick={() => void flow.run(undefined, email.trim())}
            >
              가입 상태 다시 확인
            </button>
            <Link to="/login">로그인으로 계정 확인</Link>
          </>
        ) : (
          <button
            className="auth-primary"
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
