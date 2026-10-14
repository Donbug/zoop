package com.zoop.document.analysis;

import java.util.List;
import java.util.Map;

/**
 * Outcome of one operator run. {@code requestFailure} is set when the request as a whole could not run (invalid request, busy
 * store, unusable grant registry); otherwise {@code items} has one entry per request item, in order, and the run failed exactly
 * when one of them is {@link AnalysisItemResult.Failed}. {@code command} is null when the request could not be read.
 */
public record AnalysisRunResult(String command, AnalysisFailure requestFailure, Map<String, String> requestDetails,
        List<AnalysisItemResult> items) {

    public AnalysisRunResult {
        requestDetails = Map.copyOf(requestDetails);
        items = List.copyOf(items);
    }

    public static AnalysisRunResult requestFailed(String command, AnalysisFailure failure, Map<String, String> details,
            List<AnalysisItemResult> items) {
        return new AnalysisRunResult(command, failure, details, items);
    }

    public boolean succeeded() {
        return requestFailure == null && items.stream().noneMatch(item -> item instanceof AnalysisItemResult.Failed);
    }

    /** The code that decided the exit status: the request-level failure or the first failed item's. */
    public AnalysisFailure firstFailure() {
        if (requestFailure != null) {
            return requestFailure;
        }
        return items.stream().filter(item -> item instanceof AnalysisItemResult.Failed)
                .map(item -> ((AnalysisItemResult.Failed) item).failure()).findFirst().orElse(null);
    }
}
