import { Outlet } from 'react-router-dom';
import BottomNav from './BottomNav';
import ServiceHeader from './ServiceHeader';

export default function AppLayout() {
  return (
    <div className="service-surface">
      <div className="hidden md:block">
        <ServiceHeader navLabel="데스크톱 주 메뉴" />
      </div>

      <main className="service-page-main">
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
