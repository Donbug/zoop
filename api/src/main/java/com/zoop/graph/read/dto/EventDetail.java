package com.zoop.graph.read.dto;

import com.zoop.common.response.Metadata;
import java.util.List;

/**
 * OpenAPI {@code EventDetail} ({@code getEvent}); every key is serialized, nulls included. {@code summary} is either an
 * analysis summary or {@link Unavailable}; no producer writes an event summary yet, so it is always unavailable for now.
 */
public record EventDetail(String title, String id, String eventTime, String timePrecision, String period,
        List<MentionOut> mentions, List<ArticleOut> articles, List<RelationOut> relations, List<CompanyLink> companies,
        SourceSupportOut sourceSupport, List<FieldDecisionOut> fieldDecisions, List<String> evidenceIds, Follows follows,
        ApprovalOut approval, Object summary, Metadata metadata) {

    /** One original S2 mention as the AI handoff gave it (verification none); a field an operator held or rejected is null. */
    public record MentionOut(String title, String mentionId, String articleId, String action, String target,
            String eventTime, String timePrecision, String period, String assertionStatus, List<Participant> participants,
            List<String> evidenceIds, boolean background) { }

    /** A mention participant as S2 wrote it; companyId only when it maps to a public company of this version. */
    public record Participant(String companyId, String name, String role, boolean roleUnconfirmed) { }

    public record ArticleOut(String title, String id, String publisher, String url, String publishedAt,
            String relationType) { }

    /** edgeId is the display edge of the graph for this source relation. */
    public record RelationOut(String id, String edgeId, String relationType, String source, String target, String role,
            boolean roleUnconfirmed, String assertionStatus, List<String> evidenceIds) { }

    public record CompanyLink(String id, String name, String role, boolean roleUnconfirmed, String relationType) { }

    /** Copied from the AI handoff issue; null counts mean unknown (never zero by guess). */
    public record SourceSupportOut(int articleCount, Integer knownLineageCount, List<String> unknownLineageArticles,
            Integer independentSourceCount, List<List<String>> duplicateGroups) { }

    /** Operator field verdicts of one mention; candidateId is null because no candidate store exists. */
    public record FieldDecisionOut(String candidateId, String mentionId, List<FieldOutcome> outcomes) { }

    public record FieldOutcome(String field, String decision, String reason) { }

    public record Follows(List<FollowRef> previous, List<FollowRef> next) { }

    public record FollowRef(String title, String id, String eventTime, String timePrecision) { }

    public record Unavailable(String status, String reason) { }

    /** Retained approval provenance: native administrator review or the legacy BFF's named effective publication rule. */
    public record ApprovalOut(String source, String label, String scope, String ruleId) { }
}
