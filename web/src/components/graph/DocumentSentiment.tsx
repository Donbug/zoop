import type { DocumentSentiment as Sentiment } from '@/types/evidence';
import { formatPublishedAt } from './event-format';
import PanelDisclosure from './PanelDisclosure';

// D-GRP-03/05 · port of domain/status-labels.tsx SentimentLabel.
// A document's judgement is never aggregated into an event-level score.
export default function DocumentSentiment({
  value,
  name = '사건 근거 문서',
}: {
  value: Sentiment;
  name?: string;
}) {
  const label = {
    positive: '긍정',
    negative: '부정',
    mixed: '혼재',
    undetermined: '판단 보류',
  }[value.label];
  return (
    <div className="inline-flex flex-wrap items-start gap-1.5">
      <PanelDisclosure
        label={`${name} · ${label} 판정 근거 보기`}
        trigger={label}
      >
        <p className="font-semibold text-zoop-ink">{label} 판정 근거</p>
        <p className="wrap-anywhere">{value.rationale}</p>
        {value.quotes.length > 0 && (
          <div className="flex flex-col gap-2">
            <p className="font-semibold text-zoop-ink">원문 인용</p>
            {value.quotes.map((quote, index) => (
              <blockquote key={index}>“{quote}”</blockquote>
            ))}
          </div>
        )}
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 border-t border-zoop-line pt-2">
          <dt>판정 시각</dt>
          <dd>
            <time dateTime={value.judgedAt}>
              {formatPublishedAt(value.judgedAt) ?? '미제공'}
            </time>
          </dd>
          <dt>모델</dt>
          <dd className="wrap-anywhere">{value.model}</dd>
          <dt>프롬프트 버전</dt>
          <dd className="wrap-anywhere">{value.promptVersion}</dd>
        </dl>
      </PanelDisclosure>
      <span className="text-zoop-muted">AI 판정</span>
    </div>
  );
}
