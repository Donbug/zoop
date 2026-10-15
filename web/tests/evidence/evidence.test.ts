import { afterEach, describe, expect, it, vi } from 'vitest';
import { evidenceUrl, getEvidence } from '@/apis/evidence/evidence';
import {
  createMockEvidence,
  evidenceIdsForIssue,
  mockEvidenceRecords,
} from '@/mocks/evidence/fixture';
import { createFakeServer, json } from '../support/fakeServer';

afterEach(() => vi.unstubAllEnvs());

describe('D-GRP-05 · ERD v6 evidence fixture and contract seam', () => {
  it('preserves article versions and exclusive Unicode code-point offsets', () => {
    for (const evidence of mockEvidenceRecords) {
      expect(evidence.articleVersion).toBe(evidence.documentVersion);
      expect(evidence.end - evidence.start).toBe([...evidence.quote].length);
      expect(evidence.analysisProvenance?.sourceKind).toBe('synthetic');
      expect(evidence.metadata.source).toContain('MOCK');
    }
    expect(evidenceIdsForIssue('mock-issue-1')).toEqual([
      'mock-evidence-1',
      'mock-evidence-1-detail',
    ]);
  });

  it('models missing links and access states without exposing document content', () => {
    expect(createMockEvidence('mock-evidence-1', 'no-link').article?.url).toBe(
      null,
    );
    expect(() => createMockEvidence('mock-evidence-1', 'forbidden')).toThrow(
      '권한',
    );
    expect(() => createMockEvidence('mock-evidence-1', 'unavailable')).toThrow(
      '비공개',
    );
  });

  it('keeps the future public API boundary versioned and validates response identity', async () => {
    vi.stubEnv('VITE_EVIDENCE_DATA_SOURCE', 'api');
    const server = createFakeServer();
    server.on('GET', '/api/v1/evidence/:id', ({ params }) =>
      json(createMockEvidence(params.id)),
    );
    await expect(getEvidence('mock-evidence-1')).resolves.toMatchObject({
      id: 'mock-evidence-1',
      articleVersion: 'mock-article-v1',
    });
    expect(evidenceUrl('evidence:a/b')).toBe(
      '/api/v1/evidence/evidence%3Aa%2Fb',
    );
  });
});
