import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import EventDetailPanel from '@/components/graph/EventDetailPanel';
import RelationDetailPanel from '@/components/graph/RelationDetailPanel';
import CompanyDetailPanel from '@/components/graph/CompanyDetailPanel';
import EvidenceDrawer from '@/components/evidence/EvidenceDrawer';
import { createMockEvent } from '@/mocks/events/fixture';
import { createMockEvidence } from '@/mocks/evidence/fixture';
import { createMockRelation } from '@/mocks/relations/fixture';
import { mockCompany, mockDocuments } from '@/mocks/company/fixture';
import { createMockGraph } from '@/mocks/graph/response';
import { useGraphUiStore } from '@/stores/useGraphUiStore';
import type { EvidenceResponse } from '@/types/evidence';
import {
  apiError,
  createFakeServer,
  deferred,
  json,
} from '../support/fakeServer';

// All HTTP responses here are synthetic. round forces the real /api/v1 consumers
// even when the required full-suite command uses VITE_GRAPH_DATA_SOURCE=mock.
const baseEvent = createMockEvent('mock-issue-1');
const context = {
  round: 'test-round',
  graphVersion: baseEvent.metadata.graphVersion!,
  asOf: baseEvent.metadata.asOf,
};
const eventProps = {
  id: baseEvent.id,
  context,
  geography: null,
  onClose: vi.fn(),
  onAction: vi.fn(),
};

function evidenceWithAnalysis(): EvidenceResponse {
  const evidence = createMockEvidence('mock-evidence-1');
  const provenance = {
    sourceKind: 'actual' as const,
    executionMode: 'live' as const,
    recordingKind: 'provider' as const,
  };
  return {
    ...evidence,
    analysisProvenance: provenance,
    analysisStatus: {
      summary: { status: 'available', reason: null },
      sentiment: { status: 'not_requested', reason: null },
    },
    documentSummary: {
      schemaVersion: 'zoop-ai-s1-1',
      artifactId: 'test-artifact',
      documentId: evidence.articleId,
      documentVersion: evidence.articleVersion,
      resultVersion: evidence.resultVersion!,
      text: 'fallback summary must not duplicate claims',
      claims: [
        {
          claimId: 'fact',
          text: '합성 시험의 문서 내용',
          assertionKind: 'fact',
          evidenceIds: [evidence.id],
        },
        {
          claimId: 'interpretation',
          text: '합성 시험의 해석',
          assertionKind: 'interpretation',
          evidenceIds: [evidence.id],
        },
        {
          claimId: 'limitation',
          text: '합성 시험의 한계',
          assertionKind: 'limitation',
          evidenceIds: [],
        },
      ],
      citations: [
        {
          evidenceId: evidence.id,
          documentId: evidence.articleId,
          documentVersion: evidence.articleVersion,
          textArtifactId: 'test-text',
          offsetUnit: 'unicode_code_point',
          start: evidence.start,
          end: evidence.end,
          quote: evidence.quote,
          inputKind: 'summary',
          rawLocatorIds: [],
        },
      ],
      limitations: [],
      producedAt: context.asOf,
      provenance,
    },
  };
}

function renderEvidence(evidence: EvidenceResponse) {
  const server = createFakeServer();
  server.on('GET', '/api/v1/evidence/:id', () => json(evidence));
  useGraphUiStore.getState().openEvidence({
    kind: 'issue',
    id: baseEvent.id,
    label: baseEvent.title,
    evidenceIds: [evidence.id],
    mapContext: { ...context, url: '/' },
  });
  render(<EvidenceDrawer />);
  return server;
}

beforeEach(() => useGraphUiStore.getState().reset());

