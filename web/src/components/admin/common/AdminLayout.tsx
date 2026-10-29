import { useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { adminMenus } from '@/constants/navigation';
import { logoutAdmin } from '@/apis/admin/auth';
import { useAdminSessionStore } from '@/stores/useAdminSessionStore';
import { BUTTON, FOCUS_RING } from './adminStyles';
import { useThemeToggle } from '@/util/theme-color';

function SidebarChevron({ direction }: { direction: 'left' | 'right' }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" className="size-4">
      <path
        d={direction === 'left' ? 'm14.5 5-7 7 7 7' : 'm9.5 5 7 7-7 7'}
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// A-ADM-01·02·02b·03·04·04b·05·05b 공통 관리자 내비게이션.
export default function AdminLayout() {
  const navigate = useNavigate();
  const toggleTheme = useThemeToggle();
  const admin = useAdminSessionStore((state) => state.admin);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const logout = async () => {
    await logoutAdmin().catch(() => undefined);
    navigate('/admin/login', { replace: true });
  };

  return (
    <div
      className={`admin-surface min-h-dvh grid grid-cols-1 bg-zoop-paper text-zoop-ink ${sidebarOpen ? 'md:grid-cols-[14rem_1fr]' : 'md:grid-cols-1'}`}
    >
      <a
        href="#admin-main"
        onClick={() => document.getElementById('admin-main')?.focus()}
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-full focus:bg-zoop-paper focus:px-4 focus:py-2"
      >
        본문으로 건너뛰기
      </a>
      <aside
        id="admin-sidebar"
        hidden={!sidebarOpen}
        className="min-w-0 border-b-[0.667px] border-zoop-line bg-zoop-paper p-4 text-zoop-ink md:border-r-[0.667px] md:border-b-0 md:p-6"
      >
        <div className="mb-5 flex items-center justify-between gap-3">
          <p className="text-xl font-bold">줍 관리자</p>
          <button
            type="button"
            aria-controls="admin-sidebar"
            aria-expanded={sidebarOpen}
            aria-label="메뉴 숨기기"
            title="메뉴 숨기기"
            onClick={() => setSidebarOpen(false)}
            className={`grid size-9 shrink-0 place-items-center rounded-full text-zoop-muted hover:bg-zoop-soft hover:text-zoop-ink ${FOCUS_RING}`}
          >
            <SidebarChevron direction="left" />
          </button>
        </div>
        <nav aria-label="관리자 메뉴" className="flex flex-col gap-4">
          {adminMenus.map((menu) => (
            <NavLink
              key={menu.to}
              to={menu.to}
              end={menu.to === '/admin'}
              className={({ isActive }) =>
                `rounded-full px-4 py-3 text-xs transition-colors duration-150 ${FOCUS_RING} ${
                  isActive
                    ? 'bg-zoop-ink font-semibold text-zoop-paper'
                    : 'text-zoop-muted hover:bg-zoop-wash hover:text-zoop-ink'
                }`
              }
            >
              {menu.label}
            </NavLink>
          ))}
        </nav>
        <button
          type="button"
          className={`${BUTTON} mt-4`}
          onClick={toggleTheme}
          aria-label="화면 모드 전환"
        >
          테마 전환
        </button>
        {admin && (
          <div className="mt-8 flex flex-col gap-2 border-t-[0.667px] border-zoop-line pt-4">
            <p className="flex flex-col gap-0.5">
              <strong className="text-xs">{admin.displayName}</strong>
              <span className="font-inter text-[11px] text-zoop-faint">
                {admin.role}
              </span>
            </p>
            <button
              type="button"
              onClick={() => void logout()}
              className={`${BUTTON} w-full`}
            >
              관리자 로그아웃
            </button>
          </div>
        )}
      </aside>
      <main
        id="admin-main"
        tabIndex={-1}
        className="min-w-0 px-4 outline-none md:px-8"
      >
        {!sidebarOpen && (
          <div className="pt-4">
            <button
              type="button"
              aria-controls="admin-sidebar"
              aria-expanded={sidebarOpen}
              aria-label="메뉴 열기"
              title="메뉴 열기"
              onClick={() => setSidebarOpen(true)}
              className={`grid size-9 place-items-center rounded-full bg-zoop-soft text-zoop-ink hover:bg-zoop-line ${FOCUS_RING}`}
            >
              <SidebarChevron direction="right" />
            </button>
          </div>
        )}
        <Outlet />
      </main>
    </div>
  );
}
