import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';

/** 회원 전용 라우트. 세션을 확인한 뒤 회원이 아니면 로그인(D-AUT-01)으로 보낸다. */
export default function ProtectedRoute() {
  const location = useLocation();
  const { checking, failed, retry, isAuthenticated } = useAuth();

  if (checking) {
    return (
      <p role="status" className="p-6 text-sm text-gray-500">
        로그인 상태를 확인하고 있어요
      </p>
    );
  }

  // 확인에 실패한 것을 로그아웃으로 보지 않는다.
  if (failed) {
    return (
      <div
        role="alert"
        className="mx-auto flex max-w-md items-center gap-3 p-6 text-sm"
      >
        <p className="flex-1 font-semibold text-red-700">
          로그인 상태를 확인하지 못했어요
        </p>
        <button
          type="button"
          onClick={() => void retry()}
          className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 font-medium"
        >
          다시 시도
        </button>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}
