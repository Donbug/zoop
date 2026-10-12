import { create } from 'zustand';
import type { AiChatState, RecoveryStatus } from '@/types/ai';
const initial = {
  isOpen: false,
  context: null,
  conversationId: null,
  draft: '',
  recoveryStatus: 'idle' as RecoveryStatus,
};

// 대화 본문/서버 작업 결과는 이 store에 중복 저장하지 않는다.
export const useAiChatStore = create<AiChatState>((set) => ({
  ...initial,
  open: (context) =>
    set((state) => ({
      isOpen: true,
      context: context === undefined ? state.context : context,
    })),
  close: () => set({ isOpen: false }),
  setDraft: (draft) => set({ draft }),
  setConversationId: (conversationId) => set({ conversationId }),
  setRecoveryStatus: (recoveryStatus) => set({ recoveryStatus }),
  reset: () => set(initial),
}));