describe('D-GRP-02 · prototype event panel completion via /api/v1', () => {
  it('27/28/29: keeps ordered follows, time precision, pinned context and company destinations', async () => {
    const server = createFakeServer();
    const event = structuredClone(baseEvent);
    event.follows = {
      previous: [
        {
          id: 'previous',
          title: '앞선 합성 사건',
          eventTime: '2025',
          timePrecision: 'year',
        },
      ],
      next: [
        {
          id: 'next',
          title: '이어진 합성 사건',
          eventTime: null,
          timePrecision: 'unknown',
        },
      ],
    };
    event.sourceSupport.independentSourceCount = 2;
    server.on('GET', '/api/v1/events/:id', () => json(event));
    render(<EventDetailPanel {...eventProps} />);
    await screen.findByText('독립 출처 2곳');
    const list = screen.getByRole('region', { name: '앞뒤로 이어진 사건' });
    expect(
      within(list)
        .getAllByRole('listitem')
        .map((item) => item.firstChild?.textContent),
    ).toEqual(['앞선 합성 사건', '이어진 합성 사건']);
    expect(
      within(list).getByText('앞선 사건 · 2025년 · 연도 단위'),
    ).toBeTruthy();
    expect(within(list).getByText('이어진 사건 · 발생 시각 미상')).toBeTruthy();
    expect(within(list).queryByRole('link')).toBeNull();
    for (const [key, value] of Object.entries(context))
      expect(server.requests[0].query.get(key)).toBe(value);
    expect(
      screen
        .getByRole('link', { name: event.companies[0].name })
        .getAttribute('href'),
    ).toBe(`/companies/${encodeURIComponent(event.companies[0].id)}`);
    expect(server.requests[0].query.get('graphVersion')).toBe(
      context.graphVersion,
    );
  });

  it.each([null, 0])(
    '28: does not invent an independent-source count when value is %s',
    async (count) => {
      const server = createFakeServer();
      const event = structuredClone(baseEvent);
      event.sourceSupport.independentSourceCount = count;
      server.on('GET', '/api/v1/events/:id', () => json(event));
      render(<EventDetailPanel {...eventProps} />);
      await screen.findByRole('heading', { name: baseEvent.title });
      expect(Boolean(screen.queryByText('독립 출처 0곳'))).toBe(count === 0);
    },
  );

  it('26: approval source stays off the user panel (FE handoff 3-1)', async () => {
    const server = createFakeServer();
    const event = structuredClone(baseEvent);
    event.approval = {
      source: 'admin-review',
      label: '합성 승인 표시',
      scope: 'test',
    };
    server.on('GET', '/api/v1/events/:id', () => json(event));
    render(<EventDetailPanel {...eventProps} />);
    await screen.findByRole('heading', { name: baseEvent.title });
    expect(screen.queryByText('합성 승인 표시')).toBeNull();
    expect(
      screen.queryByLabelText('관리자가 원문 근거를 직접 확인하고 게시했어요'),
    ).toBeNull();
  });

  it('26/27/28: suppresses missing and failed sections, retries without stale content', async () => {
    const server = createFakeServer();
    const event = structuredClone(baseEvent);
    event.approval = null;
    event.metadata.partial = true;
    event.metadata.failures = ['follows', 'sourceSupport'].map((section) => ({
      section,
      code: 'SOURCE_UNAVAILABLE',
      message: `${section} 합성 조회 실패`,
      retryable: true,
      asOf: context.asOf,
    }));
    event.sourceSupport.independentSourceCount = 5;
    server.on('GET', '/api/v1/events/:id', () => json(event));
    render(<EventDetailPanel {...eventProps} />);
    await screen.findByText('일부 정보를 불러오지 못했습니다.');
    expect(screen.queryByText('독립 출처 5곳')).toBeNull();
    expect(
      screen.queryByRole('region', { name: '앞뒤로 이어진 사건' }),
    ).toBeNull();
    expect(
      screen.queryByText('관리자가 원문 근거를 직접 확인하고 게시했어요'),
    ).toBeNull();
    const pending = deferred<Response>();
    server.on('GET', '/api/v1/events/:id', () => pending.promise);
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    await screen.findByText('사건 정보를 불러오는 중입니다.');
    expect(screen.queryByText('follows 합성 조회 실패')).toBeNull();
    await act(async () => pending.resolve(json(baseEvent)));
    await screen.findByRole('heading', { name: baseEvent.title });
  });
});

