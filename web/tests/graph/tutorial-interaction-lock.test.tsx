import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { useTutorialInteractionLock } from '@/components/graph/tutorial/useTutorialInteractionLock';

function Surface({
  step,
  action,
}: {
  step: number;
  action: (value: string) => void;
}) {
  useTutorialInteractionLock(step, false);
  return (
    <>
      <button onClick={() => action('close')}>상세 닫기</button>
      <a
        href="/other"
        onClick={(event) => {
          event.preventDefault();
          action('navigate');
        }}
      >
        다른 메뉴
      </a>
      <button data-tutorial-action="node" onClick={() => action('node')}>
        목표 노드
      </button>
      <button data-tutorial-action="move" onClick={() => action('move')}>
        지도 이동
      </button>
      <button data-tutorial-action="zoom" onClick={() => action('zoom')}>
        확대
      </button>
      <button data-tutorial-action="skip" onClick={() => action('skip')}>
        건너뛰기
      </button>
    </>
  );
}
describe('D-GRP-T2/T3 · tutorial input boundary', () => {
  it('2단계에서 이동과 확대를 계속 허용하고 3단계에서는 다시 차단한다', async () => {
    const action = vi.fn();
    const view = render(<Surface step={2} action={action} />);
    await userEvent.click(screen.getByRole('button', { name: '지도 이동' }));
    await userEvent.click(screen.getByRole('button', { name: '확대' }));
    expect(action.mock.calls.map(([value]) => value)).toEqual(['move', 'zoom']);
    view.rerender(<Surface step={3} action={action} />);
    expect(
      (screen.getByRole('button', { name: '지도 이동' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(
      (screen.getByRole('button', { name: '확대' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });
  it('목표·건너뛰기만 활성화하고 Escape·다른 메뉴를 막으며 5단계에서는 원래 동작을 복원한다', async () => {
    const action = vi.fn();
    const escape = vi.fn();
    const view = render(<Surface step={2} action={action} />);
    window.addEventListener('keydown', escape);
    try {
      expect(
        (screen.getByRole('button', { name: '상세 닫기' }) as HTMLButtonElement)
          .disabled,
      ).toBe(true);
      await userEvent.click(screen.getByRole('link', { name: '다른 메뉴' }));
      fireEvent.keyDown(document.body, { key: 'Escape' });
      expect(escape).not.toHaveBeenCalled();
      expect(action).not.toHaveBeenCalled();
      await userEvent.click(screen.getByRole('button', { name: '목표 노드' }));
      await userEvent.click(screen.getByRole('button', { name: '건너뛰기' }));
      expect(action.mock.calls.map(([value]) => value)).toEqual([
        'node',
        'skip',
      ]);
      view.rerender(<Surface step={5} action={action} />);
      await userEvent.click(screen.getByRole('button', { name: '상세 닫기' }));
      await userEvent.click(screen.getByRole('link', { name: '다른 메뉴' }));
      expect(action).toHaveBeenCalledWith('close');
      expect(action).toHaveBeenCalledWith('navigate');
      expect(screen.getByRole('link').getAttribute('aria-disabled')).toBeNull();
    } finally {
      window.removeEventListener('keydown', escape);
    }
  });
});
