import { Link } from 'react-router-dom';
import type { GraphResponse } from '@/types/map/graph';
import type { PersonalScope } from '@/types/map';

// D-GRP-01/01b: only interpret the empty reasons described by getGraph.
export default function MapEmptyState({
  graph,
  onPersonalFilter,
  onMarket,
}: {
  graph: GraphResponse;
  onPersonalFilter?: (scope: PersonalScope) => void;
  onMarket?: () => void;
}) {
  const {
    mode,
    personalFilter,
    emptyReason,
    partial,
    truncated,
    focusCompanyIds,
  } = graph.metadata;
  const noNodes = graph.nodes.length === 0;
  const noRelations = graph.edges.length === 0;
  if (!noNodes && !noRelations) return null;
  const uncertain = partial || truncated;
  const personal = mode === 'personal';
  const names = graph.nodes
    .filter(
      (node) =>
        node.kind === 'company' &&
        (focusCompanyIds.includes(node.id) || node.isFocus),
    )
    .map((node) => node.label);
  const label =
    personalFilter === 'holdings'
      ? '보유'
      : personalFilter === 'watchlist'
        ? '관심'
        : '내';
  let message = noNodes
    ? '현재 표시할 수 있는 관계 데이터가 없습니다.'
    : '현재 지도에 표시된 연결선이 없어요.';
  if (uncertain)
    message = '일부 자료가 누락되어 관계 상태를 확인하지 못했어요.';
  else if (personal && emptyReason === 'no_personal_stocks')
    message =
      personalFilter === 'holdings'
        ? '보유 종목이 없어요.'
        : personalFilter === 'watchlist'
          ? '관심 종목이 없어요.'
          : '보유·관심 종목이 없어요.';
  else if (emptyReason === 'no_related_issues')
    message = personal
      ? `${label} 종목과 연결된 사건이 아직 없어요.`
      : '선택한 기업과 연결된 공개 관계가 없어요.';
  else if (emptyReason === 'no_approved_issues')
    message = '현재 표시할 수 있는 공개 관계가 없어요.';
  return (
    <div
      className={
        noNodes ? 'relationship-message' : 'relationship-empty-relations'
      }
      role="status"
    >
      <p>{message}</p>
      {!uncertain &&
        emptyReason === 'no_related_issues' &&
        names.length > 0 && (
          <p>
            {names.slice(0, 3).join(', ')}
            {names.length > 3 ? ` 외 ${names.length - 3}곳` : ''}에 연결된 공개
            관계가 없어요.
          </p>
        )}
      {!uncertain && personal && emptyReason === 'no_personal_stocks' && (
        <>
          {(personalFilter === 'holdings' || personalFilter === 'all') && (
            <Link to="/my">가상 계좌 연결하기</Link>
          )}
          {(personalFilter === 'watchlist' ||
            personalFilter === 'all' ||
            personalFilter === null) && <Link to="/my">관심 종목 고르기</Link>}
        </>
      )}
      {personal && onPersonalFilter && (
        <span className="flex flex-wrap gap-3">
          {personalFilter !== 'watchlist' && (
            <button type="button" onClick={() => onPersonalFilter('watchlist')}>
              관심으로 보기
            </button>
          )}
          {personalFilter !== 'holdings' && (
            <button type="button" onClick={() => onPersonalFilter('holdings')}>
              보유로 보기
            </button>
          )}
          {personalFilter !== 'all' && (
            <button type="button" onClick={() => onPersonalFilter('all')}>
              전체로 보기
            </button>
          )}
        </span>
      )}
      {personal && onMarket && (
        <button type="button" onClick={onMarket}>
          시장 전체 지도 보기
        </button>
      )}
    </div>
  );
}
