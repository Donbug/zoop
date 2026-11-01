import type { PersonalAiCompany } from '@/types/personalBriefing';
import { NOTE, FOCUS_RING } from './briefingStyles';
import ImpactCue from '@/components/common/ImpactCue';
const labels = {
  positive: '사업상 긍정',
  negative: '사업상 부정',
  mixed: '긍정·위험 혼재',
  watch: '판단 유보',
};
/** D-BRF-01/02: source-bound personal business impact; never a trade or price guarantee. */
export default function PersonalAiJudgment({
  name,
  kinds,
  value,
}: {
  name: string;
  kinds: string[];
  value: PersonalAiCompany;
}) {
  return (
    <section
      aria-label={`${name} 개인화 AI 분석`}
      className="mt-3 space-y-3 border-t border-zoop-border pt-3 text-sm leading-relaxed"
    >
      <div className="flex flex-wrap items-center gap-2">
        <strong>{name}</strong>
        <ImpactCue tone={value.direction} badge>
          {labels[value.direction]}
        </ImpactCue>
      </div>
      <p className="font-semibold">{value.keyPoint.text}</p>
      <p>
        <strong>사업에 미치는 영향</strong>
        <br />
        {value.businessImpact.text}
      </p>
      <p>
        <strong>
          {kinds.includes('holding') ? '보유 종목 관점' : '관심 종목 관점'}
        </strong>
        <br />
        {value.forMyStocks.text}
      </p>
      <p>
        <strong>다음 확인사항</strong>
        <br />
        {value.nextCheck.text}
      </p>
      {value.priceObservation && (
        <p className={NOTE}>
          <strong>저장된 주가 관측</strong>
          <br />
          {value.priceObservation.text}
        </p>
      )}
      {value.previousChange.status !== 'unavailable' && (
        <p className={NOTE}>
          <strong>이전 판단에서 달라진 점</strong>
          <br />
          {value.previousChange.text}
        </p>
      )}
      <details>
        <summary
          className={`cursor-pointer text-xs font-semibold ${FOCUS_RING}`}
        >
          확인된 사실과 이전 비교 상태
        </summary>
        <p className="mt-2">{value.confirmedFact.text}</p>
        <p className={`${NOTE} mt-2`}>{value.previousChange.text}</p>
      </details>
    </section>
  );
}
