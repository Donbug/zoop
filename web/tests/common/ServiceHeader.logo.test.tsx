import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it } from 'vitest';
import ServiceHeader from '@/components/common/ServiceHeader';
import SlimHeader from '@/components/common/SlimHeader';

// D-GRP-01 · D-AUT-01: 로고는 한글 없이 ZOOP 워드마크 한 개로 보인다(2026-10-24 디자인 리뷰, 2026-11-05 워드마크 적용).
it('서비스 헤더와 간단 헤더의 로고는 ZOOP 한 단어다', () => {
  render(
    <MemoryRouter>
      <ServiceHeader />
      <SlimHeader />
    </MemoryRouter>,
  );
  const logos = screen.getAllByRole('link', { name: 'ZOOP' });
  expect(logos).toHaveLength(2);
  for (const logo of logos) {
    expect(logo.textContent).toBe('');
    expect(within(logo).getByRole('img', { name: 'ZOOP' })).toBeTruthy();
  }
  expect(screen.getByRole('button', { name: 'AI 채팅' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'AI 기능' })).toBeNull();
  expect(screen.queryByText('줍')).toBeNull();
});
