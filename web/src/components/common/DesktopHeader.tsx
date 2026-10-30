import { NavLink } from 'react-router-dom';
import { mainMenus } from '@/constants/navigation';

export default function DesktopHeader() {
  return (
    <header className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex h-16 max-w-screen-xl items-center justify-between px-8">
        <NavLink to="/" className="text-title font-bold text-zoop-ink">
          zoop
        </NavLink>
        <nav aria-label="데스크톱 주 메뉴">
          <ul className="flex items-center gap-8">
            {mainMenus.map((menu) => (
              <li key={menu.to}>
                <NavLink
                  to={menu.to}
                  end={menu.to === '/'}
                  className={({ isActive }) =>
                    isActive
                      ? 'font-semibold text-zoop-ink'
                      : 'text-zoop-ink hover:text-zoop-ink'
                  }
                >
                  {menu.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </header>
  );
}
