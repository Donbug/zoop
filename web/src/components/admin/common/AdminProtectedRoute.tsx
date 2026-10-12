import { useEffect, useState } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';

export default function AdminProtectedRoute() {
  const session = useAdminSessionStore((state) => state.session);
  const clearSession = useAdminSessionStore((state) => state.clearSession);
  const location = useLocation();
  const [now, setNow] = useState(Date.now);

  useEffect(() => {
    if (!session) return;
    const timer = window.setTimeout(
      () => {
        clearSession();
        setNow(Date.now());
      },
      Math.max(0, session.expiresAt - Date.now()),
    );
    return () => window.clearTimeout(timer);
  }, [session, clearSession]);

  if (!session || session.expiresAt <= now) {
    return <Navigate to="/admin/login" replace state={{ from: location }} />;
  }
  return <Outlet />;
}
