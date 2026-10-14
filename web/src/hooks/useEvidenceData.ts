import { useEffect, useMemo, useState } from 'react';
import { ApiError } from '@/apis/auth/ApiService';
import { getEvidence } from '@/apis/evidence/evidence';
import type { EvidenceLoadFailure, EvidenceResponse } from '@/types/evidence';

function toFailure(id: string, error: unknown): EvidenceLoadFailure {
  if (error instanceof ApiError) {
    if (error.status === 403 || error.code === 'ACCESS_DENIED')
      return {
        id,
        kind: 'permission',
        message: '이 근거를 볼 권한이 없습니다.',
        retryable: false,
      };
    if (
      error.code === 'EVIDENCE_UNAVAILABLE' ||
      error.code === 'RESOURCE_NOT_FOUND' ||
      error.status === 404
    )
      return {
        id,
        kind: 'unavailable',
        message: '삭제되었거나 비공개인 근거라 내용을 제공할 수 없습니다.',
        retryable: false,
      };
  }
  return {
    id,
    kind: 'failed',
    message:
      error instanceof Error
        ? error.message
        : '근거 자료를 불러오지 못했습니다.',
    retryable: true,
  };
}

export function useEvidenceData(
  evidenceIds: string[],
  expectedGraphVersion: string | undefined,
  retry: number,
) {
  const ids = useMemo(() => [...new Set(evidenceIds)], [evidenceIds]);
  const idsKey = ids.join('\u001f');
  const key = `${idsKey}:${expectedGraphVersion ?? ''}:${retry}`;
  const [state, setState] = useState<{
    key: string;
    items: EvidenceResponse[];
    failures: EvidenceLoadFailure[];
  }>({ key: '', items: [], failures: [] });

  useEffect(() => {
    let active = true;
    if (ids.length === 0) {
      return () => {
        active = false;
      };
    }
    void Promise.allSettled(ids.map((id) => getEvidence(id))).then(
      (results) => {
        if (!active) return;
        const items: EvidenceResponse[] = [];
        const failures: EvidenceLoadFailure[] = [];
        results.forEach((result, index) => {
          const id = ids[index];
          if (result.status === 'rejected') {
            failures.push(toFailure(id, result.reason));
            return;
          }
          if (
            expectedGraphVersion &&
            result.value.metadata.graphVersion !== expectedGraphVersion
          ) {
            failures.push({
              id,
              kind: 'unavailable',
              message:
                '현재 지도의 데이터 버전과 근거 버전이 달라 표시하지 않습니다.',
              retryable: false,
            });
            return;
          }
          items.push(result.value);
        });
        setState({ key, items, failures });
      },
    );
    return () => {
      active = false;
    };
  }, [ids, key, expectedGraphVersion]);

  return state.key === key
    ? { items: state.items, failures: state.failures, loading: false }
    : { items: [], failures: [], loading: ids.length > 0 };
}
