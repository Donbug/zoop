import type { EventContext } from '@/types/map/event';
import { snapshotUrl, assertSnapshot } from '@/apis/graph/snapshot';
import { call } from '@/apis/auth/ApiService';
import type { EvidenceMockScenario } from '@/mocks/evidence/fixture';
import type { EvidenceResponse } from '@/types/evidence';

export const usesEvidenceMock =
  import.meta.env.DEV && import.meta.env.VITE_EVIDENCE_DATA_SOURCE !== 'api';

export function evidenceUrl(id: string) {
  return `/api/v1/evidence/${encodeURIComponent(id)}`;
}

export async function getEvidence(
  id: string,
  context: EventContext = {},
): Promise<EvidenceResponse> {
  // D-GRP-04 mock targets must never fall through to a production API.
  if (!context.round && (usesEvidenceMock || id.startsWith('mock-evidence-'))) {
    const { createMockEvidence } = await import('@/mocks/evidence/fixture');
    await new Promise((resolve) => setTimeout(resolve, 220));
    return createMockEvidence(
      id,
      import.meta.env.VITE_EVIDENCE_MOCK_SCENARIO as
        EvidenceMockScenario | undefined,
    );
  }
  const evidence = await call<EvidenceResponse>(
    snapshotUrl(evidenceUrl(id), context),
    'GET',
    undefined,
    {
      skipAuth: true,
    },
  );
  if (evidence.id !== id)
    throw new Error('요청한 근거와 응답이 일치하지 않습니다.');
  if (context.round) assertSnapshot(evidence.metadata, context);
  return evidence;
}
