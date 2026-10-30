import DocumentSentiment from '@/components/graph/DocumentSentiment';
import type {
  BriefingDocumentSentiment,
  BriefingOutlook as Outlook,
  BriefingResponse,
} from '@/types/briefing';
import { briefingTime } from '@/util/briefingTime';
import {
  BODY,
  FOCUS_RING,
  NOTE,
  SECTION,
  SECTION_TITLE,
  STATUS_PILL,
} from './briefingStyles';

// D-BRF-01·02: port of prototype briefing-outlook.tsx, CorrectionNote and the per-issue sentiment list.

const outlookLabels = {
  positive: '긍정',
  negative: '부정',
  mixed: '혼재',
  undetermined: '판단 보류',
};

/** 발행 회차 판정. 근거 이슈는 화면에 있는 항목만 앵커로 잇고, 나머지는 제목만 보인다. */
export function BriefingOutlook({
  outlook,
  issues,
}: {
  outlook: Outlook | null | undefined;
  /** 회차 이슈와, 화면에 그린 경우의 앵커 id */
  issues: { eventId: string; title: string; anchor?: string }[];
}) {
  if (!outlook) return null;
  const linked = outlook.issueIds
    .map((id) => issues.find((issue) => issue.eventId === id))
    .filter((issue) => issue !== undefined);
  return (
    <section className={SECTION} aria-label="회차 판단">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="text-caption font-bold">회차 판단</h3>
        <span className={STATUS_PILL}>
          {outlookLabels[outlook.label]}
          <span className="sr-only"> 회차 판정</span>
        </span>
      </div>
      <p className={BODY}>{outlook.rationale}</p>
      {linked.length > 0 && (
        <p className={`${NOTE} mt-2 flex flex-wrap gap-x-3 gap-y-1`}>
          <span>근거 이슈</span>
          {linked.map((issue) =>
            issue.anchor ? (
              <a
                key={issue.eventId}
                href={`#${issue.anchor}`}
                className={`underline underline-offset-4 ${FOCUS_RING}`}
              >
                {issue.title}
              </a>
            ) : (
              <span key={issue.eventId}>{issue.title}</span>
            ),
          )}
        </p>
      )}
      <p className={`${NOTE} mt-2`}>주가 전망이 아니에요.</p>
    </section>
  );
}

type Correction = BriefingResponse['corrections'][number];

/** 정정 한 건. 발행 원문은 그대로 두고 정정 내용·사유·시각을 덧붙인다. */
export function BriefingCorrectionNote({
  correction,
}: {
  correction: Correction;
}) {
  return (
    <li className="flex flex-col gap-1 rounded-[3px] bg-zoop-wash p-3">
      <p className={NOTE}>정정 시각 {briefingTime(correction.createdAt)}</p>
      {correction.original && (
        <p className="text-caption text-zoop-faint line-through">
          발행 원문: {correction.original}
        </p>
      )}
      <p className="text-caption">정정 내용: {correction.corrected}</p>
      <p className={NOTE}>사유: {correction.reason}</p>
    </li>
  );
}

export function BriefingCorrections({
  corrections,
  title = '정정 이력',
}: {
  corrections: Correction[];
  title?: string;
}) {
  if (!corrections.length) return null;
  return (
    <section className={SECTION}>
      <h3 className={SECTION_TITLE}>{title}</h3>
      <ol className="flex flex-col gap-3">
        {corrections.map((correction) => (
          <BriefingCorrectionNote key={correction.id} correction={correction} />
        ))}
      </ol>
    </section>
  );
}

/** 이슈 아래에 붙는 정정. 회차 정정 목록과 같은 표기를 쓴다. */
export function IssueCorrections({
  corrections,
}: {
  corrections: Correction[];
}) {
  if (!corrections.length) return null;
  return (
    <ol aria-label="이 이슈의 정정" className="mt-2 flex flex-col gap-2">
      {corrections.map((correction) => (
        <BriefingCorrectionNote key={correction.id} correction={correction} />
      ))}
    </ol>
  );
}

/** 문서×기업 판정을 기업별로. 같은 문서·기업 판정은 한 번만 보이고 이슈 점수로 합치지 않는다. */
export function BriefingDocumentSentiments({
  sentiments,
  companies,
  label,
}: {
  sentiments: BriefingDocumentSentiment[] | undefined;
  companies: { id: string; name: string }[];
  label: string;
}) {
  const unique = [
    ...new Map(
      (sentiments ?? []).map((s) => [
        `${s.articleId}/${s.sentiment.companyId}`,
        s,
      ]),
    ).values(),
  ];
  if (!unique.length) return null;
  return (
    <ul aria-label={label} className="flex flex-col gap-1.5 text-caption">
      {unique.map(({ articleId, sentiment }) => {
        const name =
          companies.find((c) => c.id === sentiment.companyId)?.name ??
          '관련 기업';
        return (
          <li
            key={`${articleId}/${sentiment.companyId}`}
            className="flex flex-wrap items-center gap-x-2"
          >
            <span className="text-zoop-muted">{name} · 원문 판정</span>
            <DocumentSentiment value={sentiment} name={`${name} 근거 문서`} />
          </li>
        );
      })}
    </ul>
  );
}
