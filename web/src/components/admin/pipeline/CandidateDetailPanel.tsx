import { useCallback, useState } from 'react';
import { getAnalysisCandidate } from '@/apis/admin/pipeline';
import {
  Empty,
  ErrorBox,
  Loading,
  Note,
  Section,
  Table,
} from '@/components/admin/common/AdminUi';
import { BUTTON, LINK, TD, TH } from '@/components/admin/common/adminStyles';
import CandidateDecisionForm from '@/components/admin/pipeline/CandidateDecisionForm';
import {
  candidateGraphLabel,
  candidateStatusLabel,
  decisionLabel,
  relationLabel,
} from '@/components/admin/pipeline/candidateLabels';
import { useAsyncData } from '@/hooks/useAsyncData';
import type {
  CandidateDecisionResponse,
  CandidateDetail,
  CandidateRelation,
} from '@/types/admin/pipeline';
import { formatKst } from '@/util/format';

const reasonTitle = (detail: CandidateDetail) =>
  detail.status === 'HOLD'
    ? '보류 사유'
    : detail.status === 'REJECT'
      ? '폐기 사유'
      : '판정 사유';

// A-ADM-03 후보 상세 (FS067-02, getAnalysisCandidate)
// - 프로토타입 candidates.tsx의 CandidateDetail을 옮겼다. 원문 인용은 앱이 검증한 구간만 보이고, 검증에 실패하면 quote가 null이다.
// - 결정은 관계마다 승인·거부한다(decideAnalysisCandidate). 승인은 HOLD 후보의 아직 결정하지 않은 관계만,
//   거부는 폐기 판정이 아닌 후보의 아직 결정하지 않은 관계만 할 수 있다. 확정된 결정의 번복은 계약 범위 밖이다.
export default function CandidateDetailPanel({
  id,
  onClose,
  onDecided,
}: {
  id: string;
  onClose: () => void;
  /** 결정이 끝나면 목록의 판정·검수 열을 다시 읽게 한다. */
  onDecided?: () => void;
}) {
  const load = useCallback(() => getAnalysisCandidate(id), [id]);
  const detail = useAsyncData(load);
  const [target, setTarget] = useState<{
    relationId: string;
    decision: 'allow' | 'reject';
  } | null>(null);
  const [message, setMessage] = useState('');

  if (detail.status === 'loading')
    return <Loading>후보 상세를 불러오고 있어요</Loading>;
  if (detail.status === 'error')
    return (
      <ErrorBox
        title="후보 상세를 불러오지 못했어요"
        error={detail.error}
        onRetry={detail.reload}
      />
    );

  const c = detail.data;
  // graphDb를 읽지 못하면(unknown) 앱은 onUserGraph=false를 주므로, 비공개로 단정하지 않는다.
  const userGraphLabel = (onUserGraph: boolean) =>
    onUserGraph
      ? '표시 중'
      : c.graphDb === 'unknown'
        ? candidateGraphLabel.unknown
        : '표시 안 함';
  const canAllow = (relation: CandidateRelation) =>
    c.active &&
    c.status === 'HOLD' &&
    relation.decision === null &&
    relation.evidenceCount > 0;
  const canReject = (relation: CandidateRelation) =>
    c.active && c.status !== 'REJECT' && relation.decision === null;
  const decidable = c.relations.some(
    (relation) => canAllow(relation) || canReject(relation),
  );
  const targetRelation = target
    ? c.relations.find((relation) => relation.relationId === target.relationId)
    : undefined;
  function done(result: CandidateDecisionResponse) {
    setMessage(
      result.decision === 'approved'
        ? '관계를 승인했어요. 다음 그래프 버전을 만들 때 반영돼요.'
        : '관계를 거부했어요.',
    );
    setTarget(null);
    detail.reload();
    onDecided?.();
  }
  const articles = new Map(
    c.articles.map((article) => [article.articleId, article]),
  );

  return (
    <article aria-labelledby="candidate-title" className="flex flex-col gap-5">
      <div className="flex items-start gap-2">
        <h2 id="candidate-title" className="min-w-0 flex-1 text-sm font-bold">
          {c.title ?? '사건 없는 관계 후보'}
          <span className="mt-0.5 block font-inter text-[11px] font-normal break-all text-zoop-muted">
            {c.candidateId}
          </span>
        </h2>
        <button
          type="button"
          aria-label="후보 상세 닫기"
          onClick={onClose}
          className={BUTTON}
        >
          ×
        </button>
      </div>

      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-xs">
        <dt className="text-[11px] text-zoop-muted">판정</dt>
        <dd className="font-semibold">
          {candidateStatusLabel[c.status]}
          {!c.active && ' · 비활성'}
        </dd>
        <dt className="text-[11px] text-zoop-muted">사용자 그래프</dt>
        <dd>{userGraphLabel(c.onUserGraph)}</dd>
        <dt className="text-[11px] text-zoop-muted">GraphDB 반영</dt>
        <dd>{candidateGraphLabel[c.graphDb]}</dd>
        <dt className="text-[11px] text-zoop-muted">사건 시각</dt>
        <dd>{c.eventTime ? formatKst(c.eventTime) : '–'}</dd>
        <dt className="text-[11px] text-zoop-muted">관련 기업</dt>
        <dd>
          {c.companies.length
            ? c.companies
                .map((company) =>
                  company.role
                    ? `${company.name}(${company.role})`
                    : company.name,
                )
                .join(', ')
            : '–'}
        </dd>
        <dt className="text-[11px] text-zoop-muted">원천 버전</dt>
        <dd className="font-inter break-all">{c.sourceVersion}</dd>
      </dl>

      {c.reasons.length > 0 && (
        <Section title={reasonTitle(c)}>
          <ul className="flex list-disc flex-col gap-1 pl-4 text-xs leading-relaxed">
            {c.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </Section>
      )}
      {c.invalidationReason && <Note>비활성 사유: {c.invalidationReason}</Note>}

      {message && (
        <p role="status" className="text-xs font-semibold">
          {message}
        </p>
      )}
      {!c.active ? (
        <Note>비활성 후보는 결정할 수 없어요.</Note>
      ) : c.status === 'REJECT' ? (
        <Note>폐기 판정 후보는 결정할 수 없어요.</Note>
      ) : c.relations.length === 0 ? (
        <Note>결정할 관계가 없어요.</Note>
      ) : (
        decidable && (
          <Note>아래 연결 관계에서 관계마다 승인하거나 거부해요.</Note>
        )
      )}

      <Section title="원문 인용">
        {c.evidence.length === 0 ? (
          <Empty>원문 인용이 없어요.</Empty>
        ) : (
          <ul className="flex flex-col gap-3">
            {c.evidence.map((evidence) => {
              const article = articles.get(evidence.articleId);
              const url = evidence.url ?? article?.url ?? null;
              return (
                <li
                  key={`${evidence.articleId}:${evidence.articleVersion}:${evidence.start}:${evidence.end}`}
                  className="flex flex-col gap-1 rounded-2xl bg-zoop-soft px-4 py-3 text-xs"
                >
                  <span className="text-[11px] text-zoop-muted">
                    {[
                      article?.publisher,
                      article?.publishedAt && formatKst(article.publishedAt),
                    ]
                      .filter(Boolean)
                      .join(' · ') || '출처 정보 없음'}
                  </span>
                  <span className="font-semibold">
                    {evidence.articleTitle ??
                      article?.title ??
                      '제목 없는 기사'}
                  </span>
                  {evidence.quote === null ? (
                    <span className="text-zoop-muted">
                      인용 원문을 확인할 수 없어요.
                    </span>
                  ) : (
                    <blockquote className="border-l-2 border-zoop-line pl-3 leading-relaxed">
                      {evidence.quote}
                    </blockquote>
                  )}
                  {url && (
                    <a
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={LINK}
                    >
                      원문 기사 ↗
                    </a>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      {c.relations.length > 0 && (
        <Section title="연결 관계">
          <Table caption="연결 관계">
            <thead>
              <tr>
                <th className={TH}>관계</th>
                <th className={TH}>대상</th>
                <th className={`${TH} text-right`}>근거</th>
                <th className={TH}>사용자 그래프</th>
                <th className={TH}>검수</th>
              </tr>
            </thead>
            <tbody>
              {c.relations.map((relation) => (
                <tr key={relation.relationId}>
                  <td className={`${TD} whitespace-nowrap`}>
                    {relationLabel(relation.relationType)}
                    <span className="block font-inter text-[10px] break-all text-zoop-muted">
                      {relation.relationId} · 회차 {relation.revision}
                    </span>
                  </td>
                  <td className={TD}>
                    {relation.source} → {relation.target}
                  </td>
                  <td className={`${TD} text-right tabular-nums`}>
                    {relation.evidenceCount}
                  </td>
                  <td className={TD}>{userGraphLabel(relation.onUserGraph)}</td>
                  <td className={TD}>
                    {relation.decision ? (
                      decisionLabel[relation.decision.decision]
                    ) : (
                      <span className="flex flex-wrap gap-1.5">
                        <button
                          type="button"
                          className={BUTTON}
                          disabled={!canAllow(relation) || target !== null}
                          aria-label={`${relation.source} → ${relation.target} 관계 승인`}
                          onClick={() => {
                            setMessage('');
                            setTarget({
                              relationId: relation.relationId,
                              decision: 'allow',
                            });
                          }}
                        >
                          승인
                        </button>
                        <button
                          type="button"
                          className={BUTTON}
                          disabled={!canReject(relation) || target !== null}
                          aria-label={`${relation.source} → ${relation.target} 관계 거부`}
                          onClick={() => {
                            setMessage('');
                            setTarget({
                              relationId: relation.relationId,
                              decision: 'reject',
                            });
                          }}
                        >
                          거부
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
          {target && targetRelation && (
            <CandidateDecisionForm
              key={`${target.relationId}:${target.decision}`}
              candidateId={c.candidateId}
              relation={targetRelation}
              decision={target.decision}
              onCancel={() => setTarget(null)}
              onDone={done}
            />
          )}
        </Section>
      )}

      {c.verification && (
        <Section title="검증 판정">
          <Note>
            {[c.verification.provider, c.verification.model]
              .filter(Boolean)
              .join(' · ') || '검증 모델 정보 없음'}
          </Note>
          {c.verification.verdicts.length === 0 ? (
            <Empty>대상별 판정이 없어요.</Empty>
          ) : (
            <Table caption="검증 판정">
              <thead>
                <tr>
                  <th className={TH}>대상</th>
                  <th className={TH}>판정</th>
                  <th className={TH}>사유</th>
                </tr>
              </thead>
              <tbody>
                {c.verification.verdicts.map((verdict, index) => (
                  <tr key={`${verdict.target}:${index}`}>
                    <td className={TD}>{verdict.target}</td>
                    <td className={`${TD} whitespace-nowrap`}>
                      {verdict.decision}
                    </td>
                    <td className={TD}>{verdict.reason ?? '–'}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Section>
      )}

      <Section title="검수 이력">
        {c.history.length === 0 ? (
          <Empty>아직 검수 결정이 없어요.</Empty>
        ) : (
          <ul className="flex flex-col gap-2 text-xs">
            {c.history.map((item) => (
              <li key={item.id} className="flex flex-col gap-0.5">
                <span className="font-semibold">
                  {decisionLabel[item.decision]} · {item.adminEmail}
                </span>
                <span className="text-[11px] break-all text-zoop-muted">
                  {item.targetType === 'relation'
                    ? `관계 ${item.targetId}`
                    : item.targetType === 'candidate'
                      ? `후보 ${item.targetId}`
                      : `${item.targetType} ${item.targetId}`}{' '}
                  · 판정 회차 {item.revision}
                </span>
                <span className="text-[11px] text-zoop-muted">
                  {formatKst(item.decidedAt)}
                </span>
                <span className="leading-relaxed">{item.reason}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </article>
  );
}
