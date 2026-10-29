package com.zoop.chat.executor;

/**
 * A tool call's end was recorded as a failure with {@code code} instead of the success it was asked to record, because a limit
 * of the job only the record can check atomically refused it ({@link ChatRunControl#RESULTS_OVER_BUDGET}). The caller reports
 * that failure; nothing of the refused result is delivered.
 */
public final class ChatToolCallRefused extends RuntimeException {
    private final String code;

    public ChatToolCallRefused(String code) {
        super(code, null, false, false);
        this.code = code;
    }

    public String code() {
        return code;
    }
}
