import { createRoot } from 'react-dom/client';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import MapPage from '../../src/pages/map/MapPage';
import { useAuthStore } from '../../src/stores/useAuthStore';
import '../../src/index.css';
import { companies } from '../../src/mocks/graph/fixture';
if (new URLSearchParams(window.location.search).has('dense')) {
  const sample = companies[0];
  companies.push(
    ...Array.from({ length: 80 }, (_, index) => ({
      ...sample,
      id: `SYNTHETIC:PREVIEW-${index}`,
      label: `합성 추가 기업 ${index + 1}`,
      logoUrl: null,
      isFocus: false,
    })),
  );
}
// Local-only visual fixture. No login, credentials, persisted account or live API.
const user = {
  id: 'synthetic-preview',
  email: 'viewer@synthetic.invalid',
  displayName: '합성 검증 회원',
};
useAuthStore.setState({
  status: 'ready',
  member: user,
  onboardingCompleted: true,
  session: {
    authenticated: true,
    kind: 'member',
    user,
    setup: { completed: true, tutorialCompleted: true },
    csrfToken: null,
    expiresAt: null,
  },
});
createRoot(document.getElementById('root')!).render(
  <>
    <p className="fixed right-1 bottom-0 z-[90] bg-white p-1 text-[10px]">
      로컬 합성 데이터 · 실제 회원/API 검증 아님
    </p>
    <MemoryRouter initialEntries={['/?mode=all']}>
      <Routes>
        <Route path="*" element={<MapPage />} />
      </Routes>
    </MemoryRouter>
  </>,
);
