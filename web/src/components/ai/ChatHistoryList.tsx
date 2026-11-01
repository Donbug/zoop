import { useCallback, useState } from 'react';
import { ApiError } from '@/apis/auth/ApiService';
import { deleteConversation, listConversations } from '@/apis/chat/chat';
import { panelStyles as ui } from '@/components/common/detail-panel-styles';
import { useCursorPages } from '@/hooks/useCursorPages';
import { formatKst } from '@/util/format';
import type { ChatConversationSummary } from '@/types/ai';
import LoadingIndicator, {
  LoadingSpinner,
} from '@/components/common/LoadingIndicator';

// D-AI-02 대화 기록(와이어프레임 없음, 임시 설계): AI 질문 창 안에서 지난 대화를 고르거나 삭제한다.
// 목록은 저장된 대화만 읽고 모델을 부르지 않는다. 삭제는 서버가 deleteEnabled로 연 경우에만 보여 준다
// (승인된 처리방침·약관은 개별 채팅 삭제 미제공이며, 개정본이 시행되면 서버 설정으로 연다).

type Props = {
  /** 지금 보고 있는 대화. 목록에 "지금 대화"로 표시한다. */
  currentId: string | null;
  /** 대화를 바꿀 수 없는 동안(보내는 중·확인하지 못한 질문 등) 열기를 막는다. */
  canOpen: boolean;
  onOpen: (id: string) => void;
  /** 서버에서 지운 대화. 지금 대화였다면 질문 창을 비운다. */
  onDeleted: (id: string) => void;
  onBack: () => void;
};

export default function ChatHistoryList({
  currentId,
  canOpen,
  onOpen,
  onDeleted,
  onBack,
}: Props) {
  const load = useCallback((cursor?: string) => listConversations(cursor), []);
  const history = useCursorPages(load);
  const deleteEnabled = history.pages[0]?.deleteEnabled ?? false;
  const [confirming, setConfirming] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function remove(item: ChatConversationSummary) {
    setDeleting(item.id);
    setMessage(null);
    try {
      await deleteConversation(item.id);
      setConfirming(null);
      onDeleted(item.id);
      setMessage('대화를 삭제했어요.');
      history.reload();
    } catch (error) {
      setMessage(deleteFailure(error));
    } finally {
      setDeleting(null);
    }
  }

  return (
    <div className={ui.scroll}>
      <div className="px-4 pt-3">
        <button type="button" className={ui.button} onClick={onBack}>
          ← 대화로 돌아가기
        </button>
      </div>
      <section className={ui.section} aria-labelledby="ai-chat-history">
        <h3 id="ai-chat-history">대화 기록</h3>
        {history.status === 'loading' && (
          <LoadingIndicator
            label="대화 기록을 불러오고 있어요."
            className={`${ui.muted} flex min-h-10 w-full`}
          />
        )}
        {history.status === 'error' && (
          <div role="alert">
            <p className="m-0">대화 기록을 불러오지 못했어요.</p>
            <button
              type="button"
              className="mt-2 underline"
              onClick={history.reload}
            >
              다시 시도
            </button>
          </div>
        )}
        {history.status === 'success' && history.items.length === 0 && (
          <p className={ui.muted}>
            아직 질문한 대화가 없어요. 질문을 보내면 여기에 대화가 쌓여요.
          </p>
        )}
        {history.items.length > 0 && (
          <ul className={ui.list} aria-label="지난 대화">
            {history.items.map((item) => (
              <li key={item.id}>
                <div className="flex items-start gap-2">
                  <button
                    type="button"
                    className="min-w-0 flex-1 rounded-panel p-1 text-left hover:enabled:bg-panel-soft focus-visible:outline-2 focus-visible:outline-panel-ink disabled:cursor-not-allowed"
                    disabled={!canOpen && item.id !== currentId}
                    aria-current={item.id === currentId ? 'true' : undefined}
                    onClick={() => onOpen(item.id)}
                  >
                    <span className={`${ui.itemTitle} block`}>
                      {item.title}
                    </span>
                    <span className={`${ui.muted} block`}>
                      {formatKst(item.updatedAt)} · 질문 {item.jobs}개
                      {item.id === currentId ? ' · 지금 대화' : ''}
                    </span>
                  </button>
                  {deleteEnabled && confirming !== item.id && (
                    <button
                      type="button"
                      className="shrink-0 p-1 text-caption text-panel-secondary underline"
                      aria-label={`“${item.title}” 대화 삭제`}
                      disabled={deleting !== null}
                      onClick={() => {
                        setMessage(null);
                        setConfirming(item.id);
                      }}
                    >
                      삭제
                    </button>
                  )}
                </div>
                {confirming === item.id && (
                  <div
                    className="mt-2 rounded-panel border border-panel-line bg-panel-soft p-2"
                    role="group"
                    aria-label="대화 삭제 확인"
                  >
                    <p className="m-0">
                      이 대화의 질문과 답변을 바로 삭제해요. 되돌릴 수 없어요.
                    </p>
                    <div className="mt-2 flex gap-3">
                      <button
                        type="button"
                        className="font-semibold text-zoop-alert underline"
                        disabled={deleting !== null}
                        aria-busy={deleting === item.id}
                        onClick={() => void remove(item)}
                      >
                        {deleting === item.id ? '삭제하는 중' : '삭제'}
                      </button>
                      <button
                        type="button"
                        className="underline"
                        disabled={deleting !== null}
                        onClick={() => setConfirming(null)}
                      >
                        취소
                      </button>
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        {history.hasMore && (
          <button
            type="button"
            className={`${ui.button} mt-2 w-full`}
            disabled={history.loadingMore}
            onClick={history.loadMore}
          >
            {history.loadingMore ? (
              <>
                <LoadingSpinner size="sm" />
                <span className="sr-only">불러오는 중</span>
              </>
            ) : (
              '더 보기'
            )}
          </button>
        )}
        {history.moreError && (
          <p className={`${ui.muted} mt-2`} role="alert">
            다음 대화를 불러오지 못했어요. 다시 눌러 주세요.
          </p>
        )}
        {message && (
          <p className={`${ui.muted} mt-2`} role="status">
            {message}
          </p>
        )}
        {history.status === 'success' && !deleteEnabled && (
          <p className={`${ui.muted} mt-3`}>
            대화 기록은 회원 탈퇴 시 모두 삭제돼요.
          </p>
        )}
      </section>
    </div>
  );
}

function deleteFailure(error: unknown) {
  if (error instanceof ApiError) {
    if (error.code === 'JOB_IN_PROGRESS')
      return '처리 중인 질문이 있어 삭제할 수 없어요. 질문을 취소하거나 끝난 뒤에 삭제해 주세요.';
    if (error.status === 404)
      return '이미 삭제됐거나 지금은 삭제할 수 없는 대화예요.';
    if (error.status === 401 || error.status === 403)
      return '로그인이 필요하거나 이 대화를 삭제할 수 없어요.';
  }
  return '대화를 삭제하지 못했어요. 잠시 후 다시 시도해 주세요.';
}
