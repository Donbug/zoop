import { Outlet, useLocation } from 'react-router-dom';
import BottomNav from './BottomNav';
import ServiceHeader from './ServiceHeader';

export default function AppLayout() {
  const { pathname } = useLocation();
  // 전환 효과는 상단 메뉴 단위(/stocks, /companies…)로만 다시 건다.
  // 같은 메뉴 안 이동(/companies/A → /companies/B)까지 다시 만들면 화면 상태와 그래프를 잃는다.
  const section = pathname.split('/')[1] ?? '';
  return (
    <div className="service-surface">
      <a
        href="#service-main"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById('service-main')?.focus();
        }}
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:bg-zoop-paper focus:p-3"
      >
        본문으로 건너뛰기
      </a>
      <ServiceHeader navLabel="데스크톱 주 메뉴" />

      <main
        key={section}
        id="service-main"
        tabIndex={-1}
        className="service-page-main motion-safe:animate-service-enter has-[>.company-workspace]:w-full! has-[>.company-workspace]:max-w-[1320px] has-[>.company-workspace]:pt-6!"
      >
        <Outlet />
      </main>

      <div className="fixed inset-x-0 bottom-0 z-50 md:hidden">
        <div className="service-bottom-nav">
          <BottomNav />
        </div>
      </div>
    </div>
  );
}
