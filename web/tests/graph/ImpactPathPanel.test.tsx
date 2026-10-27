import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ComponentProps } from 'react';
import { describe, expect, it, vi } from 'vitest';
import ImpactPathPanel from '@/components/graph/ImpactPathPanel';
import { createMockGraph } from '@/mocks/graph/response';
import type { Impact } from '@/types/company/detail';

const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
const relation = graph.edges.find((edge) => edge.relationType === 'INVOLVES')!;
const companyId = relation.target;
const issueId = relation.source;
const metadata: Impact['metadata'] = {
  source: graph.metadata.source,
  asOf: graph.metadata.asOf,
  graphVersion: graph.metadata.graphVersion,
  partial: false,
  failures: [],
};
const connectedImpact: Impact = {
  companyId,
  issueId,
  steps: [
    {
      id: companyId,
      kind: 'company',
      reason: relation.role ?? relation.summary,
      evidenceIds: relation.evidenceIds,
    },
    {
      id: issueId,
      kind: 'issue',
      reason: '기사에 기업과 사건의 연결이 기록되어 있습니다.',
      evidenceIds: relation.evidenceIds,
    },
  ],
  metadata,
};

function renderPanel(
  overrides: Partial<ComponentProps<typeof ImpactPathPanel>> = {},
) {
  const callbacks = {
    onRetry: vi.fn(),
    onClose: vi.fn(),
    onViewIssue: vi.fn(),
    onEvidence: vi.fn(),
    onAskAi: vi.fn(),
  };
  const result = render(
    <ImpactPathPanel
      companyId={companyId}
      issueId={issueId}
      graph={graph}
      impact={null}
      loading={false}
      error={null}
      {...callbacks}
      {...overrides}
    />,
  );
  return { ...result, callbacks };
}

describe('D-GRP-06 · impact path states', () => {
  it('shows the loading state instead of claiming a connection result', () => {
    renderPanel({ loading: true });

    const panel = within(
      screen.getByRole('complementary', { name: /영향 경로/ }),
    );
    expect(panel.getByText(/연결 확인 중/)).toBeTruthy();
    expect(panel.getByRole('status').textContent).toContain(
      '영향 경로를 불러오는 중입니다.',
    );
  });

  it('distinguishes a successful empty path from a direct confirmed connection', () => {
    renderPanel({
      impact: { ...connectedImpact, steps: [] },
    });

    const panel = within(
      screen.getByRole('complementary', { name: /영향 경로/ }),
    );
    expect(panel.getByText(/직접 연결 미확인/)).toBeTruthy();
    expect(panel.getByText('확인된 영향 경로가 없습니다.')).toBeTruthy();
    expect(panel.queryByRole('alert')).toBeNull();
  });

  it('shows the direct connection and partial rights warning while keeping unavailable evidence disabled', () => {
    renderPanel({
      impact: {
        ...connectedImpact,
        steps: connectedImpact.steps.map((step) => ({
          ...step,
          evidenceIds: [],
        })),
        metadata: {
          ...metadata,
          partial: true,
          failures: [
            {
              section: 'evidence',
              code: 'EVIDENCE_UNAVAILABLE',
              message: '현재 공개 권한을 확인할 수 있는 근거만 표시합니다.',
            },
          ],
        },
      },
    });

    const panel = within(
      screen.getByRole('complementary', { name: /영향 경로/ }),
    );
    expect(panel.getByText(/직접 연결 확인/)).toBeTruthy();
    expect(panel.getByRole('status').textContent).toContain(
      '현재 공개 권한을 확인할 수 있는 근거만 표시합니다.',
    );
    expect(
      panel
        .getAllByRole('button', { name: '근거 0건 보기' })
        .every((button) => (button as HTMLButtonElement).disabled),
    ).toBe(true);
  });

  it('shows a retryable read error without claiming the path is empty', async () => {
    const user = userEvent.setup();
    const { callbacks } = renderPanel({ error: '일시적인 조회 오류입니다.' });

    const panel = within(
      screen.getByRole('complementary', { name: /영향 경로/ }),
    );
    expect(panel.getByText(/연결 확인 불가/)).toBeTruthy();
    expect(panel.getByRole('alert').textContent).toContain(
      '일시적인 조회 오류입니다.',
    );
    await user.click(panel.getByRole('button', { name: '다시 시도' }));
    expect(callbacks.onRetry).toHaveBeenCalledOnce();
  });
});
