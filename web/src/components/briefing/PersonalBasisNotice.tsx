import { Link, useLocation } from 'react-router-dom';
import LoadingIndicator from '@/components/common/LoadingIndicator';
import { ApiError } from '@/apis/auth/ApiService';
import type { PersonalBriefingState } from '@/hooks/usePersonalBriefing';
import { briefingTime } from '@/util/briefingTime';
import { EMPTY, FOCUS_RING } from './briefingStyles';

const LINK = `font-semibold text-zoop-ink underline underline-offset-4 ${FOCUS_RING}`;

/** 이름 목록은 앞의 3개만 적고 나머지는 개수로 */
function names(list: string[]) {
  const head = list.slice(0, 3).join(', ');
  return list.length > 3 ? `${head} 외 ${list.length - 3}곳` : head;
}

// FS036 개인화 기준 안내. 어떤 종목과 기준 시점으로 작성된 결과인지 밝히고,
// 기준 종목이 없으면 종목 설정이나 공통 브리핑을 안내한다. 비회원은 로그인을 안내한다.
export default function PersonalBasisNotice({
  member,
  checking = false,
  state,
  dataAsOf,
  onRetry,
}: {
  member: boolean;
  checking?: boolean;
  state: PersonalBriefingState;
  dataAsOf: string | null;
  onRetry: () => void;
}) {
  const location = useLocation();
  if (checking)
    return (
      <LoadingIndicator
        label="로그인 상태를 확인하고 있어요."
        className="mt-4 flex min-h-8 w-full text-caption text-zoop-muted"
      />
    );
  if (!member)
    return (
      <p className={`${EMPTY} mt-4`}>
        내 종목 기준 브리핑은 로그인한 회원만 볼 수 있어요.{' '}
        <Link
          to="/login"
          state={{ from: `${location.pathname}${location.search}` }}
          className={LINK}
        >
          로그인하기
        </Link>
      </p>
    );

  if (state.status === 'idle' || state.status === 'loading')
    return (
      <LoadingIndicator
        label="내 종목 기준을 확인하고 있어요."
        className="mt-4 flex min-h-8 w-full text-caption text-zoop-muted"
      />
    );

  if (state.status === 'error')
    return (
      <div
        role="alert"
        className={`${EMPTY} mt-4 flex flex-wrap items-center gap-2`}
      >
        <span>
          {state.error instanceof ApiError && state.error.status === 409
            ? '이 회차의 그래프 버전을 쓸 수 없어 내 종목 기준 결과를 만들지 못했어요.'
            : '내 종목 기준 결과를 불러오지 못했어요. 아래는 공통 브리핑이에요.'}
        </span>
        <button type="button" onClick={onRetry} className={LINK}>
          다시 시도
        </button>
      </div>
    );

  const { basis } = state;
  if (basis.kind === 'none')
    return (
      <p className={`${EMPTY} mt-4`}>
        보유 종목과 관심 종목이 없어 내 종목 기준으로 볼 수 없어요.{' '}
        <Link to="/my" className={LINK}>
          내 종목 설정하기
        </Link>{' '}
        또는 공통 브리핑을 확인해 주세요.
      </p>
    );

  return (
    <p
      role="status"
      className="mt-4 rounded-md border border-zoop-ink bg-zoop-surface px-3 py-2 text-caption leading-relaxed"
    >
      <strong className="font-semibold">
        {basis.kind === 'holdings'
          ? `보유 종목 기준 · ${names(basis.names)}`
          : `관심 종목 ${basis.count}개 기준`}
      </strong>{' '}
      {basis.kind === 'watchlist' && <span> · {names(basis.names)}</span>}
      {basis.kind === 'holdings' && (
        <span>
          {' '}
          · 조회한 모의 보유 비중{' '}
          {basis.names
            .map(
              (name, i) =>
                `${name} ${basis.weights[i] === null ? '미제공' : `${(basis.weights[i]! * 100).toFixed(1)}%`}`,
            )
            .join(', ')}{' '}
          · 비중 기준 {briefingTime(basis.valuationAt)}
          {basis.weightNote && ` (${basis.weightNote})`}
        </span>
      )}
      · 기준 시점 {briefingTime(dataAsOf)} · 같은 발행본에서 내 종목과 겹치는
      이슈에 표시했어요.
    </p>
  );
}
