import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
export default function ProtectedRoute() {
  const location = useLocation();
  const auth = useAuth();
  // 이미 회원 세션이 있는 상태의 재확인(loadSession(true))은 화면을 내리지 않는다.
  // 결과가 같은 회원이면 화면 상태가 그대로 남고, 다른 회원·익명이면 그때 갱신되거나 로그인으로 간다.
  const rechecking = auth.checking && !!auth.member;
  if (rechecking) return <Outlet />;
  if (auth.status === 'checking')
    return <p role="status">로그인 상태를 확인하고 있어요.</p>;
  if (auth.status === 'error')
    return (
      <div role="alert">
        <p>로그인 상태를 확인하지 못했어요.</p>
        <button onClick={auth.retry}>세션 다시 확인</button>
      </div>
    );
  if (!auth.isAuthenticated)
    return <Navigate to="/login" replace state={{ from: location }} />;
  return <Outlet />;
}
