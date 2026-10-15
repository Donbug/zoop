import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
export default function ProtectedRoute() {
  const location = useLocation();
  const auth = useAuth();
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
