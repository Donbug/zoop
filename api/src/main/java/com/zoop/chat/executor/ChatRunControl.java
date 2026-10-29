package com.zoop.chat.executor;

import com.zoop.chat.repository.ChatToolCallEnd;
import java.time.Duration;
import java.util.List;

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

    /** Whether this run still owns the job; false after a cancel, an expired lease or a newer run. */
    boolean owned();

    /**
     * Records a confirmed plan's calls as {@code reserved} {@code chat_tool_calls} rows of this attempt, continuing its call
     * index, and returns their tool-call ids in order. An attempt holds at most {@link #MAX_TOOL_CALLS} calls across plan
     * revisions; a plan that would exceed it is refused with {@link IllegalArgumentException} and nothing is reserved.
     */
    List<String> reserveToolCalls(int planRevision, List<ChatToolCallReservation> calls);

    /** reserved → running, just before the call is made. */
    void toolCallStarted(String toolCallId);

    /** running → succeeded|failed. */
    void toolCallFinished(String toolCallId, ChatToolCallEnd end);

    /**
     * Tool calls one attempt may make, supplementary rounds, failures and agent approvals included (MCP actions contract 3.2:
     * 8 per job, at most 6 internal and 2 web). Every bound read is internal until a web search tool exists, so the cap is
     * the internal 6; the 2 web calls come with that tool, counted apart.
     */
    int MAX_TOOL_CALLS = 6;
}
