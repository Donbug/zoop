import { createRoot } from 'react-dom/client';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import MapPage from '../../src/pages/map/MapPage';
import { useAuthStore } from '../../src/stores/useAuthStore';
import '../../src/index.css';
import { applyInitialTheme } from '../../src/util/theme-color';
applyInitialTheme();
// Local-only visual fixture. No login, credentials, persisted account or live API.
useAuthStore.setState({
  status: 'ready',
  member: null,
  onboardingCompleted: true,
  session: {
    authenticated: true,
    kind: 'guest',
    user: null,
    setup: { completed: true, tutorialCompleted: false },
    csrfToken: null,
    expiresAt: null,
  },
});
createRoot(document.getElementById('root')!).render(
  <>
    <p className="fixed right-1 bottom-0 z-[90] bg-zoop-paper p-1 text-[10px] text-zoop-muted">
      로컬 UI · 합성 그래프 · 실제 회원/API 검증 아님
    </p>
    <MemoryRouter
      initialEntries={[
        new URLSearchParams(window.location.search).get('view') === 'selected'
          ? '/?mode=all&select=node:KRX:005930'
          : '/?mode=all',
      ]}
    >
      <Routes>
        <Route path="*" element={<MapPage />} />
      </Routes>
    </MemoryRouter>
  </>,
);
