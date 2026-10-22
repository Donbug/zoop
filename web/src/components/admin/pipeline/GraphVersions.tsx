import { useState } from 'react';
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
import { BUTTON, TD, TH, count } from '@/components/admin/common/adminStyles';
import GraphVersionForm from '@/components/admin/pipeline/GraphVersionForm';
import { useCursorPages } from '@/hooks/useCursorPages';
import type {
  GraphDbVersionStatus,
  GraphVersion,
  GraphVersionActivation,
} from '@/types/admin/graphVersions';
import { formatKst } from '@/util/format';

const graphDbLabel: Record<GraphDbVersionStatus, string> = {
  reflected: '반영됨',
  pending: '반영 대기',
  unknown: '확인 불가',
};

const activationLabel: Record<GraphVersionActivation['action'], string> = {
  publish: '게시',
  activate: '전환',
  seed: '최초 등록',
};

// A-ADM-03 그래프 버전 탭 (FS059, listGraphVersions·activateGraphVersion)
// - 지금 사용자에게 보이는 버전, 버전 목록(최신 먼저), 전환 이력을 보여 준다.
// - 이미 있는 버전으로만 바꾼다. 원장에서 새 버전 게시(publishGraphVersion)는 API가 아직 없다.
export default function GraphVersions() {
  const versions = useCursorPages(listGraphVersions);
  const [target, setTarget] = useState<GraphVersion | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // 전환 요청이 진행 중인지. 진행 중에는 다른 버전을 고르거나 폼을 바꾸지 못하게 한다.
  const [pending, setPending] = useState(false);
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
    <div className="flex flex-col gap-6">
      <Section title="그래프 버전">
        <Note>
          사용자에게 보이는 버전:{' '}
          <strong className="font-inter text-zoop-ink">
            {activeVersionId ?? '없음'}
          </strong>
          . 이미 있는 버전으로만 바꿀 수 있어요. 새 버전 게시는 아직 지원하지
          않아요.
        </Note>
        {stale && (
          <div
            role="alert"
            className="flex flex-wrap items-center gap-3 rounded-[3px] border-[0.667px] border-zoop-line bg-zoop-wash px-4 py-3"
          >
            <p className="min-w-0 flex-1 text-xs">
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
          <p role="status" className="text-[11px] font-semibold">
            {notice}
          </p>
        )}
        {target && (
          <GraphVersionForm
            key={target.id}
            version={target}
            activeVersionId={activeVersionId}
            stale={stale}
            onPendingChange={setPending}
            onCancel={() => setTarget(null)}
            onDone={(result) => {
              setTarget(null);
              setNotice(
                result.idempotent
                  ? `${result.activeVersionId}는 이미 표시 중이에요.`
                  : `${result.activeVersionId}로 바꿨어요.`,
              );
              versions.reload();
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
                    version.id === activeVersionId ? 'bg-zoop-wash' : undefined
                  }
                >
                  <td className={`${TD} font-inter font-semibold break-all`}>
                    {version.id}
                    {version.kind === 'fixture' && (
                      <span className="ml-2 rounded-[3px] border-[0.667px] border-zoop-line px-1.5 py-0.5 text-[10px] font-normal text-zoop-muted">
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
                    className={`${TD} whitespace-nowrap font-inter tabular-nums`}
                  >
                    {formatKst(version.createdAt)}
                  </td>
                  <td className={`${TD} max-w-56 text-zoop-muted`}>
                    {version.sourceLabel}
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
                        aria-label={`${version.id}로 전환`}
                        onClick={() => {
                          setNotice(null);
                          setTarget(version);
                        }}
                        className={BUTTON}
                      >
                        전환
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
                    className={`${TD} whitespace-nowrap font-inter tabular-nums`}
                  >
                    {formatKst(activation.at)}
                  </td>
                  <td className={`${TD} whitespace-nowrap`}>
                    {activationLabel[activation.action] ?? activation.action}
                  </td>
                  <td
                    className={`${TD} font-inter whitespace-nowrap tabular-nums`}
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
