import { NavLink } from 'react-router-dom';
import { mainMenus } from '@/constants/navigation';

export default function BottomNav() {
  return (
    <nav
      aria-label="모바일 주 메뉴"
      className="border-t border-gray-200 bg-white"
    >
      <ul className="mx-auto flex h-16 max-w-md items-center">
        {mainMenus.map((menu) => (
          <li key={menu.to} className="flex-1">
            <NavLink
              to={menu.to}
              end={menu.to === '/'}
              className={({ isActive }) =>
                `flex h-16 items-center justify-center text-sm ${
                  isActive ? 'font-semibold text-zoop-ink' : 'text-zoop-muted'
                }`
              }
            >
              {menu.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
