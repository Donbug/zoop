import { fireEvent, render } from '@testing-library/react';
import { expect, it } from 'vitest';
import CompanyLogo from '@/components/common/CompanyLogo';

it('shows the logo when the company has one', () => {
  const { container } = render(
    <CompanyLogo
      name="삼성전자"
      logoUrl="/graph-assets/samsung.svg"
      className="size-8"
    />,
  );
  expect(container.querySelector('img')?.getAttribute('src')).toBe(
    '/graph-assets/samsung.svg',
  );
  expect(container.textContent).toBe('');
});

it('falls back to the first letter without a logo or when it fails to load', () => {
  const { container, rerender } = render(
    <CompanyLogo name="삼성전자" logoUrl={null} className="size-8" />,
  );
  expect(container.querySelector('img')).toBeNull();
  expect(container.textContent).toBe('삼');

  rerender(
    <CompanyLogo
      name="SK하이닉스"
      logoUrl="/graph-assets/missing.svg"
      className="size-8"
    />,
  );
  fireEvent.error(container.querySelector('img')!);
  expect(container.querySelector('img')).toBeNull();
  expect(container.textContent).toBe('S');
});
