import {
  createBrowserRouter,
  Navigate,
  RouterProvider,
  useLocation,
  useParams,
} from 'react-router-dom';
import AppLayout from '@/components/common/AppLayout';
import ProtectedRoute from '@/components/common/ProtectedRoute';
import AdminLayout from '@/components/admin/common/AdminLayout';
import AdminProtectedRoute from '@/components/admin/common/AdminProtectedRoute';
import OnboardingLayout from '@/components/onboarding/OnboardingLayout';

function LegacyHomeRedirect() {
  const location = useLocation();
  return <Navigate to={`/${location.search}${location.hash}`} replace />;
}

function LegacyDetailRedirect() {
  const { id } = useParams();
  return <Navigate to={`/companies/${encodeURIComponent(id ?? '')}`} replace />;
}

// Exported so route ownership/protection can be regression-tested without navigation mocks.
// eslint-disable-next-line react-refresh/only-export-components
export const router = createBrowserRouter([
  {
    path: '/login',
    lazy: async () => ({
      Component: (await import('@/pages/auth/login/LoginPage')).default,
    }),
  },
  {
    path: '/signup',
    lazy: async () => ({
      Component: (await import('@/pages/auth/signup/SignupPage')).default,
    }),
  },
  {
    path: '/',
    lazy: async () => ({
      Component: (await import('@/pages/map/MapPage')).default,
    }),
  },
  {
    element: <AppLayout />,
    children: [
      {
        path: '/stocks',
        lazy: async () => ({
          Component: (await import('@/pages/stocks/StocksPage')).default,
        }),
      },
      {
        path: '/companies/:id',
        lazy: async () => ({
          Component: (await import('@/pages/company/CompanyDetailPage'))
            .default,
        }),
      },
      {
        path: '/briefing',
        lazy: async () => ({
          Component: (await import('@/pages/briefing/BriefingPage')).default,
        }),
      },
      {
        element: <ProtectedRoute />,
        children: [
          {
            path: '/my',
            lazy: async () => ({
              Component: (await import('@/pages/my/MyStocksPage')).default,
            }),
          },
        ],
      },
    ],
  },
  {
    element: <ProtectedRoute />,
    children: [
      {
        path: '/onboarding',
        element: <OnboardingLayout />,
        children: [
          {
            index: true,
            lazy: async () => ({
              Component: (
                await import('@/pages/onboarding/investment/InvestmentStatusPage')
              ).default,
            }),
          },
          {
            path: 'account',
            lazy: async () => ({
              Component: (
                await import('@/pages/onboarding/account/VirtualAccountPage')
              ).default,
            }),
          },
          {
            path: 'watchlist',
            lazy: async () => ({
              Component: (
                await import('@/pages/onboarding/watchlist/WatchlistSetupPage')
              ).default,
            }),
          },
        ],
      },
    ],
  },
  {
    path: '/admin/login',
    lazy: async () => ({
      Component: (await import('@/pages/admin/login/AdminLoginPage')).default,
    }),
  },
  {
    element: <AdminProtectedRoute />,
    children: [
      {
        path: '/admin',
        element: <AdminLayout />,
        children: [
          {
            index: true,
            lazy: async () => ({
              Component: (
                await import('@/pages/admin/dashboard/AdminDashboardPage')
              ).default,
            }),
          },
          {
            path: 'stats',
            lazy: async () => ({
              Component: (await import('@/pages/admin/stats/AdminStatsPage'))
                .default,
            }),
          },
          {
            path: 'feedback',
            lazy: async () => ({
              Component: (
                await import('@/pages/admin/feedback/AdminFeedbackPage')
              ).default,
            }),
          },
          {
            path: 'pipeline',
            lazy: async () => ({
              Component: (
                await import('@/pages/admin/pipeline/AdminPipelinePage')
              ).default,
            }),
          },
          {
            path: 'briefings',
            lazy: async () => ({
              Component: (
                await import('@/pages/admin/briefings/AdminBriefingsPage')
              ).default,
            }),
          },
          {
            path: 'ai',
            lazy: async () => ({
              Component: (await import('@/pages/admin/ai/AdminAiPage')).default,
            }),
          },
          {
            path: 'members',
            lazy: async () => ({
              Component: (
                await import('@/pages/admin/members/AdminMembersPage')
              ).default,
            }),
          },
          {
            path: 'audit',
            lazy: async () => ({
              Component: (await import('@/pages/admin/audit/AdminAuditPage'))
                .default,
            }),
          },
        ],
      },
    ],
  },
  { path: '/home', element: <LegacyHomeRedirect /> },
  { path: '/search', element: <Navigate to="/stocks" replace /> },
  { path: '/detail/:id', element: <LegacyDetailRedirect /> },
  { path: '*', element: <Navigate to="/" replace /> },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
