import { NavLink, Outlet } from 'react-router-dom';
import { adminMenus } from '@/constants/navigation';

export default function AdminLayout() {
  return (
    <div className="min-h-dvh md:grid md:grid-cols-[14rem_1fr]">
      <aside className="border-r border-gray-200 bg-white p-6">
        <p className="mb-6 text-xl font-bold">줍 관리자</p>
        <nav aria-label="관리자 메뉴" className="flex flex-col gap-4">
          {adminMenus.map((menu) => (
            <NavLink key={menu.to} to={menu.to} end={menu.to === '/admin'}>
              {menu.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="min-w-0 px-4 md:px-8">
        <Outlet />
      </main>
    </div>
  );
}
