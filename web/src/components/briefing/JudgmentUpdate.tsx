import type { BriefingResponse } from '@/types/briefing';
import type { CompanyStatement } from '@/types/briefing/companyOutlook';
import type {
  JudgmentUpdate as Update,
  JudgmentCompany,
} from '@/types/briefing/judgmentUpdate';
import { briefingTime } from '@/util/briefingTime';
import {
  BODY,
  FOCUS_RING,
  NOTE,
  SECTION,
  SECTION_TITLE,
} from './briefingStyles';
import CompanyPrice from './CompanyPrice';
import { validJudgment } from '@/util/judgmentUpdate';

const decisions = {
  initial: '이번 자료로 판단',
  maintained: '기존 판단 유지',
  strengthened: '판단 강화',
  weakened: '판단 약화',
  unassessable: '갱신 판단 불가',
};

function Statement({
  value,
  update,
}: {
  value: CompanyStatement;
  update: Update;
}) {
  return (
    <div className="mt-2">
      <p className={BODY}>{value.text}</p>
      <details className="mt-1">
        <summary
          className={`min-h-11 cursor-pointer content-center text-caption text-zoop-muted ${FOCUS_RING}`}
        >
          출처·검증에 사용한 원문 문맥 {value.evidenceIds.length}건
        </summary>
        <ul className="space-y-3 border-l-2 border-zoop-border pl-3">
          {value.evidenceIds.map((id) => {
            const source = update.sources![id];
            return (
              <li key={id}>
                <a
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`text-body underline ${FOCUS_RING}`}
                >
                  {source.title} · 원문 ↗
                </a>
                <p className={NOTE}>보도 {briefingTime(source.publishedAt)}</p>
                {source.fullBody ? (
                  <details>
                    <summary
                      className={`min-h-11 cursor-pointer content-center text-caption ${FOCUS_RING}`}
                    >
                      보존 원문 보기
                    </summary>
                    <blockquote
                      className={`${NOTE} max-h-64 overflow-auto whitespace-pre-wrap`}
                    >
                      {source.fullBody}
                    </blockquote>
                  </details>
                ) : (
                  <p className={NOTE}>
                    전체 본문은 포함되지 않았습니다. 원문 링크에서 확인해
                    주세요.
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      </details>
    </div>
  );
}

function Company({
  company: c,
  update,
  result,
  compact,
}: {
  company: JudgmentCompany;
  update: Update;
  result: BriefingResponse;
  compact: boolean;
}) {
  const price = result.companyOutlooks?.companies.find(
    (p) => p.companyId === c.companyId,
  );
  return (
    <details
      open={!compact}
      className="rounded-lg border border-zoop-border bg-zoop-surface p-4"
      aria-label={`${c.companyName} 판단 갱신`}
    >
      <summary className={`cursor-pointer list-none ${FOCUS_RING}`}>
        <span className="flex flex-wrap items-center gap-2">
          <strong className="text-lead">{c.companyName}</strong>
          <span className="text-caption text-zoop-muted">{c.topic.text}</span>
          <span className="ml-auto text-caption text-zoop-muted">
            {decisions[c.decision]} · 펼치기
          </span>
        </span>
        <span className="mt-2 block text-title-sm font-bold leading-snug">
          {c.title.text}
        </span>
        <span className="mt-2 block text-body text-zoop-muted">
          {c.description.text}
        </span>
      </summary>
      <div className="mt-4 space-y-4 border-t border-zoop-border pt-3">
        <div>
          <h4 className="text-body font-semibold">이전 실제 판단</h4>
          {c.previousJudgment ? (
            <>
              <p className={`${NOTE} mt-2`}>
                {c.previousJudgment.outlook.text}
              </p>
              <p className={`${NOTE} mt-1`}>
                이전 확인 조건:{' '}
                {c.previousJudgment.conditions.map((s) => s.text).join(' ')}
              </p>
            </>
          ) : (
            <p className={`${NOTE} mt-2`}>
              직전 비교 회차에 이 기업의 판단이 없습니다. 이번 자료로 새로
              판단합니다.
            </p>
          )}
        </div>
        <div>
          <h4 className="text-body font-semibold">
            {c.role === 'watch' ? '이번 확인 범위' : '새 근거'}
          </h4>
          <Statement value={c.newEvidence} update={update} />
        </div>
        <div>
          <h4 className="text-body font-semibold">이번 판단의 이유</h4>
          <Statement value={c.reason} update={update} />
        </div>
        <div>
          <h4 className="text-body font-semibold">
            무엇이 확인되면 강화하나요?
          </h4>
          <Statement value={c.strengthenIf} update={update} />
        </div>
        <div>
          <h4 className="text-body font-semibold">무엇이 확인되면 낮추나요?</h4>
          <Statement value={c.weakenIf} update={update} />
        </div>
        {price && <CompanyPrice company={price} cutoff={update.cutoff} />}
      </div>
    </details>
  );
}

export default function JudgmentUpdate({
  result,
  compact,
}: {
  result: BriefingResponse;
  compact: boolean;
}) {
  const update = validJudgment(result);
  if (!update)
    return result.judgmentUpdate ? (
      <section className={SECTION}>
        <h3 className={SECTION_TITLE}>판단 갱신</h3>
        <p className={NOTE}>
          비교 판단을 검증해 표시할 수 없습니다. 기존 기업 분석과 근거를
          확인하세요.
        </p>
      </section>
    ) : null;
  return (
    <section className={SECTION} aria-label="새 정보로 갱신한 판단">
      <h3 className={SECTION_TITLE}>이번 판단</h3>
      <Statement value={update.conclusion!} update={update} />
      <p className={`${NOTE} mt-2`}>
        비교 기준 {briefingTime(update.previousCutoff)} →{' '}
        {briefingTime(update.cutoff)} · 기업별 사업 판단과 산업 해석
      </p>
      <details open={!compact} className="my-3">
        <summary
          className={`min-h-11 cursor-pointer content-center text-body font-semibold ${FOCUS_RING}`}
        >
          이전 자료에서 무엇이 달라졌나요?
        </summary>
        <Statement value={update.industryChange!} update={update} />
      </details>
      <h3 className="my-3 text-body font-semibold">이번 핵심 기업 한눈에</h3>
      <div className="space-y-3">
        {update
          .companies!.filter((c) => c.role === 'selected')
          .map((c) => (
            <Company
              key={c.companyId}
              company={c}
              update={update}
              result={result}
              compact={compact}
            />
          ))}
      </div>
      {update.companies!.some((c) => c.role === 'watch') && (
        <>
          <h3 className="mt-5 mb-2 text-body font-semibold">
            이전 기업의 미해결 조건 추적
          </h3>
          <p className={`${NOTE} mb-3`}>
            이번 핵심 선정과 구분합니다. 새로운 확인 자료가 없는 기업은 기존
            조건을 유지합니다.
          </p>
          <div className="space-y-3">
            {update
              .companies!.filter((c) => c.role === 'watch')
              .map((c) => (
                <Company
                  key={c.companyId}
                  company={c}
                  update={update}
                  result={result}
                  compact={compact}
                />
              ))}
          </div>
        </>
      )}
      <details className="mt-4">
        <summary
          className={`min-h-11 cursor-pointer content-center text-caption text-zoop-muted ${FOCUS_RING}`}
        >
          해석·검토 범위
        </summary>
        <Statement value={update.limits!} update={update} />
        <p className={`${NOTE} mt-2`}>{update.scopeNote}</p>
        {update.editorialReview && (
          <p className={`${NOTE} mt-2`}>
            원문 대조 후 편집한 검토본입니다. 자동 근거 검증은 편집 전 AI 초안에
            적용되었습니다.
          </p>
        )}
      </details>
    </section>
  );
}
