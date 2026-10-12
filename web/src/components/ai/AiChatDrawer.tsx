import { Link } from 'react-router-dom';
import PageSection from '@/components/common/PageSection';
import { useAiChatStore } from '@/stores/useAiChatStore';
import { useAuth } from '@/hooks/useAuth';

// D-AI-01/01b/02/02b. 대화 회수와 새 질문 전송은 별도 API로 구현한다.
export default function AiChatDrawer() {
  const isOpen = useAiChatStore((state) => state.isOpen);
  const draft = useAiChatStore((state) => state.draft);
  const setDraft = useAiChatStore((state) => state.setDraft);
  const close = useAiChatStore((state) => state.close);
  const { isAuthenticated } = useAuth();
  if (!isOpen) return null;
  return (
    <PageSection title="AI에게 묻기">
      {isAuthenticated ? (
        <label className="block">
          질문
          <textarea
            className="mt-2 block w-full rounded border p-3"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
        </label>
      ) : (
        <Link to="/login" className="underline">
          로그인 후 질문할 수 있어요
        </Link>
      )}
      <p className="mt-3 text-sm text-gray-500">
        질문 전송 기능을 준비하고 있습니다.
      </p>
      <button type="button" onClick={close} className="mt-3 underline">
        닫기
      </button>
    </PageSection>
  );
}
