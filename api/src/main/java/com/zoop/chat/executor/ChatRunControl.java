package com.zoop.chat.executor;

import java.time.Duration;

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
}
