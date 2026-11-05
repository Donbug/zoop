import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import BriefingReadingSection from '@/components/briefing/BriefingReadingSection';
import { DISCLOSURE, SECTION } from '@/components/briefing/briefingStyles';

it('D-BRF-01/02 flat reading sections retain native disclosure controls and visible text', async () => {
  const user = userEvent.setup();
  render(
    <BriefingReadingSection compact title="합성 근거 문서">
      <p>합성 검증 원문</p>
    </BriefingReadingSection>,
  );
  const summary = screen.getByText('합성 근거 문서');
  const details = summary.closest('details')!;
  expect(details.open).toBe(false);
  expect(summary.classList.contains('min-h-11')).toBe(true);
  expect(summary.tagName).toBe('SUMMARY');
  await user.click(summary);
  expect(details.open).toBe(true);
  expect(screen.getByText('합성 검증 원문')).toBeTruthy();
  await user.click(summary);
  expect(details.open).toBe(false);
});

it('D-BRF-01/02 full reading keeps the original content without a disclosure layer', () => {
  const { container } = render(
    <BriefingReadingSection compact={false} title="합성 근거 문서">
      <h4>합성 원문 제목</h4>
      <p>합성 검증 원문</p>
    </BriefingReadingSection>,
  );
  expect(container.querySelector('details')).toBeNull();
  expect(screen.getByRole('heading', { level: 4 }).textContent).toBe(
    '합성 원문 제목',
  );
  expect(screen.getByText('합성 검증 원문')).toBeTruthy();
});

it('D-BRF-01/02 sections and disclosures draw only a bottom divider, so adjacent blocks never double it', () => {
  for (const block of [SECTION, DISCLOSURE]) {
    const classes = block.split(' ');
    expect(classes).toContain('border-b');
    expect(classes).toContain('last:border-b-0');
    expect(classes.some((c) => /^border-t(-|$)/.test(c))).toBe(false);
  }
});
