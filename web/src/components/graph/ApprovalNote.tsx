import type { EventDetail } from '@/types/map/event';
import PanelDisclosure from './PanelDisclosure';
import GraphIcon from './GraphIcon';

// D-GRP-02 · gap 26. Port of domain/approval-note.tsx, no inferred approval.
export default function ApprovalNote({
  approval,
}: {
  approval: EventDetail['approval'];
}) {
  if (!approval) return null;
  const byAdmin = approval.source === 'admin-review';
  return (
    <div className="flex items-start gap-1 px-4 pb-2">
      <span className="inline-flex rounded bg-zoop-soft px-2 py-1 text-zoop-muted">
        {approval.label}
      </span>
      <PanelDisclosure
        trigger={
          <span className="grid size-7 place-items-center">
            <GraphIcon name="info" size={16} />
          </span>
        }
        label={
          byAdmin
            ? '관리자가 원문 근거를 직접 확인하고 게시했어요'
            : '역할 표현을 확인하지 못해 비우고 게시했어요'
        }
      >
        {byAdmin ? (
          <p>AI 검증이 보류했던 내용을 관리자가 원문 인용으로 확인했어요.</p>
        ) : (
          <p>
            사건과 원문 인용은 AI 검증을 통과했어요. 확인하지 못한 역할은 ‘역할
            미확인’으로 보여요.
          </p>
        )}
        {byAdmin && approval.ruleId && (
          <p>같은 사건에 자동 검수 규칙으로 게시된 내용도 있어요.</p>
        )}
      </PanelDisclosure>
    </div>
  );
}
