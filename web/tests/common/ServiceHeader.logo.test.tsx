import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it } from 'vitest';
import ServiceHeader from '@/components/common/ServiceHeader';
import SlimHeader from '@/components/common/SlimHeader';

// D-GRP-01 · D-AUT-01: 로고는 한글 없이 대문자 ZOOP 한 단어로 보인다(2026-10-24 디자인 리뷰).
it('서비스 헤더와 간단 헤더의 로고는 ZOOP 한 단어다', () => {
  render(
    <MemoryRouter>
      <ServiceHeader />
      <SlimHeader />
    </MemoryRouter>,
  );
  const logos = screen.getAllByRole('link', { name: 'ZOOP' });
  expect(logos).toHaveLength(2);
  for (const logo of logos) expect(logo.textContent).toBe('ZOOP');
  expect(screen.queryByText('줍')).toBeNull();
});
