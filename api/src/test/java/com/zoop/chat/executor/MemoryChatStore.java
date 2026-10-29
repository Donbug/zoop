package com.zoop.chat.executor;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import com.zoop.chat.repository.ChatExecutionRepository;
import com.zoop.chat.repository.ChatJobRow;
import com.zoop.chat.repository.ChatRepository;
import com.zoop.chat.repository.ChatRunningJob;
import com.zoop.chat.repository.ChatSessionRow;
import com.zoop.chat.repository.ChatToolCallEnd;
import com.zoop.chat.repository.NewChatJob;
import com.zoop.chat.repository.NewChatToolCall;

/**
 * In-memory job store with the executor's fences: a run's writes apply only while the job is running under its owner token
 * and an unexpired lease. Only the reads the executor needs are implemented.
 */
public final class MemoryChatStore implements ChatRepository, ChatExecutionRepository {
    final Map<String, Job> jobs = new LinkedHashMap<>();
    final List<ToolCall> toolCalls = new ArrayList<>();

    /** A {@code chat_tool_calls} row: the reservation, its status and how it ended. */
    public static final class ToolCall {
        public final NewChatToolCall row;
        public String status = "reserved";
        public ChatToolCallEnd end;

        ToolCall(NewChatToolCall row) {
            this.row = row;
        }
    }

    /** A mutable job row: the stored row plus the run columns the executor writes. */
    static final class Job {
        ChatJobRow row;
        String ownerToken;
        Instant leaseUntil;
        Instant deadline;
        String result;
        String failure;
        String routeSummary;
        String messageId;
        List<String> phases = new ArrayList<>();

        Job(ChatJobRow row) {
            this.row = row;
        }
    }

    public void add(ChatJobRow row) {
        jobs.put(row.id(), new Job(row));
    }

    Job job(String id) {
        return jobs.get(id);
    }

    /** What a member's cancel does to the row. */
    public void cancel(String id, Instant at) {
        Job job = jobs.get(id);
        job.row = with(job.row, "cancelled", null, job.row.runs(), job.row.attempts(), at, at);
        job.ownerToken = null;
        job.leaseUntil = null;
        closeToolCalls(id);
    }

    public synchronized List<ToolCall> toolCalls(String jobId) {
        return toolCalls.stream().filter(c -> c.row.jobId().equals(jobId)).toList();
    }

    @Override
    public Optional<ChatJobRow> findJob(String jobId) {
        return Optional.ofNullable(jobs.get(jobId)).map(job -> job.row);
    }

    @Override
    public Optional<ChatJobRow> lockNextQueued() {
        return jobs.values().stream().filter(job -> "queued".equals(job.row.status()))
                .min(Comparator.comparing((Job job) -> job.row.updatedAt()).thenComparing(job -> job.row.id()))
                .map(job -> job.row);
    }

    @Override
    public boolean start(String jobId, String ownerToken, Instant deadline, Instant leaseUntil, String attempts, Instant at) {
        Job job = jobs.get(jobId);
        if (!"queued".equals(job.row.status())) return false;
        job.row = with(job.row, "running", "planning", job.row.runs(), attempts, at, null);
        job.ownerToken = ownerToken;
        job.deadline = deadline;
        job.leaseUntil = leaseUntil;
        return true;
    }

    @Override
    public Optional<ChatJobRow> lockOwned(String jobId, String ownerToken, Instant at) {
        Job job = jobs.get(jobId);
        return owned(job, ownerToken, at) ? Optional.of(job.row) : Optional.empty();
    }

    @Override
    public Optional<ChatRunningJob> findRunning(String jobId, Instant at) {
        Job job = jobs.get(jobId);
        if (job == null || job.ownerToken == null || !owned(job, job.ownerToken, at)) return Optional.empty();
        return Optional.of(new ChatRunningJob(job.row, job.ownerToken, job.deadline));
    }

