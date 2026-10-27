import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import CompanyLogo from '@/components/common/CompanyLogo';
import GraphIcon from '@/components/graph/GraphIcon';
import { useEffect, useRef } from 'react';
import type { Impact } from '@/types/company/detail';
import type { GraphResponse } from '@/types/map/graph';

type Props = {
  tutorialEvidence?: boolean;
  tutorialAi?: boolean;
  tutorialSaving?: boolean;
  companyId: string;
  issueId: string;
  graph: GraphResponse;
  impact: Impact | null;
  loading: boolean;
  error: string | null;
  errorCode?: string | null;
  errorStatus?: number | null;
  retryable?: boolean;
  onRetry: () => void;
  onClose: () => void;
  onViewIssue: () => void;
  onEvidence: (evidenceIds: string[]) => void;
  onAskAi: () => void;
};

const unique = (items: string[]) => [...new Set(items)];

const impactLabel = (label: Impact['impact']['results'][number]['label']) =>
  ({
    positive: '긍정',
    negative: '부정',
    mixed: '혼합',
    undetermined: '판정 불확정',
  })[label];

const impactUnavailable = (
  reason: Impact['impact']['reason'],
  pathType: Impact['pathType'],
) => {
  if (reason === 'no_public_path')
    return '공개 그래프에서 확인된 연결이 없습니다.';
  if (reason === 'not_recorded')
    return '검증된 영향 결과가 기록되어 있지 않습니다.';
  if (reason === 'not_verified') return '검증을 통과한 영향 결과가 없습니다.';
  if (reason === 'evidence_unavailable')
    return '필수 근거를 현재 열 수 없어 영향 결과를 표시하지 않습니다.';
  if (reason === 'issue_impact_not_produced' || pathType === 'structural')
    return '이 이슈가 이 기업에 미치는 영향 판정은 아직 제공되지 않습니다. 사업 관계만으로 영향 방향을 추정하지 않습니다.';
  return '영향 결과를 제공할 수 없습니다.';
};

const businessPathUnavailable = (
  reason: NonNullable<Impact['businessPath']>['reason'],
) => {
  if (reason === 'intermediate_company_unmapped')
    return '사업 사슬의 중간 기업이 매핑되지 않아 상세 경로를 제공할 수 없습니다.';
  if (reason === 'not_public')
    return '공개 기준을 충족한 사업 사슬을 확인할 수 없습니다.';
  if (reason === 'evidence_unavailable')
    return '사업 관계 근거를 현재 열 수 없어 상세 사슬을 제공하지 않습니다.';
  if (reason === 'not_recorded')
    return '이 자료에는 단계별 사업 사슬이 기록되어 있지 않습니다.';
  return '완전한 사업 사슬을 확인할 수 없습니다.';
};

