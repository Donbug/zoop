package com.zoop.chat.repository;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

/**
 * The job executor's writes. Every write of a running job is fenced: it applies only while the job is still
 * {@code running} under the same owner token and an unexpired lease, so a cancelled, expired or replaced run changes nothing.
 * The {@code lock*} reads take the row lock and must run inside a transaction. Ending a job ({@link #complete},
 * {@link #fail}, {@link #failExpired}) also closes its open tool calls: reserved ones as {@code cancelled}, running ones as
 * {@code unknown}.
 */
public interface ChatExecutionRepository {
    /** The oldest queued job, locked; jobs another executor already locked are skipped. */
    Optional<ChatJobRow> lockNextQueued();

    /** queued → running under {@code ownerToken}; false when the job was no longer queued. */
    boolean start(String jobId, String ownerToken, Instant deadline, Instant leaseUntil, String attempts, Instant at);

    /** The job locked while this owner still holds an unexpired lease on it. */
    Optional<ChatJobRow> lockOwned(String jobId, String ownerToken, Instant at);

    /**
     * The job while it is running under an unexpired lease, with its owner token and deadline; not locked. A caller that
     * acts for the run (the MCP endpoint) still writes only through the fenced writes, so a run that ends meanwhile changes
     * nothing.
     */
    Optional<ChatRunningJob> findRunning(String jobId, Instant at);

    boolean phase(String jobId, String ownerToken, String phase, Instant at);

    /**
     * Brings the running job's deadline forward to {@code deadline} (never later), fenced like every run write; false when
     * the run no longer owns the job.
     */
    boolean shortenDeadline(String jobId, String ownerToken, Instant deadline, Instant at);

    /** Records that the run is about to call a model (after {@link #lockOwned} in the same transaction). */
    void recordModelCall(String jobId, int runs, String attempts, Instant at);

    boolean complete(String jobId, String ownerToken, Instant at, String outcome, String messageId, String result,
            String resultSchemaVersion, String routeSummary, String routeSchemaVersion, String attempts);

    boolean fail(String jobId, String ownerToken, Instant at, String failure, String attempts);

    /** Running jobs whose lease ran out, oldest first. */
    List<String> expired(Instant at, int limit);

    /** The job locked while it is still running with a lease that ran out. */
    Optional<ChatJobRow> lockExpired(String jobId, Instant at);

    boolean failExpired(String jobId, Instant at, String failure, String attempts);

    /**
     * Bounds every statement of the current transaction, lock waits included, to {@code wait}; a statement that runs out
     * fails instead of holding the run past its deadline.
     */
    void limitWait(Duration wait);

    /** How many tool calls the attempt has reserved so far (after {@link #lockOwned} in the same transaction). */
    int countToolCalls(String jobId, int attemptNo);

    /**
     * The job's tool calls that count against its budget: every call this attempt reserved, and those of its earlier
     * attempts that were made (all but {@code cancelled}, a reservation that never ran).
     */
    int countJobToolCalls(String jobId, int attemptNo);

    /** Stores reserved tool calls (after {@link #lockOwned} in the same transaction). */
    void reserveToolCalls(List<NewChatToolCall> calls, Instant at);

    /**
     * The oldest call of the attempt that is still {@code reserved} for exactly this capability and input digest; empty when
     * there is none (never reserved, already started or closed). Not locked: starting it is the fenced
     * {@link #startToolCall}, which only one caller wins.
     */
    Optional<String> findReservedToolCall(String jobId, int attemptNo, String capabilityId, String inputDigest);

    /** reserved → running, fenced like every run write; false when the run no longer owns the job. */
    boolean startToolCall(String jobId, String ownerToken, int attemptNo, String toolCallId, Instant at);

    /** The attempt's succeeded calls that kept their result (MCP calls), in call order. */
    List<ChatKeptToolResult> keptToolResults(String jobId, int attemptNo);

    /**
     * The attempt's first succeeded call of exactly this capability and input digest that kept its result: what an identical
     * request of the same attempt reuses instead of reading again.
     */
    Optional<ChatKeptToolResult> findKeptToolResult(String jobId, int attemptNo, String capabilityId, String inputDigest);

    /** Bytes of every result the job's calls kept, as stored, across its attempts (after {@link #lockOwned}). */
    long keptResultBytes(String jobId);

    /** running → succeeded|failed, fenced like every run write; false when the run no longer owns the job. */
    boolean finishToolCall(String jobId, String ownerToken, int attemptNo, String toolCallId, ChatToolCallEnd end,
            Instant at);
}
