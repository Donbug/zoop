import { useCallback, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getMemberActivity } from '@/apis/admin/members';
import { ApiError } from '@/apis/auth/ApiService';
import {
  Empty,
  ErrorBox,
  Loading,
  Metric,
  PageHeader,
  Section,
  Table,
} from '@/components/admin/common/AdminUi';
import {
  BUTTON,
  FOCUS_RING,
  TD,
  TH,
  count,
} from '@/components/admin/common/adminStyles';
import MemberStatusForm from '@/components/admin/members/MemberStatusForm';
import { memberStatusLabel, signupMethodLabel } from '@/constants/adminLabels';
import { useAsyncData } from '@/hooks/useAsyncData';
import { formatKst } from '@/util/format';

const actionLabel = {
  'member.block': '차단',
  'member.unblock': '차단 해제',
} as const;

// A-ADM-05 회원 상세 (FS069-01·02, getMemberActivity·blockMember·unblockMember)
// - 활동 통계만 보여 준다. 조회만으로 상태를 바꾸지 않고, 대화·개인화 결과 원문은 열지 않는다.
// - 차단·해제는 사유를 받고, 끝나면 서버가 돌려준 최신 상세로 바꾼다.
export default function AdminMemberDetailPage() {
  const { memberId = '' } = useParams();
  // 다른 회원으로 옮기면 열어 둔 입력과 처리 결과 안내를 비운다.
  return <MemberDetail key={memberId} memberId={memberId} />;
}

function MemberDetail({ memberId }: { memberId: string }) {
  const load = useCallback(() => getMemberActivity(memberId), [memberId]);
  const detail = useAsyncData(load);
  const [editing, setEditing] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const data = detail.data;
  const row = data?.member;
  const notFound =
    detail.status === 'error' &&
    detail.error instanceof ApiError &&
    detail.error.status === 404;

  return (
    <div
      className="flex flex-col gap-5 py-8 text-zoop-ink"
      data-screen-id="A-ADM-05"
    >
      <Link
        to="/admin/members"
        className={`self-start text-[11px] text-zoop-muted hover:text-zoop-ink ${FOCUS_RING}`}
      >
        ← 회원 목록
      </Link>
      <PageHeader
        title={row ? `회원 ${row.id}` : '회원 상세'}
        actions={
          row &&
          !editing && (
            <button
              type="button"
              onClick={() => {
                setDone(null);
                setEditing(true);
              }}
              className={BUTTON}
            >
              {row.status === 'active' ? '차단' : '차단 해제'}
            </button>
          )
        }
      />
      {done && (
        <p role="status" className="text-[11px] font-semibold">
          {done}
        </p>
      )}
      {detail.status === 'loading' && (
        <Loading>회원 정보를 불러오고 있어요</Loading>
      )}
      {notFound && <Empty>찾는 회원이 없어요.</Empty>}
      {detail.status === 'error' && !notFound && (
        <ErrorBox
          title="회원 정보를 불러오지 못했어요"
          error={detail.error}
          onRetry={detail.reload}
        />
      )}
      {data && row && (
        <>
          {editing && (
            <MemberStatusForm
              member={row}
              onCancel={() => setEditing(false)}
              onDone={(result) => {
                setEditing(false);
                detail.setData(result.detail);
                setDone(
                  !result.changed
                    ? '이미 같은 상태예요.'
                    : result.detail.member.status === 'blocked'
                      ? `${row.id}을 차단했어요.`
                      : `${row.id}의 차단을 풀었어요.`,
                );
              }}
            />
          )}
          <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
            <span
              className={`font-semibold ${row.status === 'blocked' ? 'text-zoop-alert' : ''}`}
            >
              {memberStatusLabel[row.status]}
            </span>
            <span className="text-zoop-muted">{row.emailMasked}</span>
          </p>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-5 border-y-[0.667px] border-zoop-line py-5 md:grid-cols-4">
            <Metric
              label="가입 방식"
              value={signupMethodLabel(row.signupMethod)}
            />
            <Metric label="가입" value={formatKst(row.createdAt)} />
            <Metric
              label="최근 활동"
              value={row.lastActiveAt ? formatKst(row.lastActiveAt) : '–'}
              detail="1분 단위로 기록돼요"
            />
            <Metric
              label="로그인 세션(누적)"
              value={`${count(row.activity.sessions)}회`}
            />
            <Metric
              label="그래프 선택"
              value={`${count(row.activity.graphSelections)}회`}
              detail="노드·간선"
            />
            <Metric
              label="AI 질문"
              value={`${count(row.activity.aiQuestions)}회`}
            />
            <Metric
              label="브리핑 조회"
              value={`${count(row.activity.briefingViews)}회`}
            />
            <Metric
              label="평가"
              value={`${count(data.feedbackUp)} / ${count(data.feedbackDown)}`}
              detail="좋아요 / 싫어요"
            />
            <Metric
              label="초기 설정"
              value={data.onboardingCompleted ? '완료' : '미완료'}
            />
            <Metric
              label="튜토리얼"
              value={data.tutorialCompleted ? '완료' : '미완료'}
            />
            <Metric
              label="관심 종목"
              value={`${count(data.watchlistCount)}개`}
              detail="종목 이름은 보이지 않아요"
            />
            <Metric
              label="가상 보유 종목"
              value={`${count(data.holdingCount)}개`}
              detail={
                data.accountConnected ? '가상 계좌 연결됨' : '가상 계좌 없음'
              }
            />
          </dl>
          <Section title="차단·해제 이력">
            {data.history.length === 0 ? (
              <Empty>차단하거나 해제한 기록이 없어요.</Empty>
            ) : (
              <Table caption="차단·해제 이력">
                <thead>
                  <tr>
                    <th className={TH}>시각</th>
                    <th className={TH}>조치</th>
                    <th className={TH}>사유</th>
                    <th className={TH}>관리자</th>
                  </tr>
                </thead>
                <tbody>
                  {data.history.map((entry, index) => (
                    <tr key={`${entry.at}-${index}`}>
                      <td
                        className={`${TD} whitespace-nowrap font-inter tabular-nums`}
                      >
                        {formatKst(entry.at)}
                      </td>
                      <td className={`${TD} whitespace-nowrap`}>
                        {actionLabel[entry.action]}
                      </td>
                      <td className={`${TD} max-w-96`}>
                        {entry.reason ?? '–'}
                      </td>
                      <td className={`${TD} text-zoop-muted`}>
                        {entry.adminEmail ?? '–'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Section>
        </>
      )}
    </div>
  );
}
