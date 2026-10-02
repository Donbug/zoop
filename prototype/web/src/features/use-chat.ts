// AI 질문 대화의 클라이언트 쪽 상태(FS045–FS053).
// 서버가 대화·작업·결과의 원본이다. 여기에는 두 가지만 둔다.
//  1) 현재 대화 ID(패널을 닫거나 화면을 옮겨도 이 훅을 쓰는 창이 계속 살아 있고, 새로 열면 서버의 가장 최근 대화를 다시 찾는다).
//  2) "서버가 접수했는지 아직 모르는 전송". 응답을 받지 못하면 같은 작업 ID로 상태를 먼저 조회하고,
//     서버가 "없다"고 확인한 경우에만 같은 ID·같은 내용으로 다시 보낸다. 새 작업 ID는 사용자가 새 질문을 보낼 때만 만든다.
//  대화 캐시는 세션 세대별 칸이다(FS007). 각 작업은 시작할 때의 세대 칸에만 쓴다: 처리 중에 로그아웃하거나 다른 회원이 로그인해도
//  이전 회원의 대화가 새 세대 칸에 들어가지 않는다. 세대가 바뀌면 이 훅의 대화 ID·보내는 중인 질문·안내도 비운다.
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/api/client";
import {
  chatKeys,
  chatRequests,
  currentPersonalEpoch,
  isChatJobActive,
  useChatConversation,
  useCurrentChat,
  usePersonalEpoch,
  type ChatConversation,
  type ChatJob,
  type ChatJobRequest,
} from "@/api/queries";

export interface PendingSend {
  request: ChatJobRequest;
  sessionId: string;
  /** 이 질문에 연결해 보낸 대상 이름 */
  labels: string[];
  /** sending: 보내는 중 · checking: 응답을 못 받아 접수 여부를 확인하는 중 · unconfirmed: 확인도 못 했다(다시 확인 필요) */
  phase: "sending" | "checking" | "unconfirmed";
  /** 보낼 때의 세션 세대 */
  epoch: number;
}

export interface ChatNotice {
  kind: "busy" | "error";
  error: unknown;
}