describe('D-GRP-04 · prototype relation fields', () => {
  it('30: shows direct assertion, citation verification, role and safe basis links', async () => {
    const server = createFakeServer();
    const relation = createMockRelation('mock-follows-1');
    relation.roles = ['발표자'];
    relation.assertionStatus = 'forecast';
    relation.basis = [
      {
        edgeId: 'safe',
        validity: 'unknown',
        relationType: 'FOLLOWS',
        sourceUrl: 'https://example.com/test',
        verifiedAt: context.asOf,
        validFrom: null,
        validUntil: null,
        countries: [],
      },
      {
        edgeId: 'unsafe',
        validity: 'unknown',
        relationType: 'FOLLOWS',
        sourceUrl: 'javascript:alert(1)',
        verifiedAt: null,
        validFrom: null,
        validUntil: null,
        countries: [],
      },
    ];
    server.on('GET', '/api/v1/graph/edges/:id', () => json(relation));
    render(
      <RelationDetailPanel
        id={relation.id}
        context={context}
        onClose={vi.fn()}
        onSelectNode={vi.fn()}
        onAction={vi.fn()}
      />,
    );
    await screen.findByText('전망');
    expect(screen.getByText('발표자')).toBeTruthy();
    expect(screen.getByText('인용 검증')).toBeTruthy();
    const link = screen.getByRole('link', {
      name: '기준 문서 열기 (새 창에서 열림)',
    });
    expect(link.getAttribute('href')).toBe('https://example.com/test');
    expect(link.getAttribute('rel')).toContain('noopener');
    expect(screen.getByText('기준 문서 링크 없음')).toBeTruthy();
  });

  it('30: does not fabricate assertion/verification on derived relations or empty basis', async () => {
    const server = createFakeServer();
    const relation = createMockRelation('mock-follows-1');
    relation.derived = true;
    relation.basis = [];
    server.on('GET', '/api/v1/graph/edges/:id', () => json(relation));
    render(
      <RelationDetailPanel
        id={relation.id}
        context={context}
        onClose={vi.fn()}
        onSelectNode={vi.fn()}
        onAction={vi.fn()}
      />,
    );
    await screen.findByRole('heading', {
      name: `${relation.source.label} – ${relation.target.label}`,
    });
    expect(screen.queryByText('보도 표현')).toBeNull();
    expect(screen.queryByText('인용 검증')).toBeNull();
    expect(screen.queryByRole('region', { name: '관계 기준 문서' })).toBeNull();
  });
});

describe('D-GRP-05 · saved document analysis', () => {
  it('31: ports claims, interpretation, limitation and summary-source notice without duplicating text', async () => {
    const server = renderEvidence(evidenceWithAnalysis());
    await screen.findByText('합성 시험의 문서 내용');
    expect(screen.getByText('해석 ·')).toBeTruthy();
    expect(screen.getByText('한계 ·')).toBeTruthy();
    expect(screen.getByText('원문을 대체하지 않아요.')).toBeTruthy();
    expect(
      screen.getByText(
        '제공된 요약에서 인용했어요. 기사 전문 인용은 아니에요.',
      ),
    ).toBeTruthy();
    expect(
      screen.queryByText('fallback summary must not duplicate claims'),
    ).toBeNull();
    expect(server.requests.every((request) => request.method === 'GET')).toBe(
      true,
    );
  });

  it.each(['document', 'result', 'status', 'article', 'authored'] as const)(
    '31: hides ineligible analysis (%s)',
    async (kind) => {
      const evidence = evidenceWithAnalysis();
      if (kind === 'document')
        evidence.documentSummary!.documentVersion = 'other-version';
      if (kind === 'result') evidence.resultVersion = 'other-result';
      if (kind === 'status')
        evidence.analysisStatus!.summary.status = 'withheld';
      if (kind === 'article') evidence.article = null;
      if (kind === 'authored') {
        evidence.documentSummary!.provenance = {
          sourceKind: 'actual',
          executionMode: 'replay',
          recordingKind: 'authored-test',
        };
      }
      renderEvidence(evidence);
      if (evidence.article) await screen.findByText(evidence.article.title!);
      else await screen.findByText('근거 문서를 제공할 수 없습니다.');
      expect(screen.queryByText('합성 시험의 문서 내용')).toBeNull();
      if (kind === 'status')
        await screen.findByText('문서 요약은 지금 제공하지 않아요.');
    },
  );

  it('31: shows a validated stored summary when the real API omits analysisStatus (null)', async () => {
    // Real getEvidence (EvidenceResponse/EvidenceService) always sends analysisStatus: null,
    // even when the latest stored summary is validated.
    const evidence = evidenceWithAnalysis();
    evidence.analysisStatus = null;
    renderEvidence(evidence);
    await screen.findByText('합성 시험의 문서 내용');
    expect(screen.getByText('해석 ·')).toBeTruthy();
  });

  it.each(['document', 'result'] as const)(
    '31: a null-status summary still needs matching document and result versions (%s)',
    async (kind) => {
      const evidence = evidenceWithAnalysis();
      evidence.analysisStatus = null;
      if (kind === 'document')
        evidence.documentSummary!.documentVersion = 'other-version';
      if (kind === 'result') evidence.resultVersion = 'other-result';
      renderEvidence(evidence);
      await screen.findByText(evidence.article!.title!);
      expect(screen.queryByText('합성 시험의 문서 내용')).toBeNull();
    },
  );

  it('31: an explicit non-available summary status keeps the stored summary hidden', async () => {
    const evidence = evidenceWithAnalysis();
    evidence.analysisStatus!.summary.status = 'not_requested';
    renderEvidence(evidence);
    await screen.findByText(evidence.article!.title!);
    expect(screen.queryByText('합성 시험의 문서 내용')).toBeNull();
  });

  it('31: shows failure states, not saved hidden result bodies', async () => {
    const evidence = evidenceWithAnalysis();
    evidence.analysisStatus = {
      summary: { status: 'failed', reason: null },
      sentiment: { status: 'withheld', reason: null },
    };
    renderEvidence(evidence);
    await screen.findByText('문서 요약을 만들지 못했어요.');
    expect(
      screen.getByText('기업별 판정은 지금 제공하지 않아요.'),
    ).toBeTruthy();
    expect(screen.queryByText('합성 시험의 문서 내용')).toBeNull();
  });
});

