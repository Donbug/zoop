package com.zoop.chat.repository;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

public interface ChatRepository {
    Optional<ChatSessionRow> findSession(String sessionId);

    /** The conversation row locked for this transaction: every job write of a conversation goes through this lock. */
    Optional<ChatSessionRow> lockSession(String sessionId);

    /** False when a conversation with this id already exists (of any member). */
    boolean insertSession(ChatSessionRow session);

    void touchSession(String sessionId, Instant at);

    Optional<ChatSessionRow> latestSession(String memberId);

    /**
     * The member's conversations that hold at least one question, latest change first ({@code updated_at}, then id, both
     * descending), strictly after the given position when one is given.
     */
    List<ChatSessionSummaryRow> sessions(String memberId, Instant afterUpdatedAt, String afterId, int limit);

    /** Deletes the conversation with its jobs and their tool calls; false when it no longer exists. */
    boolean deleteSession(String sessionId);

    int countJobs(String sessionId);

    List<ChatJobRow> jobs(String sessionId);

    Optional<ChatJobRow> findJob(String jobId);

    Optional<ChatJobRow> activeJob(String sessionId);

    int nextSeq(String sessionId);

    /** False when the id or the conversation's single active slot is already taken. */
    boolean insertJob(NewChatJob job);

    /** queued/running → cancelled; false when the job was no longer active. */
    boolean cancel(String jobId, Instant at, String attempts);

    /** failed → queued for an allowed retry; false when the job was no longer failed. */
    boolean requeue(String jobId, Instant at, String attempts);
}
