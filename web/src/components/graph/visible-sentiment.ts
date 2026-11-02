import type { CompanyDocument } from '@/types/map/company';

/** 이 기업에 대한 문서 판정 중 보여도 되는 것만: 분석 완료, 작성 테스트 아님. */
export function visibleSentiment(document: CompanyDocument, companyId: string) {
  const sentiment = document.sentiment;
  if (
    !sentiment ||
    sentiment.companyId !== companyId ||
    (document.analysisStatus &&
      document.analysisStatus.sentiment.status !== 'available') ||
    document.analysisProvenance?.recordingKind === 'authored-test'
  )
    return null;
  return sentiment;
}
