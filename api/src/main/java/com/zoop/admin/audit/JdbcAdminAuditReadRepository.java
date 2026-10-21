package com.zoop.admin.audit;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcAdminAuditReadRepository implements AdminAuditReadRepository {
    private final NamedParameterJdbcTemplate jdbc;

    public JdbcAdminAuditReadRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public List<AuditRecord> page(String action, String actor, String targetType, String query,
            Instant asOf, Instant afterAt, Long afterId, int limit) {
        // Only a purpose-bound reason is searchable. An excluded historical reason must not
        // disclose its contents through the presence of a search result.
        return jdbc.query("""
                WITH visible AS (
                  SELECT id, occurred_at, actor_kind, actor_id, actor_email_snapshot,
                         action, target_type, target_id, outcome, detail,
                         CASE
                           WHEN action = 'auth.login_failed'
                                AND reason IN ('invalid_credentials', 'account_blocked') THEN reason
                           WHEN action = 'admin.provision'
                                AND reason = 'email_already_registered' THEN reason
                           WHEN action IN ('member.block', 'member.unblock')
                                AND reason IS NOT NULL
                                AND reason !~* '(password|token|cookie|authorization|bearer|api[_-]?key|https?://|@|[[:alnum:]_-]{32,}|[[:cntrl:]])'
                                THEN reason
                           ELSE NULL
                         END AS public_reason
                  FROM audit_logs
                  WHERE occurred_at <= :asOf
                )
                SELECT id, occurred_at, actor_kind, actor_id, actor_email_snapshot,
                       action, target_type, target_id, outcome, detail::text AS detail_json,
                       public_reason
                FROM visible
                WHERE (CAST(:action AS text) IS NULL OR action = CAST(:action AS text))
                  AND (CAST(:actor AS text) IS NULL OR actor_id = CAST(:actor AS text)
                       OR actor_email_snapshot = CAST(:actor AS text))
                  AND (CAST(:targetType AS text) IS NULL OR target_type = CAST(:targetType AS text))
                  AND (CAST(:query AS text) IS NULL OR lower(action) LIKE CAST(:query AS text) ESCAPE '!'
                       OR lower(actor_id) LIKE CAST(:query AS text) ESCAPE '!'
                       OR lower(actor_email_snapshot) LIKE CAST(:query AS text) ESCAPE '!'
                       OR lower(target_id) LIKE CAST(:query AS text) ESCAPE '!'
                       OR lower(public_reason) LIKE CAST(:query AS text) ESCAPE '!')
                  AND (CAST(:afterAt AS timestamptz) IS NULL
                       OR occurred_at < CAST(:afterAt AS timestamptz)
                       OR (occurred_at = CAST(:afterAt AS timestamptz) AND id < CAST(:afterId AS bigint)))
                ORDER BY occurred_at DESC, id DESC
                LIMIT :limit
                """, new MapSqlParameterSource()
                .addValue("action", action).addValue("actor", actor)
                .addValue("targetType", targetType).addValue("query", query)
                .addValue("asOf", Timestamp.from(asOf))
                .addValue("afterAt", afterAt == null ? null : Timestamp.from(afterAt))
                .addValue("afterId", afterId).addValue("limit", limit),
                (rs, ignored) -> new AuditRecord(rs.getLong("id"),
                        rs.getTimestamp("occurred_at").toInstant(), rs.getString("actor_kind"),
                        rs.getString("actor_id"), rs.getString("actor_email_snapshot"),
                        rs.getString("action"), rs.getString("target_type"),
                        rs.getString("target_id"), rs.getString("public_reason"),
                        rs.getString("outcome"), rs.getString("detail_json")));
    }
}
