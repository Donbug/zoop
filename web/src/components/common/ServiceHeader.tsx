import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { toggleTheme } from '@/util/theme-color';
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
  const { pathname } = useLocation();
  /** D-AI-01: the AI drawer lives on the map. Elsewhere, go to the map first; the selected target is kept as it is. */
  function openAiChat() {
    if (pathname !== '/') navigate('/');
    useAiChatStore.getState().open(undefined);
  }

  return (
    <header className="relationship-header">
      <NavLink to="/" className="relationship-logo">
        <strong>줍</strong>
        <span>Zoop</span>
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
          disabled
          aria-label="AI 기능"
          title="현재 담당 구현 범위 밖 기능"
        >
          <GraphIcon name="ai" size={16} />
        </button>
        <button
          aria-label="화면 모드"
          title="라이트·다크 화면 전환"
          onClick={toggleTheme}
        >
          <GraphIcon name="moon" size={16} />
        </button>
        <AccountMenu />
      </div>
    </header>
  );
}
