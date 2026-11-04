import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import LoadingIndicator from '@/components/common/LoadingIndicator';
import CompanyLogo from '@/components/common/CompanyLogo';
import GraphIcon from '@/components/graph/GraphIcon';
import { useEffect, useRef, useState } from 'react';
import { useRelationData } from '@/hooks/useRelationData';
import type { Impact } from '@/types/company/detail';
import type { EventContext } from '@/types/map/event';
import type { GraphResponse } from '@/types/map/graph';
import type { StructuralSupplyLink } from '@/types/map/relation';
import StructuralRelationSection from './StructuralRelationSection';
import ImpactCue from '@/components/common/ImpactCue';
import type { CompanyIssueImpactAssessment } from '@/types/map/impact-assessment';

type Props = {
  tutorialEvidence?: boolean;
  tutorialAi?: boolean;
  tutorialSaving?: boolean;
  companyId: string;
  issueId: string;
  context: EventContext;
  graph: GraphResponse;
  impact: Impact | null;
  assessment?: CompanyIssueImpactAssessment | null;
  assessmentLoading?: boolean;
  assessmentError?: string | null;
  assessmentRetryable?: boolean;
  onAssessmentRetry?: () => void;
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
  onSelectNode?: (id: string) => void;
};

const unique = (items: string[]) => [...new Set(items)];

