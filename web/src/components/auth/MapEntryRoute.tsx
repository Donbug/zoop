import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { readSocialLinkResult } from '@/components/common/socialLinkResult';

// D-AUT-01 / FS001, FS005: choose a start method before entering the map.
export default function MapEntryRoute() {
  const auth = useAuth();
  const location = useLocation();
  if (auth.checking)
    return (
      <p role="status" className="p-6 text-body text-zoop-muted">
        로그인 상태를 확인하고 있어요.
      </p>
    );
  if (auth.status !== 'ready' || (!auth.isAuthenticated && !auth.isGuest))
    return <Navigate to="/login" replace state={{ from: location }} />;
  if (auth.isAuthenticated && auth.onboardingCompleted === false) {
    // 설정 중에 시작한 소셜 계정 연결의 결과(?social=)는 온보딩에서 이어서 알린다.
    const social = readSocialLinkResult(location.search);
    return (
      <Navigate
        to={social ? `/onboarding?social=${social}` : '/onboarding'}
        replace
      />
    );
  }
  return <Outlet />;
}
