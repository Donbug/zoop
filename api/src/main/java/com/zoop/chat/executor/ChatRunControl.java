package com.zoop.chat.executor;

import com.zoop.chat.repository.ChatToolCallEnd;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

/**
 * What an engine may do to the job it runs. Every write is fenced by the run's owner token and unexpired lease: after a
 * cancel, a lease expiry or a newer run, it throws {@link ChatRunSuperseded} and nothing changes.
 */
public interface ChatRunControl {
    /** Public progress: {@code planning}, {@code retrieving}, {@code writing} or {@code verifying}. */
    void phase(String phase);

    /**
     * Must be called, and must return, before every model request is sent. The first call of a run counts it in
     * {@code runs}; once called, an interrupted run can no longer be rerun because the provider may have processed it.
     */
    void beforeModelCall();

    /** Time left until the run's deadline (zero or negative once passed). */
    Duration remaining();

    /**
     * Brings the run's deadline forward to {@code deadline} (never later): from then on {@link #remaining}, every fenced
     * record, a tool request reaching the run from outside and the final store keep to it, so a result past it is not stored
     * as completed. Throws {@link ChatRunSuperseded} when the run no longer owns the job.
     */
    void shortenDeadline(Instant deadline);

    /** Whether this run still owns the job; false after a cancel, an expired lease or a newer run. */
    boolean owned();

    /**
     * Calls the job may still reserve: {@link #MAX_TOOL_CALLS} less this attempt's reservations and the calls its earlier
     * attempts made. A rerun does not open a new budget.
     */
    int toolCallsLeft();

    /**
     * Records a confirmed plan's calls as {@code reserved} {@code chat_tool_calls} rows of this attempt, continuing its call
     * index, and returns their tool-call ids in order. A job holds at most {@link #MAX_TOOL_CALLS} calls across plan
     * revisions and attempts ({@link #toolCallsLeft}); a plan that would exceed it is refused with
     * {@link IllegalArgumentException} and nothing is reserved.
     */
    List<String> reserveToolCalls(int planRevision, List<ChatToolCallReservation> calls);

    /** reserved → running, just before the call is made. */
    void toolCallStarted(String toolCallId);

    /**
     * reserved → running for this attempt's first call still reserved for exactly this capability and input digest, picked
     * and started in one step, so requests arriving together each start a different one; empty when none is left (never
     * reserved, or all already started).
     */
    Optional<String> claimToolCall(String capabilityId, String inputDigest);

    /**
     * running → succeeded|failed. A success that keeps a result is recorded only while it fits, measured as the database
     * stores it (its JSON text after storing): within {@link #MAX_CALL_RESULT_BYTES} itself, and with every result the job
     * kept within {@link #MAX_KEPT_RESULT_BYTES}. Otherwise the call is recorded {@code failed} with
     * {@link #RESULT_TOO_LARGE} or {@link #RESULTS_OVER_BUDGET} and {@link ChatToolCallRefused} is thrown, so the result is
     * never delivered.
     */
    void toolCallFinished(String toolCallId, ChatToolCallEnd end);

    /** One kept result, as stored ({@code chat_tool_calls.result}'s own limit). */
    int MAX_CALL_RESULT_BYTES = 256 * 1024;

    /** The failure of a call whose kept result would be over {@link #MAX_CALL_RESULT_BYTES}. */
    String RESULT_TOO_LARGE = "result_too_large";

    /** All results one job's calls keep for a model (MCP results, as stored), across its attempts (MCP actions 3.2). */
    int MAX_KEPT_RESULT_BYTES = 1024 * 1024;

    /** The failure of a call whose result would take the job's kept results past {@link #MAX_KEPT_RESULT_BYTES}. */
    String RESULTS_OVER_BUDGET = "job_results_too_large";

    /**
     * Tool calls one job may make across its attempts, supplementary rounds, failures and agent approvals included (MCP
     * actions contract 3.2: 8 per job, at most 6 internal and 2 web). Every bound read is internal until a web search tool
     * exists, so the cap is the internal 6; the 2 web calls come with that tool, counted apart.
     */
    int MAX_TOOL_CALLS = 6;
}
