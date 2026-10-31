package com.zoop.chat.service;

import com.zoop.chat.tool.ChatSelectionRecord;
import java.sql.Timestamp;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * The recorded publication of an issue at a graph version, read for the chatbot (Q08): the version's pinned review and rule
 * revisions, the last review decision on the issue's candidate up to that review revision, and the exact rules the version
 * was filtered with ({@code graph_version_rules}). Only the decision, its time and its path leave this class: never the
 * administrator or the reason they wrote (user decision 2026-10-30).
 */
@Repository
public class ChatPublicationRecords {
    private final NamedParameterJdbcTemplate jdbc;

    public ChatPublicationRecords(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** Empty when the version does not exist. */
    public Optional<ChatSelectionRecord.Publication> publication(String graphVersionId, String issueId, String issueTitle) {
        var params = new MapSqlParameterSource().addValue("version", graphVersionId).addValue("issue", issueId);
        var pins = jdbc.query("SELECT review_revision, rule_revision FROM graph_versions WHERE id = :version", params,
                (rs, i) -> new long[] {rs.getLong("review_revision"), rs.getObject("rule_revision") == null ? -1
                        : rs.getLong("rule_revision")});
        if (pins.isEmpty()) return Optional.empty();
        long review = pins.getFirst()[0];
        Long rule = pins.getFirst()[1] < 0 ? null : pins.getFirst()[1];
        params.addValue("review", review);
        record Decision(String decision, Timestamp at, String origin) { }
        List<Decision> decisions = jdbc.query("""
                SELECT d.decision, d.decided_at, d.origin
                  FROM review_decisions d JOIN review_targets t ON t.id = d.target_id
                 WHERE t.target_type = 'candidate' AND t.issue_id = :issue AND d.global_revision <= :review
                 ORDER BY d.global_revision DESC
                 LIMIT 1
                """, params, (rs, i) -> new Decision(rs.getString("decision"), rs.getTimestamp("decided_at"),
                rs.getString("origin")));
        List<ChatSelectionRecord.Rule> rules = jdbc.query("""
                SELECT r.id, r.title, r.summary
                  FROM graph_version_rules g JOIN publication_rules r ON r.id = g.rule_id
                 WHERE g.graph_version_id = :version
                 ORDER BY r.id
                """, params, (rs, i) -> new ChatSelectionRecord.Rule(rs.getString("id"), rs.getString("title"),
                rs.getString("summary")));
        if (decisions.isEmpty()) {
            return Optional.of(new ChatSelectionRecord.Publication(issueId, issueTitle, graphVersionId, review, rule, null,
                    "none", null, rules));
        }
        var d = decisions.getFirst();
        String path = "admin".equals(d.origin()) ? "admin_review" : "snapshot_migration";
        return Optional.of(new ChatSelectionRecord.Publication(issueId, issueTitle, graphVersionId, review, rule,
                d.decision(), path, d.at().toInstant(), rules));
    }
}