describe('D-GRP-03 · document judgements retain company/event context', () => {
  it('25: uses only matching document judgements and preserves retry recovery', async () => {
    const server = createFakeServer();
    const company = mockCompany('KRX:005930');
    const document = mockDocuments(company.id).items[0];
    const sentiment = {
      companyId: company.id,
      label: 'mixed',
      rationale: '합성 문서 판정 사유',
      quotes: ['합성 인용'],
      judgedAt: context.asOf,
      model: 'test-model',
      promptVersion: 'test-prompt',
    };
    const documents = [
      {
        ...document,
        id: 'matching',
        title: '일치 문서',
        events: [{ eventId: company.directIssues[0].issueId }],
        sentiment,
      },
      {
        ...document,
        id: 'other-company',
        title: '다른 기업 문서',
        events: [{ eventId: company.directIssues[0].issueId }],
        sentiment: { ...sentiment, companyId: 'other-company' },
      },
      {
        ...document,
        id: 'other-event',
        title: '다른 사건 문서',
        events: [{ eventId: 'other-event' }],
        sentiment,
      },
    ];
    server.on('GET', '/api/v1/companies/:id', () =>
      json({ ...company, metadata: baseEvent.metadata }),
    );
    server.on('GET', '/api/v1/companies/:id/documents', () =>
      apiError(503, 'SOURCE_UNAVAILABLE', '합성 문서 조회 실패'),
    );
    const fallback = createMockGraph({
      mode: 'all',
      personalFilter: 'all',
    }).nodes.find((node) => node.id === company.id)!;
    render(
      <MemoryRouter>
        <CompanyDetailPanel
          companyId={company.id}
          context={context}
          fallback={fallback}
          relatedCompanies={[]}
          token={null}
          onClose={vi.fn()}
          onSelectIssue={vi.fn()}
          onFocus={vi.fn()}
          onAskAi={vi.fn()}
        />
      </MemoryRouter>,
    );
    await screen.findByRole('alert');
    server.on('GET', '/api/v1/companies/:id/documents', () =>
      json({
        items: documents,
        metadata: baseEvent.metadata,
        nextCursor: null,
      }),
    );
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    await screen.findByLabelText('일치 문서 · 혼재 판정 근거 보기');
    expect(
      screen.queryByLabelText('다른 기업 문서 · 혼재 판정 근거 보기'),
    ).toBeNull();
    expect(
      screen.queryByLabelText('다른 사건 문서 · 혼재 판정 근거 보기'),
    ).toBeNull();
    await userEvent.click(
      screen.getByLabelText('일치 문서 · 혼재 판정 근거 보기'),
    );
    expect(screen.getByText('합성 문서 판정 사유')).toBeTruthy();
    expect(screen.getByText('프롬프트 버전')).toBeTruthy();
  });
});
