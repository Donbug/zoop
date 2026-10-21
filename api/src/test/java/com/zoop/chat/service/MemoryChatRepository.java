package com.zoop.chat.service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import com.zoop.chat.repository.ChatJobRow;
import com.zoop.chat.repository.ChatRepository;
import com.zoop.chat.repository.ChatSessionRow;
import com.zoop.chat.repository.NewChatJob;

/** In-memory {@link ChatRepository} with the table's uniqueness rules: job id, and one queued/running job per conversation. */
final class MemoryChatRepository implements ChatRepository {
    final Map<String, ChatSessionRow> sessions = new LinkedHashMap<>();
    final Map<String, ChatJobRow> jobs = new LinkedHashMap<>();

    @Override
    public Optional<ChatSessionRow> findSession(String sessionId) {
        return Optional.ofNullable(sessions.get(sessionId));
    }

    @Override
    public Optional<ChatSessionRow> lockSession(String sessionId) {
        return findSession(sessionId);
    }

    @Override
    public boolean insertSession(ChatSessionRow session) {
        return sessions.putIfAbsent(session.id(), session) == null;
    }

    @Override
    public void touchSession(String sessionId, Instant at) {
        var session = sessions.get(sessionId);
        if (at.isAfter(session.updatedAt())) {
            sessions.put(sessionId, new ChatSessionRow(session.id(), session.memberId(), session.createdAt(), at));
        }
    }

    @Override
    public Optional<ChatSessionRow> latestSession(String memberId) {
        return sessions.values().stream().filter(s -> s.memberId().equals(memberId))
                .max(Comparator.comparing(ChatSessionRow::updatedAt).thenComparing(ChatSessionRow::id));
    }

    @Override
    public int countJobs(String sessionId) {
        return jobs(sessionId).size();
    }

    @Override
    public List<ChatJobRow> jobs(String sessionId) {
        return jobs.values().stream().filter(j -> j.sessionId().equals(sessionId))
                .sorted(Comparator.comparingInt(ChatJobRow::seq)).toList();
    }

    @Override
    public Optional<ChatJobRow> findJob(String jobId) {
        return Optional.ofNullable(jobs.get(jobId));
    }

    @Override
    public Optional<ChatJobRow> activeJob(String sessionId) {
        return jobs(sessionId).stream().filter(ChatJobRow::active).findFirst();
    }

    @Override
    public int nextSeq(String sessionId) {
        return jobs(sessionId).stream().mapToInt(ChatJobRow::seq).max().orElse(0) + 1;
    }

    @Override
    public boolean insertJob(NewChatJob job) {
        if (jobs.containsKey(job.id()) || activeJob(job.sessionId()).isPresent()) return false;
        jobs.put(job.id(), new ChatJobRow(job.id(), job.sessionId(), sessions.get(job.sessionId()).memberId(), job.seq(),
                job.question(), job.requestHash(), job.askedAt(), job.frozenContext(),
                new ArrayList<>(job.contextCompanyIds()), job.graphVersionId(), "queued", null, null, job.resolvesJobId(),
                job.resolvesChoiceId(), job.clarificationDepth(), null, null, 0, job.attempts(), job.askedAt(),
                job.askedAt(), null));
        return true;
    }

    @Override
    public boolean cancel(String jobId, Instant at, String attempts) {
        var job = jobs.get(jobId);
        if (job == null || !job.active()) return false;
        jobs.put(jobId, with(job, "cancelled", null, null, null, job.runs(), attempts, at, at));
        return true;
    }

    @Override
    public boolean requeue(String jobId, Instant at, String attempts) {
        var job = jobs.get(jobId);
        if (job == null || !"failed".equals(job.status())) return false;
        jobs.put(jobId, with(job, "queued", null, null, null, job.runs(), attempts, at, null));
        return true;
    }

    /** What the executor will do: finish a job with a stored result or failure (test setup only). */
    void finish(String jobId, String status, String outcome, String result, String failure, int runs) {
        var job = jobs.get(jobId);
        jobs.put(jobId, with(job, status, outcome, result, failure, runs, job.attempts(), job.updatedAt(), job.updatedAt()));
    }

    private static ChatJobRow with(ChatJobRow job, String status, String outcome, String result, String failure, int runs,
            String attempts, Instant updatedAt, Instant finishedAt) {
        return new ChatJobRow(job.id(), job.sessionId(), job.memberId(), job.seq(), job.question(), job.requestHash(),
                job.askedAt(), job.frozenContext(), job.contextCompanyIds(), job.graphVersionId(), status, null, outcome,
                job.resolvesJobId(), job.resolvesChoiceId(), job.clarificationDepth(), result, failure, runs, attempts,
                job.createdAt(), updatedAt, finishedAt);
    }
}
