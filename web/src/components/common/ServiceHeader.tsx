import { NavLink } from 'react-router-dom';
import { toggleTheme } from '@/util/theme-color';
import GraphIcon from '@/components/graph/GraphIcon';
import AccountMenu from './AccountMenu';
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
            disabled={icon !== 'moon'}
            aria-label={['AI 기능', '화면 모드', '알림'][i]}
            title={
              icon === 'moon'
                ? '라이트·다크 화면 전환'
                : '현재 담당 구현 범위 밖 기능'
            }
            onClick={icon === 'moon' ? toggleTheme : undefined}
          >
            <GraphIcon name={icon} size={16} />
          </button>
        ))}
        <AccountMenu />
      </div>
    </header>
  );
}
