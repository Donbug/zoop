import type { BriefingResponse } from '@/types/briefing';
import EditionReview from './EditionReview';
import JudgmentUpdate from './JudgmentUpdate';
import CompanyOutlooks from './CompanyOutlooks';
import MarketIndicators from './MarketIndicators';
import MarketSummary from './MarketSummary';
import BriefingReadingSection from './BriefingReadingSection';
import { validEditionReview } from '@/util/editionReview';
import { validJudgment } from '@/util/judgmentUpdate';
import { NOTE } from './briefingStyles';

export default function BriefingPreservedContext({
  result,
  compact,
}: {
  result: BriefingResponse;
  compact: boolean;
}) {
  return (
    <>
      <EditionReview result={result} compact={compact} />
      {validEditionReview(result) ? (
        <BriefingReadingSection compact title="이전 분석·기업 시세·근거 보존본">
          <JudgmentUpdate result={result} compact={compact} />
          <CompanyOutlooks result={result} compact={false} />
        </BriefingReadingSection>
      ) : (
        <>
          <JudgmentUpdate result={result} compact={compact} />
          {validJudgment(result) ? (
            <BriefingReadingSection
              compact
              title="기존 생성 전문·시세·근거 보존본"
            >
              <p className={NOTE}>
                아래는 비교 분석 추가 전 생성한 문안입니다. 좁은 인용에 따른
                과거의 ‘일정 미확인’ 표현은 위의 원문 전체 기반 판단을
                확인하세요.
              </p>
              <CompanyOutlooks result={result} compact={false} />
            </BriefingReadingSection>
          ) : (
            <CompanyOutlooks result={result} compact={compact} />
          )}
        </>
      )}
      {compact && (
        <MarketIndicators variables={result.marketVariables} compact />
      )}
      <BriefingReadingSection
        compact={compact}
        title={
          result.edition === 'morning'
            ? '시장 요약·시장 전체 전망 읽기'
            : '시장 요약·시장 흐름 비교 읽기'
        }
      >
        <MarketSummary
          summary={result.marketSummary}
          edition={result.edition}
          dataAsOf={result.dataAsOf}
        />
      </BriefingReadingSection>
      {!compact && <MarketIndicators variables={result.marketVariables} />}
    </>
  );
}
