import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';
import { useOnboardingStore } from '@/stores/useOnboardingStore';

// globals를 쓰지 않으므로 Testing Library의 자동 정리를 직접 연결한다.
// Zustand store는 모듈 상태라 테스트마다 초기화한다.
afterEach(() => {
  cleanup();
  localStorage.clear();
  sessionStorage.clear();
  useOnboardingStore.getState().reset();
});
