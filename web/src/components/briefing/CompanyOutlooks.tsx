import type { BriefingResponse } from '@/types/briefing';
import type {
  CompanyOutlook,
  CompanyStatement,
} from '@/types/briefing/companyOutlook';
import {
  BODY,
  FOCUS_RING,
  NOTE,
  SECTION,
  SECTION_TITLE,
} from './briefingStyles';
import { briefingTime } from '@/util/briefingTime';
import CompanyPrice from './CompanyPrice';

const assessments = {
  positive: '사업상 긍정 요인',
  negative: '사업상 부담 요인',
  mixed: '긍정·부담 요인 혼재',
  watch: '추가 확인 필요',
};

function Statement({
  value,
  company,
}: {
  value: CompanyStatement;
  company: CompanyOutlook;
}) {
  const refs = company.sources.filter((s) =>
    value.evidenceIds.includes(s.evidenceId),
  );
  return (
    <div className="mt-2">
      <p className={BODY}>{value.text}</p>
      <details className="mt-1">
        <summary
          className={`min-h-11 cursor-pointer content-center text-xs text-zoop-muted ${FOCUS_RING}`}
        >
          근거 인용 {refs.length}개 · 원문{' '}
          {new Set(refs.map((s) => s.documentId)).size}건
        </summary>
        <ul className="space-y-3 border-l-2 border-panel-line pl-3">
          {refs.map((source) => (
            <li key={source.evidenceId}>
              <a
                href={source.url}
                target="_blank"
                rel="noopener noreferrer"
                className={`text-sm underline ${FOCUS_RING}`}
              >
                {source.title} · 원문 ↗
              </a>
              <p className={NOTE}>
                발행 {briefingTime(source.publishedAt)} · 회차 마감 이전 자료
              </p>
              <blockquote className={`${NOTE} mt-1 whitespace-pre-wrap`}>
                {source.quote}
              </blockquote>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

/** D-BRF-01/02: separate the judgment, new fact and next observation. */
function SpecificReading({ company }: { company: CompanyOutlook }) {
  const reading = company.reading;
  const allowed = new Set(company.sources.map((s) => s.evidenceId));
  const statements = [
    reading?.brief,
    reading?.fact,
    reading?.watch,
    reading?.background,
    reading?.change,
  ];
  if (
    reading?.status !== 'PASS' ||
    statements.some(
      (s) =>
        !s?.text?.trim() ||
        !s.evidenceIds.length ||
        s.evidenceIds.some((id) => !allowed.has(id)),
    )
  )
    return (
      <p className={`${NOTE} mt-2`}>
        검증된 새 문안을 표시할 수 없습니다. 전문과 근거를 확인하세요.
      </p>
    );
  return (
    <div
      className="mt-3 space-y-3"
      aria-label={`${company.companyName} 판단과 새 사실`}
    >
      <div>
        <p className="text-xs font-semibold text-zoop-muted">한 줄 판단</p>
        <p className="mt-1 text-base leading-relaxed font-medium">
          {reading.brief?.text}
        </p>
      </div>
      <div>
        <p className="text-xs font-semibold text-zoop-muted">새 사실</p>
        <p className="mt-1 text-sm leading-relaxed">{reading.fact?.text}</p>
      </div>
      <div>
        <p className="text-xs font-semibold text-zoop-muted">다음 확인 조건</p>
        <p className="mt-1 text-sm leading-relaxed">{reading.watch?.text}</p>
      </div>
      <details>
        <summary
          className={`min-h-11 cursor-pointer content-center text-sm font-semibold ${FOCUS_RING}`}
        >
          배경·이전 판단과의 연결·문장 근거
        </summary>
        <h5 className="mt-2 text-sm font-semibold">비교할 배경</h5>
        {reading.background && (
          <Statement value={reading.background} company={company} />
        )}
        <h5 className="mt-3 text-sm font-semibold">이전 판단에서 달라진 점</h5>
        {reading.change && (
          <Statement value={reading.change} company={company} />
        )}
        <h5 className="mt-3 text-sm font-semibold">
          판단·새 사실·확인 조건의 근거
        </h5>
        {statements
          .slice(0, 3)
          .map(
            (value, i) =>
              value && <Statement key={i} value={value} company={company} />,
          )}
      </details>
    </div>
  );
}

/** D-BRF-01/02: reuse the complete stored sentence; never clip qualifiers. */
function summaryStatement(
  company: CompanyOutlook,
): CompanyStatement | undefined {
  const reading = company.reading;
  if (reading?.status !== 'PASS') return;
  const allowed = new Set(company.sources.map((source) => source.evidenceId));
  const statements =
    reading.schemaVersion === 'zoop-company-reading-v2'
      ? [
          reading.brief,
          reading.fact,
          reading.watch,
          reading.background,
          reading.change,
        ]
      : [reading.brief];
  if (
    statements.some(
      (value) =>
        !value?.text?.trim() ||
        !value.evidenceIds.length ||
        value.evidenceIds.some((id) => !allowed.has(id)),
    )
  )
    return;
  return reading.brief;
}

function CompanyAnalysis({
  company,
  edition,
}: {
  company: CompanyOutlook;
  edition: BriefingResponse['edition'];
}) {
  return (
    <details open className="mt-3">
      <summary
        className={`min-h-11 cursor-pointer content-center text-sm font-semibold ${FOCUS_RING}`}
      >
        자세히 · 기업 전망 전문과 근거
      </summary>
      {company.price?.status === 'available' && (
        <p className={`${NOTE} mt-2`}>
          사업 판단과 회차 기준 시세를 함께 확인하세요. 가격이 움직였다는
          사실만으로 이 뉴스의 영향이나 전망 적중을 단정하지 않습니다.
        </p>
      )}
      <h5 className="mt-3 text-sm font-semibold">조건부 기업 전망</h5>
      <Statement value={company.outlook} company={company} />
      <h5 className="mt-3 text-sm font-semibold">전망이 성립하려면</h5>
      {company.conditions.map((s, i) => (
        <Statement key={i} value={s} company={company} />
      ))}
      <h5 className="mt-3 text-sm font-semibold">확인된 사실</h5>
      {company.facts.map((s, i) => (
        <Statement key={i} value={s} company={company} />
      ))}
      <h5 className="mt-3 text-sm font-semibold">기업에 미치는 의미</h5>
      <Statement value={company.impact} company={company} />
      <h5 className="mt-3 text-sm font-semibold">반대 요인·아직 모르는 부분</h5>
      {company.risks.map((s, i) => (
        <Statement key={i} value={s} company={company} />
      ))}
      <div className="mt-3 border-t border-panel-line pt-3">
        <h5 className="text-sm font-semibold">
          {edition === 'morning'
            ? '이전 기업 전망에서 달라진 점'
            : '아침 판단과 실제 사업 정보 비교'}
        </h5>
        <Statement value={company.comparison} company={company} />
        {company.previous?.status === 'available' ? (
          <div className="mt-2 border-l-2 border-panel-line pl-3">
            <p className={NOTE}>
              기존 판단 · {briefingTime(company.previous.cutoff!)}
            </p>
            <p className={BODY}>{company.previous.judgment?.outlook.text}</p>
          </div>
        ) : (
          <p className={NOTE}>
            {edition === 'evening'
              ? '이 기업의 같은 날 아침 판단은 없습니다. 아침 시세 기준과 아침 전망 유무는 별개입니다.'
              : '이 기업의 이전 전망 기록이 없습니다.'}
          </p>
        )}
      </div>
      {company.reading?.status === 'PASS' && (
        <details className="mt-3">
          <summary
            className={`min-h-11 cursor-pointer content-center text-sm ${FOCUS_RING}`}
          >
            짧은 요약의 문장별 근거
          </summary>
          {[
            company.reading.brief,
            company.reading.watch,
            company.reading.change,
          ].map(
            (s, i) => s && <Statement key={i} value={s} company={company} />,
          )}
        </details>
      )}
    </details>
  );
}

/** D-BRF-01/02: one native disclosure opens the original price, reading and analysis. */
function CompanyAtAGlance({
  company,
  cutoff,
  edition,
}: {
  company: CompanyOutlook;
  cutoff: string;
  edition: BriefingResponse['edition'];
}) {
  const summary = summaryStatement(company);
  return (
    <details
      className="group rounded-panel border border-panel-line bg-zoop-paper"
      aria-label={`${company.companyName} 한눈 요약`}
    >
      <summary
        className={`min-h-11 cursor-pointer list-none p-4 [&::-webkit-details-marker]:hidden ${FOCUS_RING}`}
      >
        <div className="flex items-center gap-2">
          <h4 className="min-w-0 break-words text-sm font-bold">
            {company.companyName}
          </h4>
          <span
            className="ml-auto shrink-0 text-lg leading-none text-zoop-muted"
            aria-hidden="true"
          >
            <span className="group-open:hidden">＋</span>
            <span className="hidden group-open:inline">−</span>
          </span>
        </div>
        <p
          className="mt-2 whitespace-pre-wrap text-[15px] leading-relaxed font-medium"
          aria-label={`${company.companyName} 한눈 판단`}
        >
          {summary?.text ??
            '검증된 짧은 요약이 없습니다. 전문·시세·근거를 펼쳐보세요.'}
        </p>
        <p className="mt-2 text-xs text-zoop-muted">시세·전체 분석·근거 보기</p>
      </summary>
      <div className="border-t border-panel-line px-4 pb-4">
        <p className={`${NOTE} mt-3`}>{assessments[company.assessment]}</p>
        <CompanyPrice company={company} cutoff={cutoff} />
        {company.reading?.schemaVersion === 'zoop-company-reading-v2' && (
          <SpecificReading company={company} />
        )}
        <CompanyAnalysis company={company} edition={edition} />
      </div>
    </details>
  );
}

/** D-BRF-01·02: compact overview; full reading preserves all published content. */
export default function CompanyOutlooks({
  result,
  compact,
}: {
  result: Pick<
    BriefingResponse,
    'id' | 'edition' | 'dataAsOf' | 'items' | 'companyOutlooks'
  >;
  compact: boolean;
}) {
  const layer = result.companyOutlooks;
  if (!layer)
    return (
      <section className={SECTION} aria-label="핵심 이슈 기업별 전망">
        <h3 className={SECTION_TITLE}>기업별 전망 미제공</h3>
        <p className={NOTE}>
          이 회차에는 기업별 전망이 저장되어 있지 않습니다. 시장 요약은 아래에서
          확인할 수 있습니다.
        </p>
      </section>
    );
  const expected = new Set(
    result.items.flatMap((item) => item.companies.map((c) => c.id)),
  );
  const matches =
    layer.schemaVersion === 'zoop-company-outlooks-v1' &&
    layer.roundId === result.id &&
    layer.edition === result.edition &&
    result.dataAsOf !== null &&
    Date.parse(layer.cutoff) === Date.parse(result.dataAsOf) &&
    (layer.status !== 'PASS' ||
      (new Set(layer.companies.map((c) => c.companyId)).size ===
        expected.size &&
        layer.companies.length === expected.size &&
        layer.companies.every((c) => expected.has(c.companyId))));
  return (
    <section className={SECTION} aria-label="핵심 이슈 기업별 전망">
      <p className={NOTE}>
        {compact
          ? '기업별 판단을 먼저 읽고, 필요한 내용만 펼쳐보세요.'
          : '핵심 이슈에 연결된 기업 · 주가 신호와 구분한 사업 전망'}
      </p>
      <h3 className={`${SECTION_TITLE} mt-2`}>
        {compact
          ? '핵심 기업 한눈에'
          : result.edition === 'morning'
            ? '오늘의 기업별 전망'
            : '기업별 아침 판단 비교와 다음 전망'}
      </h3>
      {!matches || layer.status !== 'PASS' ? (
        <p className={NOTE}>
          {!matches
            ? '이 회차와 일치하는 기업 전망을 표시할 수 없습니다.'
            : layer.reason}
        </p>
      ) : (
        <div className={compact ? 'space-y-2.5' : 'space-y-5'}>
          {layer.companies.map((company) =>
            compact ? (
              <CompanyAtAGlance
                key={company.companyId}
                company={company}
                cutoff={layer.cutoff}
                edition={result.edition}
              />
            ) : (
              <article
                key={company.companyId}
                className="rounded-panel border border-panel-line bg-panel-soft p-4"
              >
                <h4 className="text-lg font-bold">{company.companyName}</h4>
                <p className={`${NOTE} mt-1`}>
                  {assessments[company.assessment]}
                </p>
                {company.reading?.schemaVersion ===
                  'zoop-company-reading-v2' && (
                  <SpecificReading company={company} />
                )}
                <CompanyPrice company={company} cutoff={layer.cutoff} />
                <CompanyAnalysis company={company} edition={result.edition} />
              </article>
            ),
          )}
        </div>
      )}
    </section>
  );
}
