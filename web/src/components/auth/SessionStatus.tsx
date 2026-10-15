import { useAuth } from '@/hooks/useAuth';
import { useAuthCompletion } from '@/hooks/useAuthCompletion';
import { authAlert, authSmallButton, authStatus } from './authStyles';

export default function SessionStatus() {
  const auth = useAuth();
  const flow = useAuthCompletion();
  return (
    <section aria-label="회원 세션 확인" className="flex flex-col gap-2">
      {auth.status === 'checking' ? (
        <p role="status" className={authStatus}>
          로그인 상태를 확인하고 있어요.
        </p>
      ) : auth.status === 'error' ? (
        <div role="alert" className="flex flex-col gap-2">
          <p className={authAlert}>로그인 상태를 확인하지 못했어요.</p>
          <button
            type="button"
            className={authSmallButton}
            onClick={auth.retry}
          >
            세션 다시 확인
          </button>
        </div>
      ) : (
        <>
          <p className="text-xs text-zoop-muted">
            로그인한 계정으로 계속할 수 있어요.
          </p>
          <button
            type="button"
            className={authSmallButton}
            disabled={flow.busy}
            onClick={() => void flow.run()}
          >
            계속하기
          </button>
          {flow.error && (
            <p role="alert" className={authAlert}>
              {flow.error}
            </p>
          )}
        </>
      )}
    </section>
  );
}
