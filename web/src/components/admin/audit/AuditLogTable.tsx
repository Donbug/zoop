import { useCallback, useState } from 'react';
import { listAuditRecords } from '@/apis/admin/members';
import {
  Empty,
  ErrorBox,
  Loading,
  MoreButton,
  PageHeader,
  Table,
} from '@/components/admin/common/AdminUi';
import {
  SEARCH_INPUT,
  SELECT,
  TD,
  TH,
} from '@/components/admin/common/adminStyles';
import { auditActionLabel, auditOutcomeLabel } from '@/constants/adminLabels';
import { useCursorPages } from '@/hooks/useCursorPages';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import { formatKst } from '@/util/format';

// A-ADM-05b 관리자 감사 로그 (FS073·NFS008, listAuditRecords)
// - 로그인·검수·게시·작업·브리핑 운영·회원 조치 기록(최신 먼저). 동작 종류와 검색어는 주소에 남는다.
// - 기록을 만들거나 고치지 않고 조회만 한다.
export default function AuditLogTable() {
  const { params, updateQuery } = useRouteQuery();
  const action = params.get('action');
  const urlQ = params.get('q') ?? '';
  const [text, setText] = useState(urlQ);
  // 뒤로·앞으로 가기로 주소의 검색어가 바뀌면 입력칸도 맞춘다.
  const [seenQ, setSeenQ] = useState(urlQ);
  if (urlQ !== seenQ) {
    setSeenQ(urlQ);
    if (urlQ !== text.trim()) setText(urlQ);
  }
  const q = useDebouncedValue(text.trim(), 300);
  const load = useCallback(
    (cursor?: string) => listAuditRecords(action, q, cursor),
    [action, q],
  );
  const audit = useCursorPages(load);

  return (
    <div className="flex flex-col gap-5 py-8 text-zoop-ink">
      <PageHeader title="감사 로그" />
      <div className="flex flex-wrap items-center gap-3">
        <select
          aria-label="동작"
          value={action ?? ''}
          onChange={(event) =>
            updateQuery(
              { action: event.target.value || null },
              { replace: true },
            )
          }
          className={`${SELECT} max-w-56`}
        >
          <option value="">모든 동작</option>
          {Object.entries(auditActionLabel).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <input
          type="search"
          aria-label="감사 로그 검색"
          placeholder="대상·사유·관리자로 찾기"
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            updateQuery(
              { q: event.target.value.trim() || null },
              { replace: true },
            );
          }}
          className={SEARCH_INPUT}
        />
      </div>
      {audit.status === 'loading' && (
        <Loading>감사 로그를 불러오고 있어요</Loading>
      )}
      {audit.status === 'error' && audit.error && (
        <ErrorBox
          title="감사 로그를 불러오지 못했어요"
          error={audit.error}
          onRetry={audit.reload}
        />
      )}
      {audit.status === 'success' && audit.items.length === 0 && (
        <Empty>조건에 맞는 기록이 없어요.</Empty>
      )}
      {audit.items.length > 0 && (
        <Table caption="감사 로그">
          <thead>
            <tr>
              <th className={TH}>시각</th>
              <th className={TH}>주체</th>
              <th className={TH}>동작</th>
              <th className={TH}>대상</th>
              <th className={TH}>결과</th>
              <th className={TH}>사유</th>
            </tr>
          </thead>
          <tbody>
            {audit.items.map((row) => (
              <tr key={row.id}>
                <td
                  className={`${TD} whitespace-nowrap font-inter tabular-nums`}
                >
                  {formatKst(row.at)}
                </td>
                <td className={`${TD} text-zoop-muted`}>
                  {row.actorKind === 'system'
                    ? '시스템'
                    : (row.actorEmail ?? row.actorId)}
                </td>
                <td className={`${TD} whitespace-nowrap`}>
                  {auditActionLabel[row.action] ?? row.action}
                </td>
                <td
                  className={`${TD} max-w-72 break-all font-inter text-zoop-muted`}
                >
                  {row.targetType}
                  {row.targetId ? ` · ${row.targetId}` : ''}
                </td>
                <td
                  className={`${TD} whitespace-nowrap font-semibold ${
                    row.outcome === 'ok' ? '' : 'text-zoop-alert'
                  }`}
                >
                  {auditOutcomeLabel[row.outcome]}
                </td>
                <td className={`${TD} max-w-96`}>{row.reason ?? '–'}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {audit.hasMore && (
        <MoreButton
          loading={audit.loadingMore}
          error={audit.moreError}
          onClick={audit.loadMore}
        />
      )}
    </div>
  );
}
