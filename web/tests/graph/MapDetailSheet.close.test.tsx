import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import MapDetailSheet from '@/components/graph/MapDetailSheet';
import CompanyDetailPanel from '@/components/graph/CompanyDetailPanel';
import EventDetailPanel from '@/components/graph/EventDetailPanel';
import RelationDetailPanel from '@/components/graph/RelationDetailPanel';
import CompanyPathPanel from '@/components/graph/CompanyPathPanel';
import ImpactPathPanel from '@/components/graph/ImpactPathPanel';
import IsolatedIssuesPanel from '@/components/graph/IsolatedIssuesPanel';
import BriefingRoundIssuePanel from '@/components/graph/BriefingRoundIssuePanel';
import GraphTutorial from '@/components/graph/GraphTutorial';
import { useCompanyData } from '@/hooks/useCompanyData';
import { useEventData } from '@/hooks/useEventData';
import { useRelationData } from '@/hooks/useRelationData';
import { useAsyncData } from '@/hooks/useAsyncData';
import { createMockGraph } from '@/mocks/graph/response';
import type { Impact } from '@/types/company/detail';

vi.mock('@/hooks/useCompanyData');
vi.mock('@/hooks/useEventData');
vi.mock('@/hooks/useRelationData');
vi.mock('@/hooks/useAsyncData');

const graph = createMockGraph({ mode: 'all', personalFilter: 'all' });
const company = graph.nodes.find((node) => node.kind === 'company')!;
const issue = graph.nodes.find((node) => node.kind === 'issue')!;
const context = {
  graphVersion: graph.metadata.graphVersion ?? undefined,
  asOf: graph.metadata.asOf,
};

// D-GRP-06 label terminology follows the OpenAPI user decision.
it.each([
  ['mixed', '혼재'],
  ['undetermined', '판단 보류'],
] as const)('D-GRP-06 renders %s as %s', (label, expected) => {
  vi.mocked(useEventData).mockReturnValue({
    key: 'fixture',
    loading: false,
    error: null,
    data: null,
  });
  const impact: Impact = {
    companyId: company.id,
    issueId: issue.id,
    pathStatus: 'available',
    pathType: 'direct',
    edgeId: graph.edges[0].id,
    steps: [
      { id: issue.id, kind: 'issue', reason: '확인', evidenceIds: ['ev-a'] },
      {
        id: company.id,
        kind: 'company',
        reason: '확인',
        evidenceIds: ['ev-a'],
      },
    ],
    businessPath: null,
    impact: {
      status: 'available',
      reason: null,
      results: [
        {
          impactId: label,
          status: 'verified',
          label,
          evidenceIds: ['ev-a'],
          effects: {
            positive: [],
            negative: [],
            neutral: [],
            uncertain: ['ev-a'],
          },
        },
      ],
    },
    metadata: graph.metadata,
  };
  render(
    <MemoryRouter>
      <ImpactPathPanel
        companyId={company.id}
        issueId={issue.id}
        context={context}
        graph={graph}
        impact={impact}
        loading={false}
        error={null}
        onClose={vi.fn()}
        onRetry={vi.fn()}
        onViewIssue={vi.fn()}
        onEvidence={vi.fn()}
        onAskAi={vi.fn()}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText(`영향 판정 · ${expected}`)).toBeTruthy();
});

// M-GRP-01: render real panel headers in the mobile portal, including failure/loading.
it.each(['loading', 'error'] as const)(
  'M-GRP-01 every panel keeps a visible working close button while %s',
  async (status) => {
    vi.stubGlobal('matchMedia', () => ({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    const loading = status === 'loading';
    const error = loading ? null : 'offline';
    vi.mocked(useCompanyData).mockReturnValue({
      loading,
      errors: loading ? {} : { company: 'offline' },
      data: null,
    });
    vi.mocked(useEventData).mockReturnValue({
      key: 'fixture',
      loading,
      error,
      data: null,
    });
    vi.mocked(useRelationData).mockReturnValue({
      key: 'fixture',
      loading,
      error,
      data: null,
      retryable: true,
    });
    vi.mocked(useAsyncData).mockReturnValue(
      loading
        ? {
            status: 'loading',
            data: undefined,
            error: undefined,
            reload: vi.fn(),
            setData: vi.fn(),
          }
        : {
            status: 'error',
            data: undefined,
            error: new Error('offline'),
            reload: vi.fn(),
            setData: vi.fn(),
          },
    );
    const close = vi.fn();
    const panels = [
      {
        id: 'D-GRP-03',
        content: (
          <CompanyDetailPanel
            companyId={company.id}
            fallback={company}
            relatedCompanies={[]}
            token={null}
            onClose={close}
            onSelectIssue={vi.fn()}
            onFocus={vi.fn()}
            onConnections={vi.fn()}
            onAskAi={vi.fn()}
          />
        ),
      },
      {
        id: 'D-GRP-02',
        content: (
          <EventDetailPanel
            id={issue.id}
            context={context}
            geography={null}
            onClose={close}
            onAction={vi.fn()}
          />
        ),
      },
      {
        id: 'D-GRP-04',
        content: (
          <RelationDetailPanel
            id={graph.edges[0].id}
            context={context}
            onClose={close}
            onSelectNode={vi.fn()}
            onAction={vi.fn()}
          />
        ),
      },
      {
        id: 'D-GRP-07',
        content: (
          <CompanyPathPanel
            graph={null}
            from={company.id}
            to={null}
            loading={loading}
            error={error}
            onClose={close}
            onPick={vi.fn()}
            onRetry={vi.fn()}
            onEvidence={vi.fn()}
          />
        ),
      },
      {
        id: 'D-GRP-06',
        content: (
          <ImpactPathPanel
            companyId={company.id}
            issueId={issue.id}
            context={context}
            graph={graph}
            impact={null}
            loading={loading}
            error={error}
            onClose={close}
            onRetry={vi.fn()}
            onViewIssue={vi.fn()}
            onEvidence={vi.fn()}
            onAskAi={vi.fn()}
          />
        ),
      },
      {
        id: 'D-GRP-01',
        content: (
          <IsolatedIssuesPanel issues={[]} onClose={close} onSelect={vi.fn()} />
        ),
      },
      {
        id: 'D-BRF-04',
        content: (
          <BriefingRoundIssuePanel
            roundId="round"
            eventId={issue.id}
            graphVersion={context.graphVersion ?? null}
            onClose={close}
          />
        ),
      },
    ];
    for (const panel of panels) {
      close.mockClear();
      const view = render(
        <MemoryRouter>
          <MapDetailSheet
            open
            onClose={close}
            tutorial={
              <GraphTutorial
                step={5}
                practice
                compact
                onStepChange={vi.fn()}
                onFinish={vi.fn()}
                onSkip={vi.fn()}
              />
            }
          >
            {panel.content}
          </MapDetailSheet>
        </MemoryRouter>,
      );
      const dialog = screen.getByRole('dialog', { name: '지도 상세' });
      const buttons = within(dialog).getAllByRole('button', { name: /닫기/ });
      expect(buttons.length, panel.id).toBe(1);
      expect(buttons[0].textContent).toBe('×');
      expect((buttons[0] as HTMLButtonElement).disabled, panel.id).toBe(false);
      await userEvent.click(buttons[0]);
      expect(close, panel.id).toHaveBeenCalledOnce();
      view.unmount();
    }
  },
);
