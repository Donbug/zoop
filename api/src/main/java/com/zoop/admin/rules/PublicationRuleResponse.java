package com.zoop.admin.rules;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.util.List;

/** OpenAPI {@code RuleList}, {@code ReviewRuleOut}, {@code RuleChangeOut}, {@code RuleSwitchRequest} and {@code RuleSwitchResponse}. */
public final class PublicationRuleResponse {
    private PublicationRuleResponse() {
    }

    public record RuleList(List<RuleOut> items, String asOf, String nextCursor) {
    }

    /**
     * {@code eligible} needs the AI source projection ({@code review_targets} with source revisions, stage 4) and
     * {@code publishedCandidates}/{@code publishedEvents} are frozen with a graph version by the import path (#146), so all
     * three are null until then rather than zero.
     */
    public record RuleOut(String title, String id, String summary, boolean enabled, boolean defaultEnabled, String changedAt,
            String changedBy, String reason, Integer eligible, Integer publishedCandidates, Integer publishedEvents,
            List<RuleChangeOut> history) {
    }

    public record RuleChangeOut(long id, boolean enabled, String reason, String adminEmail, String changedAt) {
    }

    /** {@code reason} is checked for length after stripping (the stored value), in the service. */
    public record SwitchRequest(@NotNull Boolean enabled, @NotBlank String reason) {
    }

    /** {@code idempotent}: the rule already had this state, so nothing was recorded. */
    public record SwitchResponse(RuleOut rule, boolean idempotent, long reviewRevision) {
    }
}
