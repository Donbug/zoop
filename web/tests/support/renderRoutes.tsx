import { render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  createMemoryRouter,
  RouterProvider,
  type RouteObject,
} from 'react-router-dom';

/** 정한 경로만 그리는 메모리 라우터. 그 밖의 경로로 이동하면 빈 화면이 된다. */
export function renderRoutes(routes: RouteObject[], initialEntry: string) {
  const router = createMemoryRouter([...routes, { path: '*', element: null }], {
    initialEntries: [initialEntry],
  });
  const user = userEvent.setup();
  render(<RouterProvider router={router} />);
  const location = () =>
    `${router.state.location.pathname}${router.state.location.search}`;
  return { router, user, location };
}
