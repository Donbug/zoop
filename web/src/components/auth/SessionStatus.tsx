import { useAuth } from '@/hooks/useAuth';
import { useAuthCompletion } from '@/hooks/useAuthCompletion';
import { authAlert, authSmallButton, authStatus } from './authStyles';
import LoadingIndicator from '@/components/common/LoadingIndicator';

export default function SessionStatus() {
  const auth = useAuth();
  const flow = useAuthCompletion();
  return (
    <section aria-label="회원 세션 확인" className="flex flex-col gap-2">
      {auth.status === 'checking' ? (
        <LoadingIndicator
          label="로그인 상태를 확인하고 있어요."
          className={`${authStatus} flex min-h-9 w-full`}
        />
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
          <p className="text-caption text-zoop-muted">
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
