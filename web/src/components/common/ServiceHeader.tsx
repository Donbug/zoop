import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useColorTheme, useThemeToggle } from '@/util/theme-color';
import GraphIcon from '@/components/graph/GraphIcon';
import { useAiChatStore } from '@/stores/useAiChatStore';
import AccountMenu from './AccountMenu';
import ZoopWordmark from './ZoopWordmark';
import ThemeSunIcon from './ThemeSunIcon';
import './service-shell.css';
import { touchTarget } from '@/components/common/touch-target';

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
    useAiChatStore.getState().open(null, 'header');
  }

  return (
    <header className="relationship-header">
      <NavLink to="/" className="relationship-logo">
        {/* 로고는 ZOOP 워드마크로, 메뉴 타이틀과 같은 색에 예전 ZOOP 글자 높이로 둔다. */}
        <ZoopWordmark className="text-lead" />
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
          className={`${touchTarget} max-md:grid max-md:size-10 max-md:place-items-center`}
          onClick={toggleTheme}
        >
          {/* D-GRP-01 G1/G2: the next theme action remains available on mobile. */}
          {theme === 'dark' ? (
            <ThemeSunIcon />
          ) : (
            <GraphIcon name="moon" size={16} />
          )}
        </button>
        <AccountMenu />
      </div>
    </header>
  );
}
