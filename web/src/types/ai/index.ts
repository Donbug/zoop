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

// docs/api/openapi.yaml chat schemas (createConversation … cancelQuestionJob).

export type ChatJobStatus =
  'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
export type ChatPhase = 'planning' | 'retrieving' | 'writing' | 'verifying';
export type ChatOutcome =
  'answered' | 'clarification' | 'guidance' | 'insufficient_evidence';
export type ChatBasis =
  'general_knowledge' | 'zoop_documented' | 'evidence_grounded';
export type ChatAnswerBasis = ChatBasis | 'mixed' | 'none';

export type ChatPeriod = { start: string; end: string };

export type ChatContextRequest = {
  contextIds?: string[];
  evidenceIds?: string[];
  period?: ChatPeriod | null;
  asOf?: string | null;
  graphVersion?: string | null;
};

export type ChatClarificationReply = { jobId: string; choiceId: string | null };

export type ChatJobRequest = {
  jobId: string;
  question: string;
  context?: ChatContextRequest;
  resolves?: ChatClarificationReply;
};

export type ChatContextItem = { id: string; kind: string; label: string };

export type ChatFrozenContext = {
  items: ChatContextItem[];
  evidenceCount: number;
  period: ChatPeriod | null;
  asOf: string | null;
  graphVersion: string | null;
};

export type ChatAnswerSection = {
  basis: ChatBasis;
  text: string;
  evidenceIds: string[];
};

export type ChatCitation = {
  sourceKind: 'article' | 'zoop_doc';
  evidenceId: string;
  quote: string;
  articleId: string | null;
  articleVersion: string | null;
  docId: string | null;
  docVersion: string | null;
  start: number;
  end: number;
  articleTitle: string | null;
  publisher: string | null;
  publishedAt: string | null;
  url: string | null;
};

export type ChatGraphTarget = { id: string; kind: string };

export type ChatAppliedItem = { id: string; label: string };

export type ChatApplied = {
  companies: ChatAppliedItem[];
  issues: ChatAppliedItem[];
  period: {
    start: string;
    end: string;
    basis: 'question' | 'context' | 'evidence';
    expression: string | null;
  } | null;
  graphVersion: string | null;
  dataAsOf: string;
  questionOverrodeContext: boolean;
};

export type ChatChoice = {
  id: string;
  label: string;
  kind: 'company' | 'period' | 'scope' | 'snapshot' | 'other';
};

export type ChatAction = { kind: 'set_watchlist'; label: string };

export type ChatLimitationKind =
  | 'investment_advice'
  | 'precondition_unmet'
  | 'results_truncated'
  | 'evidence_insufficient'
  | 'out_of_scope';

export type ChatLimitation = {
  kind: ChatLimitationKind;
  label: string;
  message: string;
};

export type ChatResult = {
  outcome: ChatOutcome;
  messageId: string;
  answer: string;
  sections: ChatAnswerSection[];
  answerBasis: ChatAnswerBasis;
  reason: string | null;
  sources: string[];
  citations: ChatCitation[];
  graphTargets: ChatGraphTarget[];
  applied: ChatApplied;
  choices: ChatChoice[];
  action: ChatAction | null;
  limitations: ChatLimitation[];
};

export type ChatFailureKind =
  | 'validation_failed'
  | 'save_failed'
  | 'result_lost'
  | 'transient'
  | 'budget_exceeded'
  | 'permission_denied'
  | 'internal';

export type ChatFailure = {
  kind: ChatFailureKind;
  reason: string | null;
  message: string;
  retry: 'rerun' | 'save_only' | null;
};

export type ChatJob = {
  id: string;
  sessionId: string;
  seq: number;
  question: string;
  status: ChatJobStatus;
  phase: ChatPhase | null;
  outcome: ChatOutcome | null;
  askedAt: string;
  context: ChatFrozenContext;
  resolves: ChatClarificationReply | null;
  failure: ChatFailure | null;
  result: ChatResult | null;
  runs: number;
  createdAt: string;
  updatedAt: string;
  finishedAt: string | null;
};

export type ChatSession = { id: string; createdAt: string; jobs: number };

export type ChatConversation = { session: ChatSession; jobs: ChatJob[] };

export type ChatCurrentResponse = { conversation: ChatConversation | null };
