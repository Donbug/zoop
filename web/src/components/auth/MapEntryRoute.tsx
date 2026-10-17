import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';

// D-AUT-01 / FS001, FS005: choose a start method before entering the map.
export default function MapEntryRoute() {
  const auth = useAuth();
  const location = useLocation();
  // The service entry always shows its start screen, even with a saved session.
  // Explicit map URLs remain available after login or guest start.
  if (!location.search)
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location, startScreen: true }}
      />
    );
  if (auth.checking)
    return (
      <p role="status" className="p-6 text-sm text-zoop-muted">
        로그인 상태를 확인하고 있어요.
      </p>
    );
  if (auth.status !== 'ready' || (!auth.isAuthenticated && !auth.isGuest))
    return <Navigate to="/login" replace state={{ from: location }} />;
  return <Outlet />;
}
