import { Outlet, useLocation } from 'react-router-dom';
import BottomNav from './BottomNav';
import ServiceHeader from './ServiceHeader';
import SkipLink from './SkipLink';
import './briefing-login-surface.css';
import { useColorTheme } from '@/util/theme-color';

export default function AppLayout() {
  const { pathname } = useLocation();
  // 전환 효과는 상단 메뉴 단위(/stocks, /companies…)로만 다시 건다.
  // 같은 메뉴 안 이동(/companies/A → /companies/B)까지 다시 만들면 화면 상태와 그래프를 잃는다.
  const section = pathname.split('/')[1] ?? '';
  const isStocks = pathname === '/stocks';
  const dark = useColorTheme() === 'dark';
  // D-BRF-01/02와 다크 D-COM-01: 페이지와 탐색 바의 표면 역할을 공유한다.
  // 기업 상세 라이트는 #491 이전 바탕을 유지한다.
  const pageSurface =
    section === 'briefing' || (section === 'companies' && dark)
      ? ' bg-zoop-page! [&_.relationship-header]:bg-zoop-surface! [&_.service-bottom-nav]:bg-zoop-surface!'
      : '';
  return (
    <div
      className={`service-surface${isStocks ? ' stocks-login-surface' : ''}${pageSurface}`}
    >
      <SkipLink />
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