    @Override
    public boolean phase(String jobId, String ownerToken, String phase, Instant at) {
        Job job = jobs.get(jobId);
        if (!owned(job, ownerToken, at)) return false;
        job.row = with(job.row, "running", phase, job.row.runs(), job.row.attempts(), at, null);
        job.phases.add(phase);
        return true;
    }

    @Override
    public synchronized boolean shortenDeadline(String jobId, String ownerToken, Instant deadline, Instant at) {
        Job job = jobs.get(jobId);
        if (!owned(job, ownerToken, at)) return false;
        if (deadline.isBefore(job.deadline)) job.deadline = deadline;
        return true;
    }

    @Override
    public void recordModelCall(String jobId, int runs, String attempts, Instant at) {
        Job job = jobs.get(jobId);
        job.row = with(job.row, job.row.status(), job.row.phase(), runs, attempts, at, null);
    }

    @Override
    public boolean complete(String jobId, String ownerToken, Instant at, String outcome, String messageId, String result,
            String resultSchemaVersion, String routeSummary, String routeSchemaVersion, String attempts) {
        Job job = jobs.get(jobId);
        if (!owned(job, ownerToken, at)) return false;
        job.row = withOutcome(with(job.row, "completed", null, job.row.runs(), attempts, at, at), outcome, result, null);
        job.result = result;
        job.messageId = messageId;
        job.routeSummary = routeSummary;
        release(job);
        closeToolCalls(jobId);
        return true;
    }

    @Override
    public boolean fail(String jobId, String ownerToken, Instant at, String failure, String attempts) {
        Job job = jobs.get(jobId);
        if (!owned(job, ownerToken, at)) return false;
        finishFailed(job, failure, attempts, at);
        return true;
    }

    @Override
    public List<String> expired(Instant at, int limit) {
        return jobs.values().stream().filter(job -> "running".equals(job.row.status()) && !job.leaseUntil.isAfter(at))
                .map(job -> job.row.id()).limit(limit).toList();
    }

    @Override
    public Optional<ChatJobRow> lockExpired(String jobId, Instant at) {
        Job job = jobs.get(jobId);
        return "running".equals(job.row.status()) && !job.leaseUntil.isAfter(at) ? Optional.of(job.row) : Optional.empty();
    }

    @Override
    public boolean failExpired(String jobId, Instant at, String failure, String attempts) {
        Job job = jobs.get(jobId);
        if (lockExpired(jobId, at).isEmpty()) return false;
        finishFailed(job, failure, attempts, at);
        return true;
    }

    private static boolean owned(Job job, String ownerToken, Instant at) {
        return "running".equals(job.row.status()) && ownerToken.equals(job.ownerToken) && job.leaseUntil.isAfter(at);
    }

    private void finishFailed(Job job, String failure, String attempts, Instant at) {
        job.row = withOutcome(with(job.row, "failed", null, job.row.runs(), attempts, at, at), null, null, failure);
        job.failure = failure;
        release(job);
        closeToolCalls(job.row.id());
    }

    /** Memory waits for nothing. */
    @Override
    public void limitWait(java.time.Duration wait) {
    }

    @Override
    public synchronized int countToolCalls(String jobId, int attemptNo) {
        return (int) toolCalls.stream().filter(c -> c.row.jobId().equals(jobId) && c.row.attemptNo() == attemptNo).count();
    }

    @Override
    public synchronized int countJobToolCalls(String jobId, int attemptNo, boolean web) {
        return (int) toolCalls.stream().filter(c -> c.row.jobId().equals(jobId)
                && (c.row.attemptNo() == attemptNo || !"cancelled".equals(c.status))
                && "web-search".equals(c.row.registryGroup()) == web).count();
    }

    /** Web searches taken per KST day and subject ("project" or "member:<id>"). */
    final Map<String, Integer> webQuotas = new java.util.HashMap<>();

    @Override
    public synchronized String takeWebSearchQuota(String memberId, java.time.LocalDate day, int calls, int memberCap,
            int projectCap) {
        String project = day + "/project";
        String member = day + "/member:" + memberId;
        if (webQuotas.getOrDefault(project, 0) + calls > projectCap) return "project";
        if (webQuotas.getOrDefault(member, 0) + calls > memberCap) return "member";
        webQuotas.merge(project, calls, Integer::sum);
        webQuotas.merge(member, calls, Integer::sum);
        return null;
    }

