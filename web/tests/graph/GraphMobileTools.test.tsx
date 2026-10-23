import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import GraphMobileTools from '@/components/graph/GraphMobileTools';

test('M-GRP-01 mobile menu switches arrangement, respects focus lock and closes with Escape/outside pointer', async () => {
  vi.stubGlobal('matchMedia', () => ({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  const change = vi.fn();
  const view = render(
    <GraphMobileTools flow={false} onFlowChange={change} focusActive={false} />,
  );
  const summary = screen.getByText('···').closest('summary')!;
  await userEvent.click(summary);
  expect(summary.closest('details')!.open).toBe(true);
  await userEvent.click(
    screen.getByRole('button', { name: '흐름 순으로 정렬' }),
  );
  expect(change).toHaveBeenCalledWith(true);
  expect(summary.closest('details')!.open).toBe(false);
  await userEvent.click(summary);
  fireEvent.keyDown(summary, { key: 'Escape' });
  expect(summary.closest('details')!.open).toBe(false);
  expect(document.activeElement).toBe(summary);
  await userEvent.click(summary);
  fireEvent.pointerDown(document.body);
  expect(summary.closest('details')!.open).toBe(false);
  view.rerender(
    <GraphMobileTools flow={false} onFlowChange={change} focusActive />,
  );
  await userEvent.click(summary);
  expect(
    (
      screen.getByRole('button', {
        name: '흐름 순으로 정렬',
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});
