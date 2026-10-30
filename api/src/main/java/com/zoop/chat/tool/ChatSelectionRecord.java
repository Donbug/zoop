package com.zoop.chat.tool;

import java.time.Instant;
import java.time.LocalDate;
import java.util.List;

/**
 * A recorded reason an issue is where the member saw it (Q08, governance policy 6.3.1: recorded rules and decisions, never
 * a reason made up), as {@code selectionRule.read} found it. It travels with the read's result for the server's checks
 * and the verifier's facts; the model sees the item label made from it.
 */
public sealed interface ChatSelectionRecord {
    String issueId();

    String issueTitle();

    /** One publication rule a graph version was filtered with: id, title and summary as the rule states them. */
    record Rule(String ruleId, String title, String summary) { }

    /**
     * Why an issue is on the public map at a graph version: the last review decision on it up to the version's pinned review
     * revision ({@code decision} allow or reject; {@code decisionPath} admin_review, snapshot_migration or none when no
     * decision is recorded) and the publication rules the version was filtered with. Who decided, and the decider's own
     * note, are never part of it.
     */
    record Publication(String issueId, String issueTitle, String graphVersionId, long reviewRevision, Long ruleRevision,
            String decision, String decisionPath, Instant decidedAt, List<Rule> rules) implements ChatSelectionRecord {
        public Publication {
            rules = List.copyOf(rules);
            if (!List.of("admin_review", "snapshot_migration", "none").contains(decisionPath)) {
                throw new IllegalArgumentException("unknown decision path");
            }
            if (("none".equals(decisionPath)) != (decision == null) || (decision == null) != (decidedAt == null)) {
                throw new IllegalArgumentException("a decision has its path and time, and no decision has neither");
            }
        }
    }

    /** Why an issue was picked for a published briefing round: its rank and the selection reason the round recorded. */
    record BriefingSelection(String issueId, String issueTitle, String roundId, LocalDate date, String edition, int rank,
            String reason) implements ChatSelectionRecord { }
}
