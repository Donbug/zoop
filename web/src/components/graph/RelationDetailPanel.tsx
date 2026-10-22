import { useEffect, useRef, useState } from 'react';
import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import CompanyLogo from '@/components/common/CompanyLogo';
import { useRelationData } from '@/hooks/useRelationData';
import type { EventContext } from '@/types/map/event';
import type { RelationDetail } from '@/types/map/relation';
import { formatEventTime, formatPublishedAt } from './event-format';
import GraphIcon from './GraphIcon';

interface Props {
  id: string;
  context: EventContext;
  /** 지도에 있는 기업 노드의 로고 */
  logoOf?: (companyId: string) => string | null | undefined;
  onClose: () => void;
  onSelectNode: (id: string) => void;
  onAction: (
    action: 'evidence' | 'ai',
    relation: RelationDetail,
    issueId?: string,
  ) => void;
}

// D-GRP-04 · Figma 619:7557 · WBS 6.6.24 · FS023/024/055.
export default function RelationDetailPanel({
  id,
  context,
  logoOf,
  onClose,
  onSelectNode,
  onAction,
}: Props) {
  const [retry, setRetry] = useState(0);
  const [notice, setNotice] = useState('');
  const { data, loading, error, retryable } = useRelationData(
    id,
    context,
    retry,
  );
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [id]);
  const shared = data?.relationType === 'SHARES_ISSUE';
  const count = new Set(data?.evidenceIds).size;
  const verifiedAt = data?.basis
    .map((basis) => basis.verifiedAt)
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1);
  return (
    <aside
      className={`relation-panel ${ui.shell}`}
      data-screen-id="D-GRP-04"
      aria-labelledby="relation-title"
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.stopPropagation();
          onClose();
        }
      }}
    >
      <header className={ui.header}>
        <div className="flex items-start justify-between gap-3">
          <h2
            id="relation-title"
            ref={heading}
            tabIndex={-1}
            className={ui.title}
          >
            {data
              ? `${data.source.label} – ${data.target.label}`
              : '연결선 상세'}
          </h2>
          <button className={ui.close} onClick={onClose} aria-label="상세 닫기">
            ×
          </button>
        </div>
        {data && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            <span className={ui.badge}>{data.summary}</span>
            <span className={ui.badge}>
              {data.relationType === 'INVOLVES' && !data.role
                ? '역할 미확인'
                : {
                    SHARES_ISSUE: '사건 공유',
                    FOLLOWS: '후속 관계',
                    INVOLVES: '직접 관련',
                    STRUCTURALLY_RELATED_TO: '구조적 관련',
                  }[data.relationType]}
            </span>
          </div>
        )}
      </header>
      <div className={ui.scroll} aria-busy={loading}>
        {loading && (
          <div role="status" className={ui.state}>
            연결선 정보를 불러오는 중입니다.
          </div>
        )}
        {error && (
          <div role="alert" className={ui.state}>
            <strong>연결선을 불러오지 못했습니다.</strong>
            <p>{error}</p>
            <p>지도는 그대로 유지됩니다.</p>
            {retryable && (
              <button onClick={() => setRetry((value) => value + 1)}>
                다시 시도
              </button>
            )}
          </div>
        )}
        {data && (
          <>
            <section className={ui.section} aria-label="관계 정보">
              <p>{data.explanation}</p>
              <dl className="mt-3 grid grid-cols-[64px_1fr] gap-x-2 gap-y-2">
                <dt className={ui.muted}>방향</dt>
                <dd>
                  {data.directed
                    ? `${data.source.label} → ${data.target.label}`
                    : '방향 없음'}
                </dd>
                <dt className={ui.muted}>
                  {shared ? '공유 사건' : '연결 사건'}
                </dt>
                <dd>{data.via.length}건</dd>
                <dt className={ui.muted}>확인 시점</dt>
                <dd>
                  {formatPublishedAt(verifiedAt ?? null) ?? '확인 시점 미제공'}
                </dd>
                <dt className={ui.muted}>검증 상태</dt>
                <dd>{data.verification.note ?? data.verification.status}</dd>
              </dl>
            </section>
            <div className={ui.actions}>
              <button
                disabled={!count}
                onClick={() => onAction('evidence', data)}
              >
                <GraphIcon name="briefing" size={14} />
                근거 {count}건 보기
              </button>
              <button
                onClick={() => {
                  onAction('ai', data);
                  setNotice(
                    '이 연결선을 질문 대상으로 연결했습니다. AI 대화는 준비 중입니다.',
                  );
                }}
              >
                <GraphIcon name="ai" size={14} />
                AI에게 묻기
              </button>
            </div>
            {notice && (
              <p role="status" className={ui.state}>
                {notice}
              </p>
            )}
            <section className={ui.section}>
              <h3>연결된 두 대상</h3>
              <ul className={ui.list}>
                {[data.source, data.target].map((node) => (
                  <li key={node.id}>
                    <button
                      onClick={() => onSelectNode(node.id)}
                      className="flex w-full items-center gap-2 text-left"
                    >
                      <CompanyLogo
                        name={node.label}
                        logoUrl={
                          node.kind === 'company' ? logoOf?.(node.id) : null
                        }
                        className={ui.avatar}
                      />
                      <span>
                        <span className={ui.muted}>
                          {node.kind === 'company' ? '기업' : '사건'}
                        </span>
                        <strong className={`block ${ui.itemTitle}`}>
                          {node.label}
                        </strong>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
            <section className={ui.section}>
              <h3>
                {shared ? '함께 언급된 사건' : '연결된 사건'} {data.via.length}
                건
              </h3>
              {!data.via.length && (
                <p className={ui.muted}>
                  {shared ? '공유 사건이 없습니다.' : '연결된 사건이 없습니다.'}
                </p>
              )}
              <ul className={ui.list}>
                {data.via.map((issue) => (
                  <li key={issue.id}>
                    <p className={ui.muted}>
                      {formatEventTime(issue.eventTime, issue.timePrecision)}
                    </p>
                    <button
                      className={`my-1 block w-full text-left ${ui.itemTitle}`}
                      onClick={() => onSelectNode(issue.id)}
                    >
                      {issue.title}
                    </button>
                    <button
                      className={ui.button}
                      disabled={!issue.evidenceIds.length}
                      onClick={() => onAction('evidence', data, issue.id)}
                    >
                      근거 {new Set(issue.evidenceIds).size}건 보기
                    </button>
                  </li>
                ))}
              </ul>
              {!count && (
                <p className={`mt-2 ${ui.muted}`}>
                  연결된 근거가 없습니다. 근거를 추정해 표시하지 않습니다.
                </p>
              )}
            </section>
            <footer className={ui.footer}>
              <p>{data.metadata.source}</p>
              <p>조회 기준 · {formatPublishedAt(data.metadata.asOf)}</p>
            </footer>
          </>
        )}
      </div>
    </aside>
  );
}
