import { Outlet } from 'react-router-dom';
import BottomNav from './BottomNav';
import DesktopHeader from './DesktopHeader';

export default function AppLayout() {
  return (
    <div className="min-h-dvh bg-gray-50">
      <div className="hidden md:block">
        <DesktopHeader />
      </div>

      <main className="mx-auto w-full max-w-screen-xl px-4 pb-20 md:px-8 md:pb-8">
        <Outlet />
      </main>

      <div className="fixed inset-x-0 bottom-0 z-50 md:hidden">
        <BottomNav />
      </div>
    </div>
  );
}
