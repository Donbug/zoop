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

export function createConversation(id: string) {
  return call<ChatSession>(`/api/v1/chat/sessions/${enc(id)}`, 'PUT');
}

export function getConversation(id: string) {
  return call<ChatConversation>(`/api/v1/chat/sessions/${enc(id)}`, 'GET');
}

export function getCurrentConversation() {
  return call<ChatCurrentResponse>('/api/v1/chat/sessions/current', 'GET');
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
  if (job.id !== request.jobId)
    throw new Error('접수한 질문과 응답이 일치하지 않습니다.');
  return job;
}

export async function getQuestionJob(jobId: string) {
  const job = await call<ChatJob>(`/api/v1/chat/jobs/${enc(jobId)}`, 'GET');
  if (job.id !== jobId)
    throw new Error('요청한 질문 작업과 응답이 일치하지 않습니다.');
  return job;
}

export function retryQuestionJob(jobId: string, key: string) {
  return call<ChatJob>(
    `/api/v1/chat/jobs/${enc(jobId)}/retry`,
    'POST',
    undefined,
    {
      headers: { 'Idempotency-Key': key },
    },
  );
}

export function cancelQuestionJob(jobId: string, key: string) {
  return call<ChatJob>(
    `/api/v1/chat/jobs/${enc(jobId)}/cancel`,
    'POST',
    undefined,
    {
      headers: { 'Idempotency-Key': key },
    },
  );
}
