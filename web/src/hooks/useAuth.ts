import { useEffect } from 'react';
import { ACCESS_TOKEN_KEY, useAuthStore } from '@/stores/useAuthStore';
import { clearAuthentication } from '@/apis/auth/auth';

export function useAuth() {
  useEffect(() => {
    function syncSession(event: StorageEvent) {
      if (event.storageArea !== localStorage) return;
      if (event.key !== ACCESS_TOKEN_KEY && event.key !== null) return;
      if (!event.newValue) clearAuthentication();
      else
        useAuthStore.setState({
          accessToken: event.newValue,
          member: null,
          onboardingCompleted: null,
        });
    }
    window.addEventListener('storage', syncSession);
    return () => window.removeEventListener('storage', syncSession);
  }, []);
  const accessToken = useAuthStore((state) => state.accessToken);
  const member = useAuthStore((state) => state.member);
  const onboardingCompleted = useAuthStore(
    (state) => state.onboardingCompleted,
  );
  return {
    isAuthenticated: Boolean(accessToken),
    member,
    onboardingCompleted,
    logout: clearAuthentication,
  };
}
