package com.zoop.admin.dashboard.repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.Optional;

import com.zoop.admin.dashboard.dto.AdminDashboardResponse.DashboardActiveGraphVersion;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcAdminDashboardRepository implements AdminDashboardRepository {
    private final NamedParameterJdbcTemplate jdbc;

    public JdbcAdminDashboardRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public MemberCounts memberCountsAt(Instant asOf) {
        var parameters = new MapSqlParameterSource("asOf", Timestamp.from(asOf));
        return jdbc.queryForObject("""
                SELECT
                    (SELECT count(*) FROM members) AS registered,
                    (SELECT count(*) FROM member_sessions s
                        JOIN members m ON m.id = s.member_id
                        WHERE s.kind = 'member' AND m.status = 'active'
                          AND s.revoked_at IS NULL AND s.created_at <= :asOf AND s.expires_at > :asOf)
                        AS active_member_sessions,
                    (SELECT count(*) FROM member_sessions
                        WHERE kind = 'guest' AND revoked_at IS NULL
                          AND created_at <= :asOf AND expires_at > :asOf)
                        AS active_guest_sessions
                """, parameters, (rs, rowNum) -> new MemberCounts(
                rs.getLong("registered"), rs.getLong("active_member_sessions"),
                rs.getLong("active_guest_sessions")));
    }

    @Override
    public long auditCountBetween(Instant startInclusive, Instant endExclusive) {
        return jdbc.queryForObject("""
                SELECT count(*) FROM audit_logs
                WHERE occurred_at >= :start AND occurred_at < :end
                """, new MapSqlParameterSource()
                .addValue("start", Timestamp.from(startInclusive))
                .addValue("end", Timestamp.from(endExclusive)), Long.class);
    }

    @Override
    public GraphSummary graphSummaryAt(Instant asOf) {
        return jdbc.query("""
                WITH version_count AS (
                    SELECT count(*) AS total FROM graph_versions
                ), active_version AS (
                    SELECT v.id, v.sequence, v.kind, v.source_label, v.created_at, a.activated_at,
                           v.issue_count, v.relation_count, v.article_count
                    FROM graph_activations a
                    JOIN graph_versions v ON v.id = a.version_id
                    WHERE a.pointer_changed AND a.activated_at <= :asOf
                    ORDER BY a.activated_at DESC, a.id DESC
                    LIMIT 1
                )
                SELECT version_count.total AS version_count, active_version.*
                FROM version_count LEFT JOIN active_version ON TRUE
                """, new MapSqlParameterSource("asOf", Timestamp.from(asOf)), (rs, rowNum) -> {
                    String activeId = rs.getString("id");
                    Optional<DashboardActiveGraphVersion> active = activeId == null
                            ? Optional.empty()
                            : Optional.of(activeVersion(rs, rowNum));
                    return new GraphSummary(rs.getLong("version_count"), active);
                }).stream().findFirst().orElseThrow();
    }

    private static DashboardActiveGraphVersion activeVersion(ResultSet rs, int rowNum) throws SQLException {
        Timestamp activation = rs.getTimestamp("activated_at");
        return new DashboardActiveGraphVersion(rs.getString("id"), rs.getLong("sequence"),
                rs.getString("kind"), rs.getString("source_label"), rs.getTimestamp("created_at").toInstant(),
                activation == null ? null : activation.toInstant(), rs.getLong("issue_count"),
                rs.getLong("relation_count"), rs.getLong("article_count"));
    }
}
