import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// globals를 쓰지 않으므로 Testing Library의 자동 정리를 직접 연결한다.
afterEach(() => {
  cleanup();
  localStorage.clear();
  sessionStorage.clear();
});
