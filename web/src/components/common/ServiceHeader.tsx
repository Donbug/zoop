import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useColorTheme, useThemeToggle } from '@/util/theme-color';
import GraphIcon from '@/components/graph/GraphIcon';
import { useAiChatStore } from '@/stores/useAiChatStore';
import AccountMenu from './AccountMenu';
import './service-shell.css';

const menus = [
  { to: '/', label: '지도' },
  { to: '/stocks', label: '종목' },
  { to: '/briefing', label: '브리핑' },
  { to: '/my', label: '내 종목' },
] as const;

// D-GRP-01 shared service shell. Non-map feature bodies intentionally stay empty.
export default function ServiceHeader({
  navLabel = '주 메뉴',
}: {
  navLabel?: string;
}) {
  const navigate = useNavigate();
  const toggleTheme = useThemeToggle();
  const theme = useColorTheme();
  const themeLabel =
    theme === 'dark' ? '라이트 모드로 바꾸기' : '다크 모드로 바꾸기';
  const { pathname } = useLocation();
  /** D-AI-01: the AI drawer lives on the map. Elsewhere, go to the map first; the selected target is kept as it is. */
  function openAiChat() {
    if (pathname !== '/') navigate('/');
    useAiChatStore.getState().open(undefined);
  }

  return (
    <header className="relationship-header">
      <NavLink to="/" className="relationship-logo">
        {/* 로고는 영문 ZOOP 한 단어로, 메뉴 타이틀과 같은 색·크기로 둔다. */}
        <strong className="font-heading">ZOOP</strong>
      </NavLink>
      <nav aria-label={navLabel}>
        {menus.map((menu) => (
          <NavLink key={menu.to} to={menu.to} end={menu.to === '/'}>
            {menu.label}
          </NavLink>
        ))}
        <button type="button" onClick={openAiChat}>
          AI 채팅
        </button>
      </nav>
      <div className="relationship-user-tools">
        <button
          type="button"
          aria-label={themeLabel}
          title={themeLabel}
          className="max-md:grid max-md:size-10 max-md:place-items-center"
          onClick={toggleTheme}
        >
          {/* D-GRP-01 G1/G2: the next theme action remains available on mobile. */}
          {theme === 'dark' ? (
            <svg
              aria-hidden="true"
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            >
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42" />
            </svg>
          ) : (
            <GraphIcon name="moon" size={16} />
          )}
        </button>
        <AccountMenu />
      </div>
    </header>
  );
}
