import { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { listMembers } from '@/apis/admin/members';
import {
  Empty,
  ErrorBox,
  Loading,
  MoreButton,
  Note,
  PageHeader,
  Segmented,
  Table,
} from '@/components/admin/common/AdminUi';
import {
  LINK,
  SEARCH_INPUT,
  TD,
  TH,
  count,
} from '@/components/admin/common/adminStyles';
import { memberStatusLabel, signupMethodLabel } from '@/constants/adminLabels';
import { useCursorPages } from '@/hooks/useCursorPages';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import type { MemberFilter } from '@/types/admin/members';
import { formatKst } from '@/util/format';

const FILTERS: { value: MemberFilter; label: string }[] = [
  { value: 'all', label: '전체' },
  { value: 'active', label: '정상' },
  { value: 'blocked', label: '차단됨' },
];

const parseFilter = (value: string | null): MemberFilter =>
  value === 'active' || value === 'blocked' ? value : 'all';

const NUM = `${TD} text-right tabular-nums`;

// A-ADM-05 회원·접근 관리 (FS069-01)
// - 가명 id·가린 이메일·가입 방식·활동 요약·상태. 실명과 이메일 원문은 서버가 내보내지 않는다.
// - 상태 필터와 검색어는 주소에 남는다. 검색은 입력을 멈춘 뒤 한 번만 요청한다.
export default function MemberManagement() {
  const { params, updateQuery } = useRouteQuery();
  const filter = parseFilter(params.get('status'));
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
    (cursor?: string) => listMembers(filter, q, cursor),
    [filter, q],
  );
  const members = useCursorPages(load);
  const counts = members.pages[0]?.counts;

  return (
    <div className="flex flex-col gap-5 py-8 text-zoop-ink">
      <PageHeader title="회원 관리" />
      <div className="flex flex-wrap items-center gap-3">
        <Segmented
          label="회원 상태"
          value={filter}
          options={FILTERS}
          onChange={(value) =>
            updateQuery(
              { status: value === 'all' ? null : value },
              { replace: true },
            )
          }
        />
        <input
          type="search"
          aria-label="회원 검색"
          placeholder="가명 id·가린 이메일로 찾기"
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
        {counts && (
          <Note>
            전체 {count(counts.all)}명 · 정상 {count(counts.active)} · 차단{' '}
            {count(counts.blocked)}
          </Note>
        )}
      </div>
      {members.status === 'loading' && (
        <Loading>회원을 불러오고 있어요</Loading>
      )}
      {members.status === 'error' && members.error && (
        <ErrorBox
          title="회원을 불러오지 못했어요"
          error={members.error}
          onRetry={members.reload}
        />
      )}
      {members.status === 'success' && members.items.length === 0 && (
        <Empty>조건에 맞는 회원이 없어요.</Empty>
      )}
      {members.items.length > 0 && (
        <Table caption="회원 목록">
          <thead>
            <tr>
              <th className={TH}>회원(가명 id)</th>
              <th className={TH}>이메일(가림)</th>
              <th className={TH}>가입 방식</th>
              <th className={TH}>가입</th>
              <th className={TH}>최근 활동</th>
              <th className={`${TH} text-right`}>로그인 세션</th>
              <th className={`${TH} text-right`}>그래프 선택</th>
              <th className={`${TH} text-right`}>AI 질문</th>
              <th className={`${TH} text-right`}>브리핑 조회</th>
              <th className={TH}>상태</th>
            </tr>
          </thead>
          <tbody>
            {members.items.map((row) => (
              <tr key={row.id}>
                <td className={`${TD} whitespace-nowrap font-inter`}>
                  <Link
                    to={`/admin/members/${encodeURIComponent(row.id)}`}
                    className={LINK}
                  >
                    {row.id}
                  </Link>
                </td>
                <td className={`${TD} whitespace-nowrap text-zoop-muted`}>
                  {row.emailMasked}
                </td>
                <td className={`${TD} whitespace-nowrap`}>
                  {signupMethodLabel(row.signupMethod)}
                </td>
                <td
                  className={`${TD} whitespace-nowrap font-inter tabular-nums`}
                >
                  {formatKst(row.createdAt)}
                </td>
                <td
                  className={`${TD} whitespace-nowrap font-inter tabular-nums`}
                >
                  {row.lastActiveAt ? formatKst(row.lastActiveAt) : '–'}
                </td>
                <td className={NUM}>{count(row.activity.sessions)}</td>
                <td className={NUM}>{count(row.activity.graphSelections)}</td>
                <td className={NUM}>{count(row.activity.aiQuestions)}</td>
                <td className={NUM}>{count(row.activity.briefingViews)}</td>
                <td
                  className={`${TD} whitespace-nowrap font-semibold ${
                    row.status === 'blocked' ? 'text-zoop-alert' : ''
                  }`}
                >
                  {memberStatusLabel[row.status]}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {members.hasMore && (
        <MoreButton
          loading={members.loadingMore}
          error={members.moreError}
          onClick={members.loadMore}
        />
      )}
    </div>
  );
}