    @Override
    public synchronized void reserveToolCalls(List<NewChatToolCall> calls, Instant at) {
        calls.forEach(call -> toolCalls.add(new ToolCall(call)));
    }

    @Override
    public synchronized Optional<String> findReservedToolCall(String jobId, int attemptNo, String capabilityId,
            String inputDigest) {
        return toolCalls.stream().filter(c -> c.row.jobId().equals(jobId) && c.row.attemptNo() == attemptNo
                        && c.row.capabilityId().equals(capabilityId) && c.row.inputDigest().equals(inputDigest)
                        && "reserved".equals(c.status))
                .min(java.util.Comparator.comparingInt(c -> c.row.callIndex())).map(c -> c.row.toolCallId());
    }

    @Override
    public synchronized Optional<String> claimReservedToolCall(String jobId, String ownerToken, int attemptNo,
            String capabilityId, String inputDigest, Instant at) {
        if (!owned(jobs.get(jobId), ownerToken, at)) return Optional.empty();
        var claimed = toolCalls.stream().filter(c -> c.row.jobId().equals(jobId) && c.row.attemptNo() == attemptNo
                        && c.row.capabilityId().equals(capabilityId) && c.row.inputDigest().equals(inputDigest)
                        && "reserved".equals(c.status))
                .min(Comparator.comparingInt(c -> c.row.callIndex()));
        claimed.ifPresent(c -> c.status = "running");
        return claimed.map(c -> c.row.toolCallId());
    }

    /** Memory stores JSON as given: its stored size is its own UTF-8 size. */
    @Override
    public long storedResultBytes(String result) {
        return result.getBytes(java.nio.charset.StandardCharsets.UTF_8).length;
    }

    @Override
    public synchronized boolean startToolCall(String jobId, String ownerToken, int attemptNo, String toolCallId,
            Instant at) {
        var call = toolCall(jobId, attemptNo, toolCallId);
        if (!owned(jobs.get(jobId), ownerToken, at) || !"reserved".equals(call.status)) return false;
        call.status = "running";
        return true;
    }

    @Override
    public synchronized boolean finishToolCall(String jobId, String ownerToken, int attemptNo, String toolCallId,
            ChatToolCallEnd end, Instant at) {
        var call = toolCall(jobId, attemptNo, toolCallId);
        if (!owned(jobs.get(jobId), ownerToken, at) || !"running".equals(call.status)) return false;
        call.status = end.status();
        call.end = end;
        return true;
    }

    @Override
    public synchronized List<com.zoop.chat.repository.ChatKeptToolResult> keptToolResults(String jobId, int attemptNo) {
        return toolCalls.stream().filter(c -> c.row.jobId().equals(jobId) && c.row.attemptNo() == attemptNo
                        && "succeeded".equals(c.status) && c.end != null && c.end.result() != null)
                .sorted(Comparator.comparingInt(c -> c.row.callIndex()))
                .map(c -> new com.zoop.chat.repository.ChatKeptToolResult(c.row.toolCallId(), c.row.capabilityId(),
                        c.end.result()))
                .toList();
    }

    @Override
    public synchronized Optional<com.zoop.chat.repository.ChatKeptToolResult> findKeptToolResult(String jobId, int attemptNo,
            String capabilityId, String inputDigest) {
        return toolCalls.stream().filter(c -> c.row.jobId().equals(jobId) && c.row.attemptNo() == attemptNo
                        && c.row.capabilityId().equals(capabilityId) && c.row.inputDigest().equals(inputDigest)
                        && "succeeded".equals(c.status) && c.end != null && c.end.result() != null)
                .min(Comparator.comparingInt(c -> c.row.callIndex()))
                .map(c -> new com.zoop.chat.repository.ChatKeptToolResult(c.row.toolCallId(), c.row.capabilityId(),
                        c.end.result()));
    }

