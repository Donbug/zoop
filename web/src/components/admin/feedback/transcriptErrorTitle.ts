import { ApiError } from '@/apis/auth/ApiService';

/** A-ADM-02b: show the actual failed gate, never an empty successful transcript. */
export function transcriptErrorTitle(error: Error) {
  if (error instanceof ApiError) {
    if (error.status === 403) return '대화록을 볼 권한이 없어요';
    if (error.status === 422) return '열람 목적과 조회 조건을 확인해 주세요';
    if (error.status === 404) return '찾는 대화록이 없어요';
    if (error.code === 'MASKING_FAILED')
      return '개인정보를 가리지 못해 대화록을 보여 주지 않았어요';
    if (error.code === 'AUDIT_UNAVAILABLE')
      return '열람 기록을 남기지 못해 대화록을 보여 주지 않았어요';
  }
  return '대화록을 불러오지 못했어요';
}
