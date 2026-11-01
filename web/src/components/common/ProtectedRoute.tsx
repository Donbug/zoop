import { Fragment } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import LoadingIndicator from '@/components/common/LoadingIndicator';
export default function ProtectedRoute() {
  const location = useLocation();
  const auth = useAuth();
  const onboardingRoute =
    location.pathname === '/onboarding' ||
    location.pathname.startsWith('/onboarding/');
  // 하위 화면은 회원 ID별로 따로 만든다. 같은 회원이면 상태가 남고, 회원이 바뀌면 이전 회원의 화면 상태를 버린다.
  const outlet = (
    <Fragment key={auth.member?.id ?? 'anonymous'}>
      <Outlet />
    </Fragment>
  );
  // 이미 회원 세션이 있는 상태의 재확인(loadSession(true))은 화면을 내리지 않는다.
  // 결과가 같은 회원이면 그대로 남고, 다른 회원이면 위 key로 새로 만들고, 익명이면 로그인으로 간다.
  if (auth.checking && auth.member) {
    if (auth.onboardingCompleted === false && !onboardingRoute)
      return <Navigate to="/onboarding" replace />;
    return outlet;
  }
  if (auth.status === 'checking')
    return (
      <LoadingIndicator
        label="로그인 상태를 확인하고 있어요."
        className="flex min-h-screen w-full"
      />
    );
  if (auth.status === 'error')
    return (
      <div role="alert">
        <p>로그인 상태를 확인하지 못했어요.</p>
        <button onClick={auth.retry}>세션 다시 확인</button>
      </div>
    );
  if (!auth.isAuthenticated)
    return <Navigate to="/login" replace state={{ from: location }} />;
  if (auth.onboardingCompleted === false && !onboardingRoute)
    return <Navigate to="/onboarding" replace />;
  return outlet;
}