    @Override
    public synchronized long keptResultBytes(String jobId) {
        return toolCalls.stream().filter(c -> c.row.jobId().equals(jobId) && c.end != null && c.end.result() != null)
                .mapToLong(c -> c.end.result().getBytes(java.nio.charset.StandardCharsets.UTF_8).length).sum();
    }

    private ToolCall toolCall(String jobId, int attemptNo, String toolCallId) {
        return toolCalls.stream().filter(c -> c.row.jobId().equals(jobId) && c.row.attemptNo() == attemptNo
                && c.row.toolCallId().equals(toolCallId)).findFirst().orElseThrow();
    }

    /** What the job's end does to its open tool calls. */
    private synchronized void closeToolCalls(String jobId) {
        toolCalls.stream().filter(c -> c.row.jobId().equals(jobId)).forEach(c -> {
            if ("reserved".equals(c.status)) c.status = "cancelled";
            else if ("running".equals(c.status)) c.status = "unknown";
        });
    }

    private static void release(Job job) {
        job.ownerToken = null;
        job.leaseUntil = null;
        job.deadline = null;
    }

    private static ChatJobRow with(ChatJobRow r, String status, String phase, int runs, String attempts, Instant updatedAt,
            Instant finishedAt) {
        return new ChatJobRow(r.id(), r.sessionId(), r.memberId(), r.seq(), r.question(), r.requestHash(), r.askedAt(),
                r.frozenContext(), r.frozenSelection(), r.contextCompanyIds(), r.graphVersionId(), status, phase, r.outcome(),
                r.resolvesJobId(),
                r.resolvesChoiceId(), r.clarificationDepth(), r.result(), r.failure(), runs, attempts, r.createdAt(),
                updatedAt, finishedAt);
    }

    private static ChatJobRow withOutcome(ChatJobRow r, String outcome, String result, String failure) {
        return new ChatJobRow(r.id(), r.sessionId(), r.memberId(), r.seq(), r.question(), r.requestHash(), r.askedAt(),
                r.frozenContext(), r.frozenSelection(), r.contextCompanyIds(), r.graphVersionId(), r.status(), r.phase(),
                outcome,
                r.resolvesJobId(), r.resolvesChoiceId(), r.clarificationDepth(), result, failure, r.runs(), r.attempts(),
                r.createdAt(), r.updatedAt(), r.finishedAt());
    }

    // The executor reads nothing else of the chat repository.
    @Override public Optional<ChatSessionRow> findSession(String sessionId) { throw new UnsupportedOperationException(); }
    @Override public Optional<ChatSessionRow> lockSession(String sessionId) { throw new UnsupportedOperationException(); }
    @Override public boolean insertSession(ChatSessionRow session) { throw new UnsupportedOperationException(); }
    @Override public void touchSession(String sessionId, Instant at) { throw new UnsupportedOperationException(); }
    @Override public Optional<ChatSessionRow> latestSession(String memberId) { throw new UnsupportedOperationException(); }
    @Override public List<com.zoop.chat.repository.ChatSessionSummaryRow> sessions(String memberId, Instant afterUpdatedAt,
            String afterId, int limit) { throw new UnsupportedOperationException(); }
    @Override public boolean deleteSession(String sessionId) { throw new UnsupportedOperationException(); }
    @Override public int countJobs(String sessionId) { throw new UnsupportedOperationException(); }
    @Override public List<ChatJobRow> jobs(String sessionId) { throw new UnsupportedOperationException(); }
    @Override public Optional<ChatJobRow> activeJob(String sessionId) { throw new UnsupportedOperationException(); }
    @Override public int nextSeq(String sessionId) { throw new UnsupportedOperationException(); }
    @Override public boolean insertJob(NewChatJob job) { throw new UnsupportedOperationException(); }
    @Override public boolean cancel(String jobId, Instant at, String attempts) { throw new UnsupportedOperationException(); }
    @Override public boolean requeue(String jobId, Instant at, String attempts) { throw new UnsupportedOperationException(); }
}
