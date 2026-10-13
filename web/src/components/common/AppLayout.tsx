import { Outlet } from 'react-router-dom';
import ServiceHeader from './ServiceHeader';
import '@/components/graph/relationship-map.css';

export default function AppLayout() {
  return (
    <div className="relationship-map">
      <ServiceHeader />
      <main className="relationship-main">
        <Outlet />
      </main>
    </div>
  );
}
