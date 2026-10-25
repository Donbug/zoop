package com.zoop.admin.jobs;

import java.time.Duration;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/** Consumer bounds, not source rights, admission quota or permission to spend. */
@ConfigurationProperties("zoop.analysis.analyze-plan")
public record AnalyzePlanProperties(
        @DefaultValue("false") boolean enabled,
        String expectedPrincipal,
        @DefaultValue("2s") Duration pollInterval,
        @DefaultValue("30m") Duration attemptDeadline,
        @DefaultValue("150s") Duration lease,
        @DefaultValue("5") int maxConsecutiveFailures,
        @DefaultValue("3") int maxRecoveryDispatches,
        @DefaultValue("16") int maxReclaims) {

    public AnalyzePlanProperties {
        bounded("poll-interval", pollInterval, Duration.ofMillis(100), Duration.ofSeconds(30));
        bounded("attempt-deadline", attemptDeadline, Duration.ofSeconds(1), Duration.ofHours(24));
        bounded("lease", lease, Duration.ofSeconds(1), Duration.ofHours(1));
        if (maxConsecutiveFailures < 1 || maxConsecutiveFailures > 100
                || maxRecoveryDispatches < 1 || maxRecoveryDispatches > 100
                || maxReclaims < 1 || maxReclaims > 1000) {
            throw new IllegalArgumentException("zoop.analysis.analyze-plan: invalid finite attempt bounds");
        }
        if (enabled && (expectedPrincipal == null
                || !com.zoop.ai.plan.PlanIdentity.PRINCIPAL.matcher(expectedPrincipal).matches())) {
            throw new IllegalArgumentException("zoop.analysis.analyze-plan.expected-principal is required and must be a service principal");
        }
    }

    private static void bounded(String name, Duration value, Duration minimum, Duration maximum) {
        if (value == null || value.compareTo(minimum) < 0 || value.compareTo(maximum) > 0) {
            throw new IllegalArgumentException("zoop.analysis.analyze-plan." + name + " is outside its finite bounds");
        }
    }
}
