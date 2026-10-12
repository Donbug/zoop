import type { GraphTarget } from '@/types/map';

export type RecoveryStatus = 'idle' | 'loading' | 'ready' | 'error';

export type AiChatState = {
  isOpen: boolean;
  context: GraphTarget | null;
  conversationId: string | null;
  draft: string;
  recoveryStatus: RecoveryStatus;
  open: (context?: GraphTarget | null) => void;
  close: () => void;
  setDraft: (draft: string) => void;
  setConversationId: (conversationId: string | null) => void;
  setRecoveryStatus: (recoveryStatus: RecoveryStatus) => void;
  reset: () => void;
};
