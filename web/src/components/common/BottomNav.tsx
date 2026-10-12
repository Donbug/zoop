import { NavLink } from 'react-router-dom';

const menus = [
  { to: '/home', label: '홈' },
  { to: '/search', label: '탐색' },
  { to: '/my', label: 'MY' },
];

export default function BottomNav() {
  return (
    <nav
      aria-label="모바일 주 메뉴"
      className="border-t border-gray-200 bg-white"
    >
      <ul className="mx-auto flex h-16 max-w-md items-center">
        {menus.map((menu) => (
          <li key={menu.to} className="flex-1">
            <NavLink
              to={menu.to}
              className={({ isActive }) =>
                `flex h-16 items-center justify-center text-sm ${
                  isActive ? 'font-semibold text-black' : 'text-gray-400'
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
