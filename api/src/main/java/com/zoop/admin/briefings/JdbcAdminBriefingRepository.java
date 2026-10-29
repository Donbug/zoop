package com.zoop.admin.briefings;

import java.sql.Timestamp;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/** Explicit read projection: no credentials, lease/owner tokens or provider request bodies are selected. */
@Repository
public class JdbcAdminBriefingRepository {
    private static final String SELECT = """
            SELECT r.id,r.round_date,r.edition,r.scheduled_at,r.window_from,r.window_to,r.open_start,r.status,
                r.stages,r.failure_reason,r.generated_at,r.published_at,r.graph_version_id,r.review_revision,
                CASE WHEN r.published_at IS NOT NULL THEN jsonb_array_length(r.published_payload->'items') END AS item_count,
                (SELECT count(*) FROM briefing_attempts a WHERE a.round_id=r.id AND a.purpose='generation') AS attempts,
                a.trigger, a.stages AS attempt_stages,
                (SELECT count(*) FROM briefing_changes c WHERE c.round_id=r.id AND c.kind='correction') AS correction_count,
                s.suspended,s.reason AS suspension_reason,s.created_at AS suspension_at,s.admin_email_snapshot AS suspension_admin
            FROM briefing_rounds r
            LEFT JOIN LATERAL (SELECT trigger,stages FROM briefing_attempts
                WHERE round_id=r.id AND purpose='generation' ORDER BY attempt_no DESC LIMIT 1) a ON true
            LEFT JOIN LATERAL (SELECT suspended,reason,created_at,admin_email_snapshot FROM briefing_changes
                WHERE round_id=r.id AND kind='suspension' ORDER BY seq DESC LIMIT 1) s ON true
            """;
    private final JdbcTemplate jdbc;
    public JdbcAdminBriefingRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    List<Map<String, Object>> list(AdminBriefingService.Window window, AdminBriefingCursor.Position cursor, int limit) {
        StringBuilder sql = new StringBuilder(SELECT).append(" WHERE true");
        List<Object> args = new ArrayList<>();
        if (window.start() != null) { sql.append(" AND r.scheduled_at>=?"); args.add(Timestamp.from(window.start())); }
        if (window.end() != null) {
            sql.append(window.exclusiveEnd() ? " AND r.scheduled_at<?" : " AND r.scheduled_at<=?");
            args.add(Timestamp.from(window.end()));
        }
        if (cursor != null) {
            sql.append(" AND (r.scheduled_at,r.id COLLATE \"C\") < (?,? COLLATE \"C\")");
            args.add(Timestamp.from(cursor.at())); args.add(cursor.id());
        }
        sql.append(" ORDER BY r.scheduled_at DESC,r.id COLLATE \"C\" DESC LIMIT ?"); args.add(limit);
        return jdbc.queryForList(sql.toString(), args.toArray());
    }

    List<Map<String, Object>> find(String id) { return jdbc.queryForList(SELECT + " WHERE r.id=?", id); }

    List<Map<String, Object>> changes(String id) {
        return jdbc.queryForList("""
                SELECT id,seq,event_id,original,corrected,reason,created_at,admin_email_snapshot
                FROM briefing_changes WHERE round_id=? AND kind='correction' ORDER BY seq
                """, id);
    }

    List<Map<String, Object>> attempts(String id) {
        return jdbc.queryForList("""
                SELECT attempt_no,trigger,started_at,finished_at,status,failure_reason,admin_email_snapshot
                FROM briefing_attempts WHERE round_id=? AND purpose='generation' ORDER BY attempt_no
                """, id);
    }
}
