import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';
import ServiceHeader from '@/components/common/ServiceHeader';
import { useAiChatStore } from '@/stores/useAiChatStore';

// D-GRP-01 shared header · D-AI-01: the AI drawer lives on the map.

function at(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/"
          element={
            <>
              <ServiceHeader />
              <p>지도 화면</p>
            </>
          }
        />
        <Route path="/stocks" element={<ServiceHeader />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => useAiChatStore.getState().reset());

describe('D-GRP-01 · AI 채팅 header button', () => {
  it('goes to the map and opens the drawer from another screen', async () => {
    at('/stocks');
    await userEvent
      .setup()
      .click(screen.getByRole('button', { name: 'AI 채팅' }));
    expect(screen.getByText('지도 화면')).toBeTruthy();
    expect(useAiChatStore.getState().isOpen).toBe(true);
  });

  it('opens the drawer in place on the map', async () => {
    at('/');
    await userEvent
      .setup()
      .click(screen.getByRole('button', { name: 'AI 채팅' }));
    expect(screen.getByText('지도 화면')).toBeTruthy();
    expect(useAiChatStore.getState().isOpen).toBe(true);
  });
});
