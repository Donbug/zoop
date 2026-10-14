import { useAuth } from '@/hooks/useAuth';
import { useAuthCompletion } from '@/hooks/useAuthCompletion';

export default function SessionStatus() {
  const auth = useAuth();
  const flow = useAuthCompletion();
  return (
    <section aria-label="회원 세션 확인">
      {auth.status === 'checking' ? (
        <p role="status">로그인 상태를 확인하고 있어요.</p>
      ) : auth.status === 'error' ? (
        <div role="alert">
          <p>로그인 상태를 확인하지 못했어요.</p>
          <button onClick={auth.retry}>세션 다시 확인</button>
        </div>
      ) : (
        <>
          <p>로그인한 계정으로 계속할 수 있어요.</p>
          <button disabled={flow.busy} onClick={() => void flow.run()}>
            계속하기
          </button>
          {flow.error && <p role="alert">{flow.error}</p>}
        </>
      )}
    </section>
  );
}
