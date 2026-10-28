package com.zoop.admin.ai;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;

/** FS068 / A-ADM-04b response. Unknown measurements stay null, with availability carried beside them. */
public record AiUsageResponse(String availability, List<String> unavailableMetrics, Instant asOf, String window,
        List<Feature> features, List<Object> pastRuns, Cost cost, List<Object> daily, Object members) {
    public record Feature(String availability, List<String> unavailableMetrics, String feature, String label,
            String engine, boolean modelBacked, Long requests, Long succeeded, Long failed, Latency latencyMs,
            Usage usage, Cost cost, String source, List<RecentError> recentErrors, String note) { }

    public record Latency(double avg, double p95, double max) { }

    public record Usage(Long modelCalls, Long inputTokens, Long outputTokens, Long replayCalls, Long retries) { }

    public record Cost(String status, BigDecimal actual, BigDecimal estimated, String currency, String reason) { }

    public record RecentError(Instant at, String code, String message) { }
}
