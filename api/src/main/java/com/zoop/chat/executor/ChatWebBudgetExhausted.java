package com.zoop.chat.executor;

/**
 * Web searches were refused before anything was reserved: the job's {@link ChatRunControl#MAX_WEB_CALLS}, or the KST day's
 * quota of the member ({@link ChatRunControl#MEMBER_DAILY_WEB_CALLS}) or of the project
 * ({@link ChatRunControl#PROJECT_DAILY_WEB_CALLS}) has too few left. It is never a job failure: the answer goes on without
 * the web, with a {@code web_budget_exhausted} notice (web search design 3 and 4).
 */
public final class ChatWebBudgetExhausted extends RuntimeException {
    /** Which budget had too few left. */
    public enum Budget { JOB, MEMBER, PROJECT }

    private final Budget budget;

    public ChatWebBudgetExhausted(Budget budget) {
        super("web search budget exhausted: " + budget);
        this.budget = budget;
    }

    public Budget budget() {
        return budget;
    }
}
