import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { adminMenus } from '@/constants/navigation';
import { logoutAdmin } from '@/apis/admin/auth';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';

export default function AdminLayout() {
  const navigate = useNavigate();
  const admin = useAdminSessionStore((state) => state.admin);

  const logout = async () => {
    await logoutAdmin().catch(() => undefined);
    navigate('/admin/login', { replace: true });
  };

  return (
    <div className="min-h-dvh md:grid md:grid-cols-[14rem_1fr]">
      <aside className="border-r-[0.667px] border-zoop-line bg-zoop-paper p-6 text-zoop-ink">
        <p className="mb-6 text-xl font-bold">줍 관리자</p>
        <nav aria-label="관리자 메뉴" className="flex flex-col gap-4">
          {adminMenus.map((menu) => (
            <NavLink key={menu.to} to={menu.to} end={menu.to === '/admin'}>
              {menu.label}
            </NavLink>
          ))}
        </nav>
        {admin && (
          <div className="mt-8 flex flex-col gap-2 border-t-[0.667px] border-zoop-line pt-4">
            <p className="flex flex-col gap-0.5">
              <strong className="text-xs">{admin.displayName}</strong>
              <span className="font-inter text-[10px] text-zoop-faint">
                {admin.role}
              </span>
            </p>
            <button
              type="button"
              onClick={() => void logout()}
              className="h-8 rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-paper px-3 text-xs font-semibold text-zoop-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink"
            >
              관리자 로그아웃
            </button>
          </div>
        )}
      </aside>
      <main className="min-w-0 px-4 md:px-8">
        <Outlet />
      </main>
    </div>
  );
}
