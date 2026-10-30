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
// web_reported: what a supplementary web search reported, never ZOOP's own verified fact.
export type ChatBasis =
  | 'general_knowledge'
  | 'zoop_documented'
  | 'evidence_grounded'
  | 'web_reported';
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
  /**
   * company_profile: ZOOP's reviewed company catalog text; docId is the company id.
   * web_result: a web search hit; publisher is the page's domain and docId the search provider.
   */
  sourceKind: 'article' | 'zoop_doc' | 'company_profile' | 'web_result';
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
  | 'not_in_member_scope'
  | 'evidence_insufficient'
  | 'out_of_scope'
  | 'tool_unavailable';

export type ChatLimitation = {
  kind: ChatLimitationKind;
  label: string;
  message: string;
};

// 답변 완결 정도(MCP 실행 계약 3.5): 서버가 정하며 job.status·outcome과 별개다.
export type ChatAnswerStatus = 'complete' | 'partial' | 'guidance';

export type ChatNoticeCode =
  | 'mcp_direct_start'
  | 'web_unavailable'
  | 'web_no_results'
  | 'web_budget_exhausted'
  | 'web_not_configured'
  | 'tool_unavailable'
  | 'tool_budget_exhausted';

// 답변을 막지 않은 장애·우회. labels가 비어 있으면 실행 전체에 해당한다.
export type ChatNotice = {
  code: ChatNoticeCode;
  labels: string[];
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
  answerStatus: ChatAnswerStatus;
  notices: ChatNotice[];
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

/** listConversations 한 항목. title은 첫 질문(100자 초과 시 잘림), updatedAt은 마지막으로 질문한 시각. */
export type ChatConversationSummary = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  jobs: number;
};

/** deleteEnabled가 거짓이면 서버가 삭제를 열지 않았다(처리방침·약관 개정 전): 삭제를 보여 주지 않는다. */
export type ChatConversationList = {
  items: ChatConversationSummary[];
  nextCursor: string | null;
  deleteEnabled: boolean;
};