// WBS 6.6.26 · D-GRP-06 · Figma 619:8880
export default function ImpactPathPanel({
  companyId,
  tutorialEvidence = false,
  tutorialAi = false,
  tutorialSaving = false,
  issueId,
  graph,
  impact,
  loading,
  error,
  errorCode = null,
  errorStatus = null,
  retryable = true,
  onRetry,
  onClose,
  onViewIssue,
  onEvidence,
  onAskAi,
}: Props) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [companyId, issueId]);
  const company = graph.nodes.find((node) => node.id === companyId);
  const evidenceIds = unique([
    ...(impact?.steps.flatMap((step) => step.evidenceIds) ?? []),
    ...(impact?.businessPath?.links.flatMap((link) => link.evidenceIds) ?? []),
    ...(impact?.impact.results.flatMap((result) => result.evidenceIds) ?? []),
  ]);
  const routeLabel =
    impact?.pathStatus === 'none'
      ? '확인된 연결 없음'
      : impact?.pathType === 'direct'
        ? '직접 연결'
        : impact?.pathType === 'structural'
          ? '구조적 연결'
          : loading
            ? '경로 조회 중'
            : '경로 정보 없음';
  const connectedCompanies = graph.edges
    .filter(
      (edge) =>
        !edge.derived &&
        (edge.source === issueId || edge.target === issueId) &&
        (edge.relationType === 'INVOLVES' ||
          edge.relationType === 'STRUCTURALLY_RELATED_TO'),
    )
    .map((edge) => {
      const connectedId = edge.source === issueId ? edge.target : edge.source;
      return {
        edge,
        company:
          connectedId === companyId
            ? undefined
            : graph.nodes.find((node) => node.id === connectedId),
      };
    })
    .filter((item) => item.company?.kind === 'company');

  return (
    <aside
      className={`event-panel ${ui.shell}`}
      data-screen-id="D-GRP-06"
      aria-labelledby="impact-panel-title"
      onKeyDown={(event) => {
        if (event.key === 'Escape') onClose();
      }}
    >
      <header className={ui.header}>
        <button
          className={`absolute top-4 right-4 ${ui.close}`}
          onClick={onClose}
          aria-label="영향 경로 닫기"
        >
          ×
        </button>
        <h2
          id="impact-panel-title"
          ref={heading}
          tabIndex={-1}
          className={`${ui.title} pr-10`}
        >
          {company?.label ?? companyId} · 영향 경로
        </h2>
        <p className={ui.muted}>
          {routeLabel} · 지도 기준{' '}
          {new Date(graph.metadata.asOf).toLocaleString('ko-KR')}
        </p>
      </header>
      <div className={ui.scroll} aria-busy={loading}>
        {loading && (
          <div className={ui.state} role="status">
            <span className="block h-14 rounded-panel bg-panel-line motion-safe:animate-pulse" />
            <p>영향 경로를 불러오는 중입니다.</p>
          </div>
        )}
        {error && (
          <div className={ui.state} role="alert">
            <strong>
              {errorStatus === 404 || errorCode === 'RESOURCE_NOT_FOUND'
                ? '선택한 기업 또는 이슈를 찾을 수 없습니다.'
                : errorStatus === 409 || errorCode === 'VERSION_UNAVAILABLE'
                  ? '요청한 그래프 버전을 사용할 수 없습니다.'
                  : errorStatus === 422 || errorCode === 'INVALID_REQUEST'
                    ? '그래프 버전과 기준 시점을 함께 확인해 주세요.'
                    : errorStatus === 403 || errorCode === 'ACCESS_DENIED'
                      ? '이 경로를 볼 권한이 없습니다.'
                      : '영향 경로를 불러오지 못했습니다.'}
            </strong>
            <p>
              {errorStatus === 404 || errorCode === 'RESOURCE_NOT_FOUND'
                ? '지도의 기업과 이슈 선택을 확인한 뒤 다시 열어 주세요.'
                : errorStatus === 409 || errorCode === 'VERSION_UNAVAILABLE'
                  ? '현재 그래프 기준으로 경로를 다시 조회해 주세요.'
                  : errorStatus === 422 || errorCode === 'INVALID_REQUEST'
                    ? '선택 시점 또는 회차를 확인한 뒤 다시 열어 주세요.'
                    : errorStatus === 503 || errorCode === 'SOURCE_UNAVAILABLE'
                      ? '공개 자료를 읽는 중 문제가 발생했습니다. 잠시 뒤 다시 시도해 주세요.'
                      : error}
            </p>
            {retryable && (
              <button data-tutorial-action="retry" onClick={onRetry}>
                다시 시도
              </button>
            )}
          </div>
        )}
        {impact && (
          <>
            <div className={ui.actions}>
              <button onClick={onViewIssue}>사건 상세 보기</button>
              <button
                className={`bg-panel-ink! text-white! ${tutorialAi ? 'tutorial-target tutorial-ai-target' : ''}`}
                disabled={tutorialSaving}
                onClick={onAskAi}
              >
                <GraphIcon name="ai" size={14} />
                AI에게 묻기
              </button>
            </div>
            <section
              className={ui.section}
              aria-labelledby="impact-route-title"
            >
              <h3 id="impact-route-title">확인된 연결</h3>
              {impact.pathStatus === 'none' ? (
                <p className={ui.state} role="status">
                  공개 그래프에서 확인된 이슈·기업 연결이 없습니다.
                </p>
              ) : impact.steps.length ? (
                <ol className="m-0 list-none p-0">
                  {impact.steps.map((step, index) => {
                    const node = graph.nodes.find(
                      (item) => item.id === step.id,
                    );
                    const stepEvidence = unique(step.evidenceIds);
                    return (
                      <li
                        key={`${step.id}-${index}`}
                        className="relative flex gap-2.5 py-2.5 not-last:border-b not-last:border-panel-line"
                      >
                        {node?.kind === 'company' ? (
                          <CompanyLogo
                            name={node.label}
                            logoUrl={node.logoUrl}
                            className={ui.avatar}
                          />
                        ) : (
                          <span className={ui.avatar} aria-hidden="true">
                            {node ? '◇' : '•'}
                          </span>
                        )}
                        <div className="min-w-0 flex-1">
                          <p className={ui.muted}>
                            {node?.kind === 'issue' ? '사건' : '기업'} ·{' '}
                            {step.reason}
                          </p>
                          <strong className={ui.itemTitle}>
                            {node?.label ?? step.id}
                          </strong>
                          <button
                            className="mt-1 text-[11px] font-semibold underline disabled:text-panel-muted"
                            disabled={stepEvidence.length === 0}
                            data-tutorial-action={
                              tutorialEvidence ? 'evidence' : undefined
                            }
                            data-tutorial-evidence={
                              tutorialEvidence || undefined
                            }
                            onClick={() => onEvidence(stepEvidence)}
                          >
                            근거 {stepEvidence.length}건 보기
                          </button>
                        </div>
                      </li>
                    );
                  })}
                </ol>
              ) : (
                <p className={ui.muted}>표시할 연결 단계가 없습니다.</p>
              )}
            </section>
            {impact.pathType === 'structural' && impact.businessPath && (
              <section
                className={ui.section}
                aria-labelledby="impact-business-path-title"
              >
                <h3 id="impact-business-path-title">사업 관계 사슬</h3>
                {impact.businessPath.status === 'complete' ? (
                  <ol className="m-0 list-none p-0">
                    {impact.businessPath.links.map((link, index) => {
                      const supplier = graph.nodes.find(
                        (node) => node.id === link.supplierCompanyId,
                      );
                      const customer = graph.nodes.find(
                        (node) => node.id === link.customerCompanyId,
                      );
                      const stepEvidence = unique(link.evidenceIds);
                      return (
                        <li
                          key={`${link.supplierCompanyId}-${link.customerCompanyId}-${index}`}
                          className="py-2.5 not-last:border-b not-last:border-panel-line"
                        >
                          <p className={ui.itemTitle}>
                            공급자 {supplier?.label ?? link.supplierCompanyId} ·
                            고객 {customer?.label ?? link.customerCompanyId}
                          </p>
                          <p className={ui.muted}>{link.reason}</p>
                          <button
                            className="mt-1 text-[11px] font-semibold underline disabled:text-panel-muted"
                            disabled={!stepEvidence.length}
                            onClick={() => onEvidence(stepEvidence)}
                          >
                            근거 {stepEvidence.length}건 보기
                          </button>
                        </li>
                      );
                    })}
                  </ol>
                ) : (
                  <p className={ui.state} role="status">
                    {businessPathUnavailable(impact.businessPath.reason)}
                  </p>
                )}
              </section>
            )}
            <section
              className={ui.section}
              aria-labelledby="impact-results-title"
            >
              <h3 id="impact-results-title">검증된 영향 결과</h3>
              {impact.impact.status === 'available' ? (
                impact.impact.results.length ? (
                  <ul className={`${ui.list} [&>li]:py-3`}>
                    {impact.impact.results.map((result) => (
                      <li key={result.impactId}>
                        <strong className={ui.itemTitle}>
                          영향 판정 · {impactLabel(result.label)}
                        </strong>
                        <p className={ui.muted}>
                          효과 근거 {result.evidenceIds.length}건 · 긍정{' '}
                          {result.effects.positive.length} · 부정{' '}
                          {result.effects.negative.length} · 중립{' '}
                          {result.effects.neutral.length} · 불확실{' '}
                          {result.effects.uncertain.length}
                        </p>
                        <button
                          className="mt-1 text-[11px] font-semibold underline disabled:text-panel-muted"
                          disabled={!result.evidenceIds.length}
                          onClick={() => onEvidence(result.evidenceIds)}
                        >
                          결과 근거 보기
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className={ui.state} role="status">
                    검증된 영향 결과가 없습니다.
                  </p>
                )
              ) : (
                <p className={ui.state} role="status">
                  {impactUnavailable(impact.impact.reason, impact.pathType)}
                </p>
              )}
            </section>
            <section
              className={ui.section}
              aria-labelledby="impact-company-title"
            >
              <h3 id="impact-company-title">
                함께 연결된 기업 {connectedCompanies.length}곳
              </h3>
              {connectedCompanies.length ? (
                <ul className={`${ui.list} [&>li]:flex [&>li]:gap-2.5`}>
                  {connectedCompanies.map(({ edge, company: connected }) => (
                    <li key={edge.id}>
                      <CompanyLogo
                        name={connected?.label ?? ''}
                        logoUrl={connected?.logoUrl}
                        className={ui.avatar}
                      />
                      <div className="min-w-0">
                        <strong className={ui.itemTitle}>
                          {connected?.label}
                        </strong>
                        <p className={ui.muted}>
                          {edge.summary || '직접 관련'} · 근거{' '}
                          {edge.evidenceIds.length}건
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className={ui.muted}>함께 연결된 다른 기업이 없습니다.</p>
              )}
            </section>
            <section
              className={ui.section}
              aria-labelledby="impact-limit-title"
            >
              <h3 id="impact-limit-title">해석 한계</h3>
              <ul className="list-disc space-y-1 pl-4 text-panel-secondary">
                <li>
                  위 연결은 기사에 적힌 사실과 승인된 사업 관계이며, 주가나 실적
                  영향을 판단하지 않아요.
                </li>
                {impact.pathType === 'structural' && (
                  <li>
                    사업 관계는 이 이슈가 대상 기업에 영향을 줬다는 판정과
                    다릅니다.
                  </li>
                )}
                <li>
                  계획·전망 표현은 실제 발생이 확인된 사건과 구분해서 살펴봐야
                  해요.
                </li>
              </ul>
            </section>
            <footer className={ui.footer}>
              <p>{impact.metadata.source}</p>
              <p>경로 근거 {evidenceIds.length}건 · 화면 ID D-GRP-06</p>
            </footer>
          </>
        )}
      </div>
    </aside>
  );
}
