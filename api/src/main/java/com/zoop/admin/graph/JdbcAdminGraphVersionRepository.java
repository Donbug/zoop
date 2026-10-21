package com.zoop.admin.graph;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.Set;

import com.zoop.admin.graph.GraphVersionAdminResponse.ActivationOut;
import com.zoop.admin.graph.GraphVersionAdminResponse.GraphDbVersionState;
import com.zoop.admin.graph.GraphVersionAdminResponse.GraphVersionOut;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

/** Admin reads of {@code graph_versions}/{@code graph_activations} and the activation idempotency records. */
@Repository
public class JdbcAdminGraphVersionRepository {
    /** Recent pointer history shown next to the version list; it is not paged with the versions. */
    static final int ACTIVATION_HISTORY_LIMIT = 50;
    private static final Set<String> GRAPH_DB_STATUSES = Set.of("reflected", "pending", "unknown");

    private final NamedParameterJdbcTemplate jdbc;

    public JdbcAdminGraphVersionRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** Versions below {@code beforeSequence} (null for the first page), newest first, at most {@code limit} rows. */
    public List<GraphVersionOut> versions(Long beforeSequence, int limit) {
        return jdbc.query("""
                SELECT v.id, v.sequence, v.kind, v.created_at, v.created_by, v.reason, v.source_label,
                       v.policy_version, v.issue_count, v.relation_count, v.article_count, v.candidate_count,
                       a.sha256, a.bytes, v.active,
                       (SELECT max(g.activated_at) FROM graph_activations g
                        WHERE g.version_id = v.id AND g.pointer_changed) AS activated_at,
                       v.graph_db_state->>'status' AS graph_db_status,
                       v.graph_db_state->>'pendingJobsAtCreation' AS graph_db_pending,
                       v.graph_db_state->>'note' AS graph_db_note
                FROM graph_versions v JOIN artifacts a ON a.id = v.snapshot_artifact_id
                WHERE CAST(:before AS bigint) IS NULL OR v.sequence < :before
                ORDER BY v.sequence DESC
                LIMIT :limit
                """, new MapSqlParameterSource("before", beforeSequence).addValue("limit", limit),
                JdbcAdminGraphVersionRepository::version);
    }

    public List<ActivationOut> activations() {
        return jdbc.query("""
                SELECT version_id, previous_version_id, activated_at, admin_email_snapshot, reason, action
                FROM graph_activations
                ORDER BY activated_at DESC, id DESC
                LIMIT :limit
                """, new MapSqlParameterSource("limit", ACTIVATION_HISTORY_LIMIT), (rs, rowNum) -> new ActivationOut(
                        rs.getString("version_id"), rs.getString("previous_version_id"),
                        rs.getTimestamp("activated_at").toInstant(), rs.getString("admin_email_snapshot"),
                        rs.getString("reason"), rs.getString("action")));
    }

    public boolean claimIdempotency(String id, String adminId, String path, String key, String versionId,
            String requestHash, Instant createdAt) {
        return jdbc.update("""
                INSERT INTO idempotency_records
                  (id, principal_kind, principal_id, method, path, idem_key, request_hash,
                   status, resource_type, resource_id, owner_token, lease_until,
                   response_status, response_body, created_at, expires_at)
                VALUES (:id, 'admin', :adminId, 'POST', :path, :key, :requestHash,
                        'processing', 'graph_version', :versionId, NULL, NULL, NULL, NULL, :createdAt, NULL)
                ON CONFLICT (principal_kind, principal_id, method, path, idem_key) DO NOTHING
                """, new MapSqlParameterSource("id", id).addValue("adminId", adminId).addValue("path", path)
                .addValue("key", key).addValue("versionId", versionId).addValue("requestHash", requestHash)
                .addValue("createdAt", Timestamp.from(createdAt))) == 1;
    }

    public Optional<IdempotencyRow> findIdempotencyForUpdate(String adminId, String path, String key) {
        return jdbc.query("""
                SELECT id, request_hash, status, response_body::text AS response_body
                FROM idempotency_records
                WHERE principal_kind = 'admin' AND principal_id = :adminId
                  AND method = 'POST' AND path = :path AND idem_key = :key
                FOR UPDATE
                """, new MapSqlParameterSource("adminId", adminId).addValue("path", path).addValue("key", key),
                (rs, rowNum) -> new IdempotencyRow(rs.getString("id"), rs.getString("request_hash"),
                        rs.getString("status"), rs.getString("response_body"))).stream().findFirst();
    }

    public void completeIdempotency(String id, String responseBody) {
        int changed = jdbc.update("""
                UPDATE idempotency_records
                SET status = 'completed', response_status = 200, response_body = CAST(:responseBody AS jsonb)
                WHERE id = :id AND status = 'processing'
                """, new MapSqlParameterSource("id", id).addValue("responseBody", responseBody));
        if (changed != 1) throw new IllegalStateException("Idempotency record was not completed");
    }

    private static GraphVersionOut version(ResultSet rs, int rowNumber) throws SQLException {
        long candidates = rs.getLong("candidate_count");
        Long candidateCount = rs.wasNull() ? null : candidates;
        Timestamp activatedAt = rs.getTimestamp("activated_at");
        String status = rs.getString("graph_db_status");
        String pending = rs.getString("graph_db_pending");
        return new GraphVersionOut(rs.getString("id"), rs.getLong("sequence"), rs.getString("kind"),
                rs.getTimestamp("created_at").toInstant(), rs.getString("created_by"), rs.getString("reason"),
                rs.getString("source_label"), rs.getString("policy_version"), rs.getLong("issue_count"),
                rs.getLong("relation_count"), rs.getLong("article_count"), candidateCount, rs.getString("sha256"),
                rs.getLong("bytes"), rs.getBoolean("active"), activatedAt == null ? null : activatedAt.toInstant(),
                new GraphDbVersionState(status != null && GRAPH_DB_STATUSES.contains(status) ? status : "unknown",
                        pending != null && pending.matches("[0-9]{1,18}") ? Long.valueOf(pending) : null,
                        rs.getString("graph_db_note")));
    }

    public record IdempotencyRow(String id, String requestHash, String status, String responseBody) { }
}
