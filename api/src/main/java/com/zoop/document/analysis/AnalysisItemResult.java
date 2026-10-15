package com.zoop.document.analysis;

import java.util.Map;

/**
 * What happened to one request item. Only identifiers and states; never text, paths, credentials or model output.
 *
 * <p>{@link Pending} is a success: the AI job is not finished and the item can be advanced again. {@link Failed} means the item
 * wrote nothing (or, for {@code database_unavailable}, that its outcome is unknown).
 */
public sealed interface AnalysisItemResult {

    int index();

    /** A pending analysis with its issued AI job id is committed; no AI request has been made. */
    record Prepared(int index, String analysisId, String aiJobId, long requestNo, String stage) implements AnalysisItemResult {
    }

    /**
     * The analysis reached its terminal state: {@code available}, {@code withheld} or {@code failed}, with the machine
     * {@code reason} (null for available). The counters are what this settlement added.
     */
    record Settled(int index, String analysisId, String outcome, String reason, int executionsRecorded,
            int executionsExisting, int evidence) implements AnalysisItemResult {
    }

    /** The AI job is not finished: {@code wait}, {@code receipts_incomplete} or {@code recovering}. Nothing was written. */
    record Pending(int index, String analysisId, String aiJobId, String waiting) implements AnalysisItemResult {
    }

    /** The analysis was already terminal; nothing was called or written. */
    record AlreadySettled(int index, String analysisId, String outcome, String reason) implements AnalysisItemResult {
    }

    record Failed(int index, AnalysisFailure failure, Map<String, String> details) implements AnalysisItemResult {
        public Failed {
            details = Map.copyOf(details);
        }
    }

    /** An earlier item failed, so this one was not started. */
    record NotAttempted(int index) implements AnalysisItemResult {
    }
}
