import { useEffect, useEffectEvent, useRef, useState } from 'react';
import { listGraphVersions } from '@/apis/admin/graphVersions';
import {
  Empty,
  ErrorBox,
  Loading,
  MoreButton,
  Note,
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
import GraphVersionForm from '@/components/admin/pipeline/GraphVersionForm';
import { useCursorPages } from '@/hooks/useCursorPages';
import {
  activationModeOf,
  type GraphDbVersionStatus,
  type GraphVersion,
  type GraphVersionActivation,
} from '@/types/admin/graphVersions';
import { formatKst } from '@/util/format';

const graphDbLabel: Record<GraphDbVersionStatus, string> = {
  reflected: '반영됨',
  pending: '반영 대기',
  unknown: '확인 불가',
};

/** A-ADM-03 출처: 칸보다 길면 '…'로 줄이고, 마우스를 올리면 툴팁으로, 누르면 펼쳐서 전체를 보여 준다. */
function SourceLabel({ label }: { label: string }) {
  const [open, setOpen] = useState(false);
  return (
    <button
      type="button"
      title={label}
      aria-expanded={open}
      onClick={() => setOpen((value) => !value)}
      className={`block w-full rounded text-left ${open ? 'break-all' : 'truncate'} ${FOCUS_RING}`}
    >
      {label}
    </button>
  );
}

/** 행 버튼 문구: 표시한 적 있는 버전은 되돌리기(rollback), 나머지는 전환(forward). */
function verbOf(version: GraphVersion) {
  return activationModeOf(version) === 'rollback' ? '되돌리기' : '전환';
}

const activationLabel: Record<GraphVersionActivation['action'], string> = {
  publish: '게시',
  activate: '전환',
  seed: '최초 등록',
};

// A-ADM-03 그래프 버전 탭 (FS059, listGraphVersions·activateGraphVersion)
// - 지금 사용자에게 보이는 버전, 버전 목록(최신 먼저), 전환 이력을 보여 준다.
// - 이미 있는 버전으로만 바꾼다. 표시한 적 없는 버전은 전환(forward), 표시했던 버전은 되돌리기(rollback).
// - 원장에서 새 버전 게시(publishGraphVersion)는 API가 아직 없다.
export default function GraphVersions({
  onActivated,
  refreshKey = 0,
}: {
  /** 표시 버전이 바뀌면 후보의 공개 표시 상태도 다시 읽게 알린다. */
  onActivated?: () => void;
  /** 회차 상세에서 버전 탭으로 올 때마다 바뀐다. 바뀌면 목록을 조용히 다시 읽는다(#55). */
  refreshKey?: number;
} = {}) {
  const versions = useCursorPages(listGraphVersions);
  const [target, setTarget] = useState<GraphVersion | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // 전환 요청이 진행 중인지. 진행 중에는 다른 버전을 고르거나 폼을 바꾸지 못하게 한다.
  const [pending, setPending] = useState(false);
  // 처음 연 뒤로 탭이 유지되므로, 회차가 수입한 새 버전을 보려면 다시 읽어야 한다.
  // 전환 중이거나 조회(처음 읽기·더 보기·다시 읽기)가 진행 중이면 조용한 다시 읽기를 할 수 없으므로,
  // 끝난 뒤(전환은 성공·실패와 관계없이)에 읽고 그때 처리한 것으로 기록한다.
  const seenRefreshKey = useRef(refreshKey);
  const refresh = useEffectEvent(() => {
    if (seenRefreshKey.current === refreshKey) return;
    if (
      pending ||
      versions.status === 'loading' ||
      versions.loadingMore ||
      versions.refreshing
    )
      return;
    seenRefreshKey.current = refreshKey;
    versions.reload({ quiet: true });
  });
  useEffect(() => {
    refresh();
  }, [
    refreshKey,
    pending,
    versions.status,
    versions.loadingMore,
    versions.refreshing,
  ]);
  const first = versions.pages[0];
  const activeVersionId = first?.activeVersionId ?? null;
  // 커서는 표시 버전을 고정하지 않는다. 더 불러온 쪽의 표시 버전이 첫 쪽과 다르면 목록이 섞인 것이므로
  // 다시 읽게 하고, 그때까지 새 전환을 막는다(열린 폼의 기대 버전은 몰래 바꾸지 않는다).
  const stale = versions.pages.some(
    (page) => page.activeVersionId !== activeVersionId,
  );

  if (versions.status === 'loading')
    return <Loading>그래프 버전을 불러오고 있어요</Loading>;
  if (versions.status === 'error' && versions.error)
    return (
      <ErrorBox
        title="그래프 버전을 불러오지 못했어요"
        error={versions.error}
        onRetry={versions.reload}
      />
    );

  return (
    <div className="flex min-w-0 max-w-full flex-col gap-6">
      <Section title="그래프 버전">
        <Note>
          사용자에게 보이는 버전:{' '}
          <strong className="font-num break-all text-zoop-ink">
            {activeVersionId ?? '없음'}
          </strong>
          . 이미 있는 버전으로만 바꿀 수 있고, 이전에 표시했던 버전은 되돌리기로
          바꿔요. 새 버전 게시는 아직 지원하지 않아요.
        </Note>
        {stale && (
          <div
            role="alert"
            className="flex flex-wrap items-center gap-3 rounded-2xl bg-zoop-soft px-4 py-3"
          >
            <p className="min-w-0 flex-1 text-caption">
              목록을 읽는 사이 표시 버전이 바뀌었어요. 다시 불러와서 확인해
              주세요.
            </p>
            <button
              type="button"
              disabled={pending}
              onClick={() => {
                setNotice(null);
                versions.reload();
              }}
              className={BUTTON}
            >
              다시 불러오기
            </button>
          </div>
        )}
        {notice && (
          <p role="status" className="text-caption font-semibold">
            {notice}
          </p>
        )}
        {target && (
          <GraphVersionForm
            key={target.id}
            // 폼이 열린 채 목록을 다시 읽으면 같은 버전의 최신 상태(표시 이력 → mode)를 쓴다.
            version={
              versions.items.find((item) => item.id === target.id) ?? target
            }
            activeVersionId={activeVersionId}
            stale={stale}
            onPendingChange={setPending}
            onCancel={() => setTarget(null)}
            onDone={(result, mode) => {
              setTarget(null);
              setNotice(
                result.idempotent
                  ? `${result.activeVersionId}는 이미 표시 중이에요.`
                  : mode === 'rollback'
                    ? `${result.activeVersionId}로 되돌렸어요.`
                    : `${result.activeVersionId}로 바꿨어요.`,
              );
              // 성공하면 여기서 목록을 처음부터 다시 읽으므로 기다리던 다시 읽기도 함께 처리된다.
              seenRefreshKey.current = refreshKey;
              versions.reload();
              if (!result.idempotent) onActivated?.();
            }}
          />
        )}
        {versions.items.length === 0 ? (
          <Empty>등록된 그래프 버전이 없어요.</Empty>
        ) : (
          <Table caption="그래프 버전 목록">
            <thead>
              <tr>
                <th className={TH}>버전</th>
                <th className={TH}>사용자 표시</th>
                <th className={TH}>만든 시각</th>
                <th className={TH}>출처</th>
                <th className={`${TH} text-right`}>이슈</th>
                <th className={`${TH} text-right`}>관계</th>
                <th className={`${TH} text-right`}>기사</th>
                <th className={TH}>GraphDB</th>
                <th className={TH}>사유</th>
                <th className={TH}>
                  <span className="sr-only">전환</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {versions.items.map((version) => (
                <tr
                  key={version.id}
                  className={
                    version.id === activeVersionId ? 'bg-zoop-soft' : undefined
                  }
                >
                  <td className={`${TD} font-num font-semibold break-all`}>
                    {version.id}
                    {version.kind === 'fixture' && (
                      <span className="ml-2 rounded-full bg-zoop-soft px-2 py-1 text-caption font-normal text-zoop-muted">
                        합성
                      </span>
                    )}
                  </td>
                  <td className={`${TD} whitespace-nowrap`}>
                    {version.id === activeVersionId ? (
                      <span className="font-semibold">표시 중</span>
                    ) : (
                      <span className="text-zoop-faint">–</span>
                    )}
                  </td>
                  <td
                    className={`${TD} whitespace-nowrap font-num tabular-nums`}
                  >
                    {formatKst(version.createdAt)}
                  </td>
                  <td className={`${TD} max-w-56 text-zoop-muted`}>
                    <SourceLabel label={version.sourceLabel} />
                  </td>
                  <td className={`${TD} text-right tabular-nums`}>
                    {count(version.issueCount)}
                  </td>
                  <td className={`${TD} text-right tabular-nums`}>
                    {count(version.relationCount)}
                  </td>
                  <td className={`${TD} text-right tabular-nums`}>
                    {count(version.articleCount)}
                  </td>
                  <td className={`${TD} whitespace-nowrap`}>
                    {graphDbLabel[version.graphDb.status]}
                  </td>
                  <td className={`${TD} max-w-56 text-zoop-muted`}>
                    {version.reason ?? '–'}
                  </td>
                  <td className={`${TD} text-right whitespace-nowrap`}>
                    {version.id !== activeVersionId && !stale && (
                      <button
                        type="button"
                        disabled={pending}
                        aria-label={`${version.id}로 ${verbOf(version)}`}
                        onClick={() => {
                          setNotice(null);
                          setTarget(version);
                        }}
                        className={BUTTON}
                      >
                        {verbOf(version)}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        {versions.hasMore && (
          <MoreButton
            loading={versions.loadingMore}
            error={versions.moreError}
            onClick={versions.loadMore}
          />
        )}
      </Section>

      <Section title="전환 이력">
        {!first || first.activations.length === 0 ? (
          <Empty>전환 이력이 없어요.</Empty>
        ) : (
          <Table caption="그래프 버전 전환 이력">
            <thead>
              <tr>
                <th className={TH}>시각</th>
                <th className={TH}>동작</th>
                <th className={TH}>버전</th>
                <th className={TH}>관리자</th>
                <th className={TH}>사유</th>
              </tr>
            </thead>
            <tbody>
              {first.activations.map((activation, index) => (
                <tr key={`${activation.versionId}-${activation.at}-${index}`}>
                  <td
                    className={`${TD} whitespace-nowrap font-num tabular-nums`}
                  >
                    {formatKst(activation.at)}
                  </td>
                  <td className={`${TD} whitespace-nowrap`}>
                    {activationLabel[activation.action] ?? activation.action}
                  </td>
                  <td
                    className={`${TD} font-num whitespace-nowrap tabular-nums`}
                  >
                    {activation.previousVersionId
                      ? `${activation.previousVersionId} → `
                      : ''}
                    {activation.versionId}
                  </td>
                  <td className={`${TD} text-zoop-muted`}>
                    {activation.adminEmail ?? '시스템'}
                  </td>
                  <td className={`${TD} max-w-96`}>
                    {activation.reason ?? '–'}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Section>
    </div>
  );
}
