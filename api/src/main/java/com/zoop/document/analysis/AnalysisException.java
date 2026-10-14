package com.zoop.document.analysis;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * One request or item failed in a defined way. The message is the code only. The details are a few identifiers (an AI or grant
 * code, an analysis id, a status): each value is a plain token or the word {@code redacted}, so that nothing else can ride along
 * into a log or the result file. It has no cause and no stack trace.
 *
 * <p>Thrown inside the settlement transaction it means "rolled back"; the caller then removes the files it had created for it.
 */
public final class AnalysisException extends RuntimeException {
    private static final Pattern TOKEN = Pattern.compile("[A-Za-z0-9_.:-]{1,80}");

    private final AnalysisFailure failure;
    private final Map<String, String> details;

    public AnalysisException(AnalysisFailure failure) {
        this(failure, Map.of());
    }

    public AnalysisException(AnalysisFailure failure, Map<String, String> details) {
        super(failure.code(), null, false, false);
        this.failure = failure;
        Map<String, String> safe = new LinkedHashMap<>();
        details.forEach((key, value) -> safe.put(key, value != null && TOKEN.matcher(value).matches() ? value : "redacted"));
        this.details = Map.copyOf(safe);
    }

    public static AnalysisException of(AnalysisFailure failure, String key, String value) {
        Map<String, String> details = new LinkedHashMap<>();
        details.put(key, value);
        return new AnalysisException(failure, details);
    }

    public AnalysisFailure failure() {
        return failure;
    }

    public Map<String, String> details() {
        return details;
    }
}
