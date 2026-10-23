import { describe, expect, it } from 'vitest';
import {
  cancelQuestionJob,
  createConversation,
  getConversation,
  getCurrentConversation,
  retryQuestionJob,
  submitQuestion,
} from '@/apis/chat/chat';
import type { ChatJob } from '@/types/ai';
import { createFakeServer, json } from '../support/fakeServer';

// D-AI-01 · D-AI-02 — 경로의 ID와 다른 성공 응답이 현재 대화 상태를 오염시키지 않아야 한다.

const SESSION_ID = 'conv-0001';
const JOB_ID = 'job-00000001';

function job(patch: Partial<ChatJob> = {}): ChatJob {
  return {
    id: JOB_ID,
    sessionId: SESSION_ID,
    seq: 1,
    question: 'HBM이 뭐야?',
    status: 'queued',
    phase: null,
    outcome: null,
    askedAt: '2026-10-21T00:00:00Z',
    context: {
      items: [],
      evidenceCount: 0,
      period: null,
      asOf: null,
      graphVersion: null,
    },
    resolves: null,
    failure: null,
    result: null,
    runs: 1,
    createdAt: '2026-10-21T00:00:00Z',
    updatedAt: '2026-10-21T00:00:00Z',
    finishedAt: null,
    ...patch,
  };
}

describe('chat API response identity', () => {
  it('rejects a created session whose id differs from the requested path', async () => {
    const server = createFakeServer();
    server.on('PUT', '/api/v1/chat/sessions/:id', () =>
      json({ id: 'conv-other', createdAt: '2026-10-21T00:00:00Z', jobs: 0 }),
    );

    await expect(createConversation(SESSION_ID)).rejects.toThrow(
      '요청한 대화와 응답이 일치하지 않습니다.',
    );
  });

  it('rejects a fetched conversation or contained job from another session', async () => {
    const server = createFakeServer();
    server.on('GET', '/api/v1/chat/sessions/:id', () =>
      json({
        session: {
          id: SESSION_ID,
          createdAt: '2026-10-21T00:00:00Z',
          jobs: 1,
        },
        jobs: [job({ sessionId: 'conv-other' })],
      }),
    );

    await expect(getConversation(SESSION_ID)).rejects.toThrow(
      '대화에 다른 세션의 질문 작업이 포함되어 있습니다.',
    );
  });

  it('rejects a current conversation containing a job from another session', async () => {
    const server = createFakeServer();
    server.on('GET', '/api/v1/chat/sessions/current', () =>
      json({
        conversation: {
          session: {
            id: SESSION_ID,
            createdAt: '2026-10-21T00:00:00Z',
            jobs: 1,
          },
          jobs: [job({ sessionId: 'conv-other' })],
        },
      }),
    );

    await expect(getCurrentConversation()).rejects.toThrow(
      '대화에 다른 세션의 질문 작업이 포함되어 있습니다.',
    );
  });

  it('rejects a submitted job attached to another session', async () => {
    const server = createFakeServer();
    server.on('POST', '/api/v1/chat/sessions/:id/jobs', () =>
      json(job({ sessionId: 'conv-other' }), 202),
    );

    await expect(
      submitQuestion(SESSION_ID, { jobId: JOB_ID, question: 'HBM이 뭐야?' }),
    ).rejects.toThrow('접수한 대화와 질문 작업이 일치하지 않습니다.');
  });

  it.each([
    ['retry', retryQuestionJob],
    ['cancel', cancelQuestionJob],
  ])('rejects a mismatched %s response job', async (action, request) => {
    const server = createFakeServer();
    server.on('POST', `/api/v1/chat/jobs/:id/${action}`, () =>
      json(job({ id: 'job-other' })),
    );

    await expect(request(JOB_ID, 'idem-key')).rejects.toThrow(
      '요청한 질문 작업과 응답이 일치하지 않습니다.',
    );
  });
});