function newId(prefix: string) {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return `${prefix}-${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
}

/** 응답을 받지 못했거나(연결 끊김) 서버 장애인 경우: 서버가 받았는지 알 수 없다. */
function outcomeUnknown(error: unknown) {
  return !(error instanceof ApiError) || error.status === 0 || error.status >= 500;
}

export function useChat({ member, open }: { member: boolean; open: boolean }) {
  const client = useQueryClient();
  const epoch = usePersonalEpoch();
  const [localId, setLocalId] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingSend | null>(null);
  const [notice, setNotice] = useState<ChatNotice | null>(null);
  const [startingNew, setStartingNew] = useState(false);
  const [newError, setNewError] = useState<unknown>(null);
  // 만들다 만 대화 ID: 응답을 못 받고 다시 시도해도 같은 ID라 대화가 둘 생기지 않는다.
  const draftId = useRef<string | null>(null);
  const newDraftId = useRef<string | null>(null);

  // 세대가 바뀌면(로그아웃·다른 회원 로그인) 이전 회원의 대화를 가리키던 상태를 버린다.
  useEffect(() => {
    setLocalId(null);
    setPending(null);
    setNotice(null);
    setNewError(null);
    draftId.current = null;
    newDraftId.current = null;
  }, [epoch]);

  const current = useCurrentChat(member && open && localId === null);
  const sessionId = localId ?? current.data ?? null;
  const conversation = useChatConversation(sessionId, member && open);
  const jobs = conversation.data?.jobs ?? [];
  const sessionPending = pending && pending.sessionId === sessionId ? pending : null;
  const hasActive = jobs.some(isChatJobActive) || sessionPending !== null;
  /** 가장 최근 대화를 아직 모르면(처음 조회 중이거나 조회 실패) 새 대화를 만들지 않는다: 조회 실패를 '대화 없음'으로 보지 않는다. */
  const ready = localId !== null || current.isSuccess;

  const adopt = useCallback(
    (sid: string, job: ChatJob, at: number) => {
      client.setQueryData<ChatConversation>(chatKeys.session(sid, at), (prev) => {
        const rest = (prev?.jobs ?? []).filter((j) => j.id !== job.id);
        const all = [...rest, job].sort((a, b) => a.seq - b.seq);
        return { session: { id: sid, createdAt: prev?.session.createdAt ?? job.createdAt, jobs: all.length }, jobs: all };
      });
      // 늦게 도착한 오래된 응답이 새 상태를 덮었을 수 있으니 한 번 더 읽어 맞춘다.
      void client.invalidateQueries({ queryKey: chatKeys.session(sid, at) });
    },
    [client],
  );

  /** 만든 대화의 ID. 만드는 사이 세대가 바뀌었으면 null(이전 회원의 대화를 지금 화면에 붙이지 않는다). */
  const createConversation = useCallback(
    async (id: string) => {
      const at = currentPersonalEpoch();
      const created = await chatRequests.createSession(id);
      if (at !== currentPersonalEpoch()) return null;
      client.setQueryData<ChatConversation>(chatKeys.session(id, at), { session: created, jobs: [] });
      setLocalId(id);
      return id;
    },
    [client],
  );

  const ensureSession = useCallback(async () => {
    if (sessionId) return sessionId;
    draftId.current ??= newId("chat");
    const id = await createConversation(draftId.current);
    if (id) draftId.current = null;
    return id;
  }, [createConversation, sessionId]);

  /** 서버에 이 작업이 있는지 묻는다. found: 있다(상태를 반영) · absent: 서버가 조회해 없다고 확인 · unknown: 확인하지 못했다 */
  const check = useCallback(
    async (sid: string, jobId: string, at: number): Promise<"found" | "absent" | "unknown"> => {
      try {
        adopt(sid, await chatRequests.job(jobId), at);
        return "found";
      } catch (error) {
        return error instanceof ApiError && error.status === 404 && error.code === "chat_job_not_found" ? "absent" : "unknown";
      }
    },
    [adopt],
  );

  /** accepted: 서버가 이 작업을 갖고 있다 · unconfirmed: 접수 여부를 아직 모른다 · rejected: 서버가 이 질문을 받지 않았다(입력을 유지한다) */
  const settle = useCallback(
    async (p: PendingSend): Promise<"accepted" | "unconfirmed" | "rejected"> => {
      const done = () => setPending((now) => (now?.request.jobId === p.request.jobId ? null : now));
      for (let attempt = 0; attempt < 3; attempt += 1) {
        try {
          adopt(p.sessionId, await chatRequests.submit(p.sessionId, p.request), p.epoch);
          done();
          return "accepted";
        } catch (error) {
          // 보낸 뒤 세대가 바뀌었으면 결과를 지금 화면에 알리지 않는다(캐시는 보낸 세대 칸에만 쓴다).
          if (p.epoch !== currentPersonalEpoch()) return "rejected";
          if (!outcomeUnknown(error)) {
            done();
            setNotice({ kind: error instanceof ApiError && error.code === "chat_session_busy" ? "busy" : "error", error });
            if (error instanceof ApiError && error.code === "chat_session_busy") void client.invalidateQueries({ queryKey: chatKeys.session(p.sessionId, p.epoch) });
            return "rejected";
          }
          setPending((now) => (now?.request.jobId === p.request.jobId ? { ...p, phase: "checking" } : now));
          const known = await check(p.sessionId, p.request.jobId, p.epoch);
          if (known === "found") {
            done();
            return "accepted";
          }
          if (known === "unknown") break;
          // absent: 서버가 작업 저장소를 정상 조회하고 기록이 없음을 확인했다 → 같은 작업 ID·같은 내용으로 다시 접수한다.
        }
      }
      setPending((now) => (now?.request.jobId === p.request.jobId ? { ...p, phase: "unconfirmed" } : now));
      return "unconfirmed";
    },
    [adopt, check, client],
  );

  const send = useCallback(
    async (question: string, context: ChatJobRequest["context"], labels: string[]) => {
      setNotice(null);
      let sid: string | null;
      try {
        sid = await ensureSession();
      } catch (error) {
        setNotice({ kind: "error", error });
        return false;
      }
      if (!sid) return false;
      const p: PendingSend = { request: { jobId: newId("job"), question, context }, sessionId: sid, labels, phase: "sending", epoch: currentPersonalEpoch() };
      setPending(p);
      return (await settle(p)) !== "rejected";
    },
    [ensureSession, settle],
  );

  /** 접수 여부를 모르는 전송: 먼저 서버에 이 작업의 상태를 묻는다. 서버가 없다고 확인한 때만 같은 내용으로 다시 접수한다. */
  const recheck = useCallback(async () => {
    if (!pending) return;
    setNotice(null);
    setPending({ ...pending, phase: "checking" });
    const known = await check(pending.sessionId, pending.request.jobId, pending.epoch);
    if (known === "found") setPending(null);
    else if (known === "absent") await settle(pending);
    else setPending({ ...pending, phase: "unconfirmed" });
  }, [check, pending, settle]);

  const act = useCallback(
    async (call: () => Promise<ChatJob>) => {
      setNotice(null);
      const at = currentPersonalEpoch();
      try {
        const job = await call();
        adopt(job.sessionId, job, at);
      } catch (error) {
        if (at !== currentPersonalEpoch()) return;
        setNotice({ kind: error instanceof ApiError && error.code === "chat_session_busy" ? "busy" : "error", error });
        if (sessionId) void client.invalidateQueries({ queryKey: chatKeys.session(sessionId, at) });
      }
    },
    [adopt, client, sessionId],
  );

  const retryJob = useCallback((jobId: string) => act(() => chatRequests.retry(jobId)), [act]);
  const cancelJob = useCallback((jobId: string) => act(() => chatRequests.cancel(jobId)), [act]);

  /** 새 대화: 이전 대화는 그대로 두고(처리 중인 질문도 취소하지 않는다) 별도 ID의 빈 대화로 옮긴다. 실패하면 지금 대화를 유지한다. */
  const startNew = useCallback(async () => {
    setStartingNew(true);
    setNewError(null);
    newDraftId.current ??= newId("chat");
    try {
      const id = await createConversation(newDraftId.current);
      if (!id) return false;
      newDraftId.current = null;
      setNotice(null);
      return true;
    } catch (error) {
      setNewError(error);
      return false;
    } finally {
      setStartingNew(false);
    }
  }, [createConversation]);

  return {
    sessionId,
    jobs,
    ready,
    current,
    conversation,
    pending: sessionPending,
    notice,
    dismissNotice: () => setNotice(null),
    hasActive,
    send,
    recheck,
    retryJob,
    cancelJob,
    startNew,
    startingNew,
    newError,
  };
}
