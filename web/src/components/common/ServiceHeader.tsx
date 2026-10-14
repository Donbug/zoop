import { NavLink } from 'react-router-dom';
import GraphIcon from '@/components/graph/GraphIcon';
import { selectMemberId, useAuthStore } from '@/stores/useAuthStore';
import './service-shell.css';

const menus = [
  { to: '/', label: '지도', icon: 'map' },
  { to: '/stocks', label: '종목', icon: 'search' },
  { to: '/briefing', label: '브리핑', icon: 'briefing' },
  { to: '/my', label: '내 종목', icon: 'bookmark' },
] as const;

// Shared shell from Figma 619:1824. Non-map feature bodies intentionally stay empty.
export default function ServiceHeader({
  navLabel = '주 메뉴',
}: {
  navLabel?: string;
}) {
  const token = useAuthStore(selectMemberId);
  const member = useAuthStore((s) => s.member);
  return (
    <header className="relationship-header">
      <NavLink to="/" className="relationship-logo">
        <strong>줍</strong>
        <span>Zoop</span>
      </NavLink>
      <nav aria-label={navLabel}>
        {menus.map((menu) => (
          <NavLink key={menu.to} to={menu.to} end={menu.to === '/'}>
            <GraphIcon name={menu.icon} size={15} />
            {menu.label}
          </NavLink>
        ))}
        <button>
          <GraphIcon name="ai" size={15} />
          AI질의
        </button>
      </nav>
      <div className="relationship-user-tools">
        {['ai', 'moon', 'bell'].map((icon, i) => (
          <button
            key={icon}
            disabled
            aria-label={['AI 기능', '화면 모드', '알림'][i]}
            title="현재 담당 구현 범위 밖 기능"
          >
            <GraphIcon name={icon} size={16} />
          </button>
        ))}
        <NavLink to={token ? '/my' : '/login'} className="relationship-user">
          <span>
            <GraphIcon name="user" />
          </span>
          {token ? (member?.displayName ?? '회원') : '로그인'}
          <GraphIcon name="chevron" size={12} />
        </NavLink>
      </div>
    </header>
  );
}
