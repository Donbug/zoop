import { call } from '@/apis/auth/ApiService';
import { createIdempotencyKey } from '@/apis/portfolio/portfolio';
import type {
  ChatConversation,
  ChatCurrentResponse,
  ChatJob,
  ChatJobRequest,
  ChatSession,
} from '@/types/ai';

// D-AI-01/01b/02/02b. docs/api/openapi.yaml createConversation … cancelQuestionJob.
// GET 회수는 저장된 상태만 읽고 모델을 다시 부르지 않는다.

/** 대화·질문 작업 ID: 계약의 `[A-Za-z0-9_-]{8,64}`. */
export function newChatId() {
  return createIdempotencyKey().replace(/[^A-Za-z0-9_-]/g, '');
}

const enc = encodeURIComponent;

function ensureSessionId(session: ChatSession, expectedId: string) {
  if (session.id !== expectedId)
    throw new Error('요청한 대화와 응답이 일치하지 않습니다.');
  return session;
}

function ensureConversationId(
  conversation: ChatConversation,
  expectedId = conversation.session.id,
) {
  ensureSessionId(conversation.session, expectedId);
  if (conversation.jobs.some((job) => job.sessionId !== expectedId))
    throw new Error('대화에 다른 세션의 질문 작업이 포함되어 있습니다.');
  return conversation;
}

function ensureJobId(job: ChatJob, expectedId: string) {
  if (job.id !== expectedId)
    throw new Error('요청한 질문 작업과 응답이 일치하지 않습니다.');
  return job;
}

export async function createConversation(id: string) {
  const session = await call<ChatSession>(
    `/api/v1/chat/sessions/${enc(id)}`,
    'PUT',
  );
  return ensureSessionId(session, id);
}

export async function getConversation(id: string) {
  const conversation = await call<ChatConversation>(
    `/api/v1/chat/sessions/${enc(id)}`,
    'GET',
  );
  return ensureConversationId(conversation, id);
}

export async function getCurrentConversation() {
  const current = await call<ChatCurrentResponse>(
    '/api/v1/chat/sessions/current',
    'GET',
  );
  if (current.conversation) ensureConversationId(current.conversation);
  return current;
}

/** 같은 jobId(=Idempotency-Key)로 다시 보내면 서버는 같은 작업을 돌려준다. */
export async function submitQuestion(
  sessionId: string,
  request: ChatJobRequest,
) {
  const job = await call<ChatJob>(
    `/api/v1/chat/sessions/${enc(sessionId)}/jobs`,
    'POST',
    request,
    { headers: { 'Idempotency-Key': request.jobId } },
  );
  ensureJobId(job, request.jobId);
  if (job.sessionId !== sessionId)
    throw new Error('접수한 대화와 질문 작업이 일치하지 않습니다.');
  return job;
}

export async function getQuestionJob(jobId: string) {
  const job = await call<ChatJob>(`/api/v1/chat/jobs/${enc(jobId)}`, 'GET');
  return ensureJobId(job, jobId);
}

export async function retryQuestionJob(jobId: string, key: string) {
  const job = await call<ChatJob>(
    `/api/v1/chat/jobs/${enc(jobId)}/retry`,
    'POST',
    undefined,
    {
      headers: { 'Idempotency-Key': key },
    },
  );
  return ensureJobId(job, jobId);
}

export async function cancelQuestionJob(jobId: string, key: string) {
  const job = await call<ChatJob>(
    `/api/v1/chat/jobs/${enc(jobId)}/cancel`,
    'POST',
    undefined,
    {
      headers: { 'Idempotency-Key': key },
    },
  );
  return ensureJobId(job, jobId);
}