// WBS 6.6.26 · D-GRP-06 · Figma 619:8880
export default function ImpactPathPanel({
  companyId,
  tutorialEvidence = false,
  tutorialAi = false,
  tutorialSaving = false,
  issueId,
  context,
  graph,
  impact,
  assessment,
  assessmentLoading = false,
  assessmentError = null,
  assessmentRetryable = false,
  onAssessmentRetry = () => {},
  loading,
  error,
  retryable = true,
  onRetry,
  onClose,
  onViewIssue,
  onEvidence,
  onAskAi,
  onSelectNode,
}: Props) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [companyId, issueId]);
  const company = graph.nodes.find((node) => node.id === companyId);
  const structuralEdge = graph.edges.find(
    (edge) =>
      !edge.derived &&
      edge.relationType === 'STRUCTURALLY_RELATED_TO' &&
      [edge.source, edge.target].includes(companyId) &&
      [edge.source, edge.target].includes(issueId),
  );
  const evidenceIds = unique(
    impact?.steps.flatMap((step) => step.evidenceIds) ?? [],
  );
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
        <p className={`${ui.muted} inline-flex items-center gap-1`}>
          {loading ? (
            <>
              <LoadingIndicator label="연결 확인 중" size="sm" />{' '}
              <span className="sr-only">연결 확인 중</span>
            </>
          ) : error ? (
            '연결 확인 불가'
          ) : impact?.pathStatus === 'structural_path_details_unavailable' ? (
            '구조 관계 확인'
          ) : impact?.pathStatus === 'direct_available' ? (
            '직접 연결 확인'
          ) : impact?.pathStatus === 'no_direct_relation' ? (
            '직접 연결 미확인'
          ) : impact?.steps.length ? (
            '연결 확인'
          ) : (
            '직접 연결 미확인'
          )}{' '}
          · 지도 기준 {new Date(graph.metadata.asOf).toLocaleString('ko-KR')}
        </p>
      </header>
      <div className={ui.scroll} aria-busy={loading}>
        {impact?.metadata.partial && (
          <p className="px-4 py-2 text-caption text-zoop-alert" role="status">
            현재 공개 권한을 확인할 수 있는 근거만 표시합니다.
          </p>
        )}
        {loading && (
          <LoadingIndicator
            label="영향 경로를 불러오는 중입니다."
            className={`${ui.state} flex min-h-14 w-full`}
          />
        )}
        {error && (
          <div className={ui.state} role="alert">
            <strong>영향 경로를 불러오지 못했습니다.</strong>
            <p>{error}</p>
            <p>지도와 기업 선택은 그대로 유지됩니다.</p>
            {retryable ? (
              <button data-tutorial-action="retry" onClick={onRetry}>
                다시 시도
              </button>
            ) : (
              <p>
                선택한 그래프 버전을 확인한 뒤 기업과 이슈를 다시 선택해 주세요.
              </p>
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
              {impact.steps.length ? (
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
                            className="mt-1 text-caption font-semibold underline disabled:text-panel-muted"
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
                <p className={ui.muted}>
                  {impact.pathStatus === 'structural_path_details_unavailable'
                    ? '구조 관계가 공개 그래프에서 확인됐습니다. 경로 상세와 단계별 근거는 아래 사업 관계 상세에서 확인합니다.'
                    : '선택한 그래프에서 기업과 이슈 사이의 직접 연결을 확인하지 못했습니다.'}
                </p>
              )}
            </section>
            {impact.pathStatus === 'direct_available' && (
              <section
                className={ui.section}
                aria-labelledby="impact-assessment-title"
              >
                <h3 id="impact-assessment-title">기사 인용 영향 평가</h3>
                <p className={ui.muted}>
                  인용 문장에 나타난 사업상 효과를 검증한 결과입니다. 주가나
                  실적의 방향을 예측하지 않습니다.
                </p>
                {assessmentLoading && (
                  <LoadingIndicator
                    label="검증된 영향 평가를 불러오는 중입니다."
                    className="flex min-h-12 w-full"
                  />
                )}
                {assessmentError && (
                  <div role="alert" className="space-y-2">
                    <p>영향 평가를 불러오지 못했습니다. {assessmentError}</p>
                    {assessmentRetryable && (
                      <button className={ui.button} onClick={onAssessmentRetry}>
                        다시 시도
                      </button>
                    )}
                  </div>
                )}
                {!assessmentLoading &&
                  !assessmentError &&
                  assessment?.status === 'unavailable' && (
                    <p className={ui.muted}>
                      {assessmentMessage(assessment.reason)}
                    </p>
                  )}
                {!assessmentLoading &&
                  !assessmentError &&
                  assessment?.status === 'available' && (
                    <ol className="m-0 list-none space-y-3 p-0">
                      {assessment.results.map((result, index) => (
                        <li
                          key={result.impactId}
                          className="space-y-2 border-t border-panel-line pt-3"
                        >
                          <ImpactCue tone={result.label} badge>
                            {impactLabels[result.label]}
                          </ImpactCue>
                          {(result.provenance.executionMode === 'replay' ||
                            result.provenance.sourceKind === 'synthetic') && (
                            <p className={ui.muted}>
                              합성 재생 시험 결과 · 실제 뉴스에 대한 실시간 AI
                              판정이 아닙니다.
                            </p>
                          )}
                          {effectGroups(result).map(
                            ({ label, evidenceIds }) => (
                              <button
                                key={`${index}-${label}`}
                                type="button"
                                className={`${ui.button} mr-2 mt-1`}
                                onClick={() => onEvidence(evidenceIds)}
                              >
                                {label} {evidenceIds.length}건 보기
                              </button>
                            ),
                          )}
                        </li>
                      ))}
                    </ol>
                  )}
              </section>
            )}
            {structuralEdge && (
              <StructuralImpactDetails
                key={`${structuralEdge.id}:${JSON.stringify(context)}`}
                edgeId={structuralEdge.id}
                context={context}
                onEvidence={(link) => onEvidence(unique(link.evidenceIds))}
              />
            )}
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
                        <button
                          type="button"
                          className={`${ui.itemTitle} text-left underline underline-offset-4 focus-visible:outline-2`}
                          disabled={!onSelectNode}
                          onClick={() =>
                            connected && onSelectNode?.(connected.id)
                          }
                        >
                          {connected?.label}
                        </button>
                        <p className={ui.muted}>
                          {edge.relationType === 'INVOLVES'
                            ? '직접 관련'
                            : '구조적 관련'}{' '}
                          ·{' '}
                          {(edge.role === 'participant'
                            ? '참여 기업'
                            : edge.role) ||
                            edge.summary ||
                            '공개 그래프 연결'}
                        </p>
                        <button
                          type="button"
                          className={`${ui.button} mt-1`}
                          disabled={!edge.evidenceIds.length}
                          onClick={() => onEvidence(unique(edge.evidenceIds))}
                        >
                          근거 {unique(edge.evidenceIds).length}건
                        </button>
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

const impactLabels = {
  positive: '긍정',
  negative: '부정',
  mixed: '긍정·부정 혼재',
  undetermined: '판단 보류',
} as const;

function assessmentMessage(reason: CompanyIssueImpactAssessment['reason']) {
  switch (reason) {
    case 'no_public_path':
      return '공개된 직접 연결이 없어 영향 평가를 찾을 수 없습니다.';
    case 'not_recorded':
      return '이 그래프 버전에는 저장된 영향 평가가 없습니다.';
    case 'evidence_unavailable':
      return '현재 공개 권한을 확인할 수 있는 근거가 없어 평가를 표시하지 않습니다.';
    case 'issue_impact_not_produced':
      return '이 관계 유형에 대한 영향 평가는 아직 제공되지 않습니다.';
    case 'not_verified':
    default:
      return '공개할 수 있도록 검증된 영향 평가가 없습니다.';
  }
}

function effectGroups(result: CompanyIssueImpactAssessment['results'][number]) {
  const labels = {
    positive: '긍정 근거',
    negative: '부정 근거',
    neutral: '중립 근거',
    uncertain: '불확실 근거',
  } as const;
  return (Object.keys(labels) as (keyof typeof labels)[])
    .map((effect) => ({
      label: labels[effect],
      evidenceIds: result.effects[effect],
    }))
    .filter((group) => group.evidenceIds.length > 0);
}

function StructuralImpactDetails({
  edgeId,
  context,
  onEvidence,
}: {
  edgeId: string;
  context: EventContext;
  onEvidence: (link: StructuralSupplyLink) => void;
}) {
  const [retry, setRetry] = useState(0);
  const { data, loading, error, retryable } = useRelationData(
    edgeId,
    context,
    retry,
  );
  const failure = data?.metadata.failures.find(
    (item) => item.section === 'structuralDetails',
  );
  if (loading && !data)
    return (
      <section className={ui.section} aria-label="사업 관계 상세" role="status">
        <LoadingIndicator
          label="사업 관계 상세를 불러오는 중입니다."
          className="flex min-h-14 w-full"
        />
      </section>
    );
  if (error && !data)
    return (
      <section className={ui.section} aria-label="사업 관계 상세" role="alert">
        <p>사업 관계 상세를 불러오지 못했습니다.</p>
        <p>{error}</p>
        {retryable ? (
          <button onClick={() => setRetry((value) => value + 1)}>
            다시 시도
          </button>
        ) : (
          <p className={ui.muted}>
            선택한 그래프 버전에서 사업 관계 상세를 찾지 못했습니다. 기업과
            이슈를 다시 선택해 주세요.
          </p>
        )}
      </section>
    );
  if (!data) return null;
  return (
    <StructuralRelationSection
      details={data.structuralDetails}
      failure={failure}
      onRetry={() => setRetry((value) => value + 1)}
      onEvidence={onEvidence}
    />
  );
}
