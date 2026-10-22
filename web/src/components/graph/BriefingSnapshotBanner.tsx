import { useCallback } from 'react';
import { Link } from 'react-router-dom';
import { ApiError } from '@/apis/auth/ApiService';
import { getBriefingGraphBasis } from '@/apis/briefing/briefing';
import { useAsyncData } from '@/hooks/useAsyncData';
import { useRouteQuery } from '@/hooks/useRouteQuery';
import { briefingTime } from '@/util/briefingTime';

const FOCUS_RING =
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zoop-ink';
const BUTTON = `inline-flex h-8 items-center rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-paper px-3 text-xs font-semibold text-zoop-ink hover:bg-zoop-wash ${FOCUS_RING}`;
const PRIMARY = `inline-flex h-8 items-center rounded-[3px] bg-zoop-ink px-3 text-xs font-semibold text-zoop-paper ${FOCUS_RING}`;

const editionLabel = { morning: '출근', evening: '퇴근' } as const;

/** 회차 id(brf-2026-09-17-evening)에서 날짜·구분을 읽는다. 기준을 받기 전·실패 시 제목에 쓴다. */
function parseRoundId(roundId: string) {
  const match = roundId.match(/(\d{4}-\d{2}-\d{2})-(morning|evening)$/);
  return match
    ? { date: match[1], edition: match[2] as 'morning' | 'evening' }
    : null;
}

// D-BRF-04 회차 기준 지도 (FS032·FS035, getBriefingGraphBasis)
// - 지도가 브리핑 발행 당시 그래프를 보이고 있음을 밝히고, 현재 그래프·원래 브리핑으로 돌아갈 길을 둔다.
// - 회차가 제공 중단·미발행·사용 불가이면 그 안내를 보여 준다. 최신 그래프로 몰래 바꾸지 않는다.
export default function BriefingSnapshotBanner({
  roundId,
}: {
  roundId: string;
}) {
  const { updateQuery } = useRouteQuery();
  const load = useCallback(() => getBriefingGraphBasis(roundId), [roundId]);
  const basis = useAsyncData(load);
  const parsed = parseRoundId(roundId);
  const date = basis.data?.date ?? parsed?.date;
  const edition = basis.data?.edition ?? parsed?.edition;
  const title =
    date && edition
      ? `${date} ${editionLabel[edition]} 브리핑 기준 그래프${basis.data?.graphOrigin === 'reconstructed' ? ' · 재구성' : ''}`
      : '브리핑 회차 기준 그래프';
  const briefingHref =
    date && edition ? `/briefing?date=${date}&edition=${edition}` : '/briefing';
  const data = basis.data;

  let detail: string;
  if (basis.status === 'loading') detail = '회차 기준을 확인하고 있어요.';
  else if (basis.status === 'error')
    detail =
      basis.error instanceof ApiError && basis.error.status === 404
        ? '찾는 브리핑 회차가 없어요.'
        : '회차 기준을 확인하지 못했어요. 지도는 이 회차 기준으로만 보여 줘요.';
  else if (data && data.status !== 'available')
    detail = [data.message ?? '이 회차의 그래프를 볼 수 없어요.', data.reason]
      .filter(Boolean)
      .join(' · ');
  else
    detail = `${data?.graphOrigin === 'reconstructed' ? '저장된 발행 자료로 재구성' : '발행 당시의 관계·근거'} · 핵심 이슈 ${data?.keyIssueIds.length ?? 0}개 · 관련 기업 ${data?.companyIds.length ?? 0}개 · 데이터 기준 ${briefingTime(data?.dataAsOf ?? null)} · 버전 ${data?.graphVersion ?? '미확인'}${
      data?.correctionCount
        ? ` · 정정 ${data.correctionCount}건은 브리핑에서 확인`
        : ''
    }`;

  return (
    <section
      aria-label="브리핑 회차 기준 지도"
      className="mx-4 mt-3 flex flex-wrap items-center gap-3 rounded-[5px] border-[0.667px] border-zoop-line bg-zoop-wash px-4 py-3 text-zoop-ink"
    >
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-bold">{title}</p>
        <p
          role={
            basis.status === 'error' ||
            (data &&
              data.status !== 'available' &&
              data.unavailableReason !== 'snapshot_not_recorded')
              ? 'alert'
              : 'status'
          }
          className="mt-0.5 text-[11px] break-words text-zoop-muted"
        >
          {detail}
        </p>
        {data?.graphOrigin === 'reconstructed' && (
          <p className="mt-1 text-[11px] text-zoop-muted">
            {data.message} 재구성 시각{' '}
            {briefingTime(data.reconstructedAt ?? null)}
          </p>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {basis.status === 'error' && (
          <button type="button" onClick={basis.reload} className={BUTTON}>
            다시 확인
          </button>
        )}
        <button
          type="button"
          onClick={() =>
            updateQuery({
              round: null,
              asOf: null,
              graphVersion: null,
              companyId: null,
              select: null,
              impact: null,
              event: null,
              focus: null,
              hops: null,
              path: null,
              depth: null,
            })
          }
          className={BUTTON}
        >
          현재 그래프로 보기
        </button>
        <Link to={briefingHref} className={PRIMARY}>
          브리핑으로
        </Link>
      </div>
    </section>
  );
}
