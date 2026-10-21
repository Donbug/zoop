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
  expect(
    (container.firstElementChild as HTMLElement).style.backgroundColor,
  ).toBe('rgb(255, 255, 255)');
});

it('uses each logo background without leaking it into the text fallback', () => {
  const { container, rerender } = render(
    <CompanyLogo
      name="마이크론"
      logoUrl="/graph-assets/micron.svg"
      className="size-8 bg-red-500"
    />,
  );
  expect(
    (container.firstElementChild as HTMLElement).style.backgroundColor,
  ).toBe('rgb(0, 0, 0)');

  rerender(<CompanyLogo name="새 기업" logoUrl={null} className="size-8" />);
  expect(
    (container.firstElementChild as HTMLElement).style.backgroundColor,
  ).toBe('');
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
