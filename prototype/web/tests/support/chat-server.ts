// AI 질문 서버 대역: 대화·작업을 메모리에 저장하고 BFF(/api/chat)와 같은 규칙으로 답한다.
//  - 대화 만들기(PUT)·질문 접수(POST)는 멱등이다. 같은 작업 ID를 다시 보내면 새 작업이 생기지 않고 기존 작업을 돌려준다.
//  - 처리 중인 작업이 있는 대화에 새 작업 ID를 보내면 409 chat_session_busy.
//  - 작업의 답변은 시험이 `complete()`로 끝내거나, `answerNow`를 켜 두면 접수 즉시 끝난다.
import type { Schemas } from "@/api/client";
import { apiError, json, type FakeBff, type Reply } from "./fake-bff";
import { metadata } from "./fixtures";

type Job = Schemas["ChatJob"];
type Failure = NonNullable<Job["failure"]>;

interface Session {
  id: string;
  createdAt: string;
  jobIds: string[];
}

export class ChatServer {
  readonly sessions = new Map<string, Session>();
  readonly jobs = new Map<string, Job>();
  /** 켜 두면 접수한 질문에 바로 이 함수가 만든 답변을 저장한다. */
  answerNow: ((question: string) => string) | null = null;
  readonly #labels: Record<string, string>;
  #tick = 0;

  /** labels: 질문에 연결하는 대상 id → 화면에 보일 이름 */
  constructor(labels: Record<string, string> = {}) {
    this.#labels = labels;
  }

  #now() {
    this.#tick += 1;
    return `2026-10-02T10:00:${String(this.#tick).padStart(2, "0")}+09:00`;
  }

  jobsOf(sessionId: string): Job[] {
    return (this.sessions.get(sessionId)?.jobIds ?? []).map((id) => this.jobs.get(id)!);
  }

  #conversation(session: Session) {
    return { session: { id: session.id, createdAt: session.createdAt, jobs: session.jobIds.length }, jobs: this.jobsOf(session.id) };
  }

  /** PUT /sessions/{id}: 없으면 만들고(201), 있으면 그대로(200) */
  createSession(id: string): Reply {
    const found = this.sessions.get(id);
    if (found) return json(this.#conversation(found).session);
    const session: Session = { id, createdAt: this.#now(), jobIds: [] };
    this.sessions.set(id, session);
    return json(this.#conversation(session).session, 201);
  }

  /** POST /sessions/{sid}/jobs: 서버가 질문을 접수한다. 응답을 클라이언트가 받는지는 별개다. */
  accept(sessionId: string, body: Schemas["ChatJobRequest"]): Reply {
    const session = this.sessions.get(sessionId);
    if (!session) return apiError(404, "chat_session_not_found", "대화를 찾을 수 없어요");
    const existing = this.jobs.get(body.jobId);
    if (existing) return json(existing);
    if (this.jobsOf(sessionId).some((j) => j.status === "queued" || j.status === "running"))
      return apiError(409, "chat_session_busy", "먼저 한 질문의 답변을 준비하고 있어요");

    const now = this.#now();
    const job: Job = {
      id: body.jobId,
      sessionId,
      seq: session.jobIds.length + 1,
      question: body.question,
      status: "running",
      outcome: null,
      askedAt: now,
      context: {
        items: (body.context?.contextIds ?? []).map((id) => ({ id, kind: "company", label: this.#labels[id] ?? id })),
        evidenceCount: body.context?.evidenceIds?.length ?? 0,
        period: null,
      },
      failure: null,
      result: null,
      runs: 1,
      createdAt: now,
      updatedAt: now,
      finishedAt: null,
    };
    this.jobs.set(job.id, job);
    session.jobIds.push(job.id);
    if (this.answerNow) this.complete(job.id, this.answerNow(job.question));
    return json(this.jobs.get(job.id), 202);
  }

  /** 서버가 답변을 검증·저장해 작업을 끝낸다. */
  complete(jobId: string, answer: string) {
    const job = this.jobs.get(jobId)!;
    const now = this.#now();
    this.jobs.set(jobId, {
      ...job,
      status: "completed",
      outcome: "answered",
      failure: null,
      result: {
        outcome: "answered",
        messageId: `message-${jobId}`,
        answer,
        reason: null,
        sources: [],
        citations: [],
        graphTargets: [],
        applied: { companies: job.context.items.map(({ id, label }) => ({ id, label })), issues: [], period: null, graphVersion: null, dataAsOf: now, questionOverrodeContext: false },
        choices: [],
        action: null,
        metadata,
      },
      updatedAt: now,
      finishedAt: now,
    });
  }

  /** 서버가 확인한 실패로 작업을 끝낸다. */
  fail(jobId: string, failure: Failure) {
    const job = this.jobs.get(jobId)!;
    const now = this.#now();
    this.jobs.set(jobId, { ...job, status: "failed", failure, result: null, updatedAt: now, finishedAt: now });
  }

  /** POST /jobs/{id}/retry: 같은 작업을 최초 질문·맥락 그대로 다시 실행한다. */
  retry(jobId: string): Reply {
    const job = this.jobs.get(jobId);
    if (!job) return apiError(404, "chat_job_not_found", "작업을 찾을 수 없어요");
    this.jobs.set(jobId, { ...job, status: "running", failure: null, runs: job.runs + 1, finishedAt: null });
    if (this.answerNow) this.complete(jobId, this.answerNow(job.question));
    return json(this.jobs.get(jobId), 202);
  }

  serve(bff: FakeBff) {
    bff.on("PUT", "/api/chat/sessions/:id", (_, { id }) => this.createSession(id!));
    bff.on("GET", "/api/chat/sessions/:id", (_, { id }) => {
      const session = this.sessions.get(id!);
      return session ? json(this.#conversation(session)) : apiError(404, "chat_session_not_found", "대화를 찾을 수 없어요");
    });
    bff.on("POST", "/api/chat/sessions/:sid/jobs", (request, { sid }) => this.accept(sid!, request.body as Schemas["ChatJobRequest"]));
    bff.on("GET", "/api/chat/jobs/:id", (_, { id }) => {
      const job = this.jobs.get(id!);
      return job ? json(job) : apiError(404, "chat_job_not_found", "작업을 찾을 수 없어요");
    });
    bff.on("POST", "/api/chat/jobs/:id/retry", (_, { id }) => this.retry(id!));
    bff.on("GET", "/api/feedback", json({ items: [] }));
    // 나중에 등록한 경로가 우선하므로, ":id"에 먹히지 않도록 "current"를 마지막에 둔다.
    bff.on("GET", "/api/chat/sessions/current", () => {
      const latest = [...this.sessions.values()].at(-1);
      return json({ conversation: latest ? this.#conversation(latest) : null });
    });
  }
}
