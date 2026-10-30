package com.zoop.briefing.storage;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import com.zoop.common.json.StrictJson;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.JsonNode;

/** JDBC read side: no save/update method and no model or artifact-store access. */
@Repository
public class BriefingRoundRepository {
    // The digest is explicitly PostgreSQL jsonb::text UTF-8, not the producer's original JSON byte hash.
    private static final String ROUND = """
            SELECT *, payload_sha256 = encode(sha256(convert_to(published_payload::text, 'UTF8')), 'hex')
                AS payload_digest_valid FROM briefing_rounds
            """;
    private static final String HISTORY = """
            SELECT id, round_date, edition, scheduled_at, status, published_at FROM briefing_rounds
            WHERE published_at IS NOT NULL
            """;
    private final JdbcTemplate jdbc;
    private final RowMapper<BriefingRound> rows = this::round;

    public BriefingRoundRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public String feedbackVersion(String id) {
        return jdbc.queryForObject("SELECT COALESCE(graph_version_id,'publication:'||payload_sha256) FROM briefing_rounds WHERE id=? AND published_at IS NOT NULL", String.class,id);
    }

    public Optional<BriefingRound> find(LocalDate date, String edition) {
        return jdbc.query(ROUND + " WHERE round_date=? AND edition=?", rows, date, edition).stream().findFirst();
    }

    /** The latest stored round, optionally constrained by date and/or edition; no assumed calendar fallback. */
    public Optional<BriefingRound> latest(LocalDate date, String edition) {
        StringBuilder sql = new StringBuilder(ROUND).append(" WHERE true");
        List<Object> parameters = new ArrayList<>();
        if (date != null) {
            sql.append(" AND round_date=?");
            parameters.add(date);
        }
        if (edition != null) {
            sql.append(" AND edition=?");
            parameters.add(edition);
        }
        sql.append(" ORDER BY scheduled_at DESC, id COLLATE \"C\" DESC LIMIT 1");
        return jdbc.query(sql.toString(), rows, parameters.toArray()).stream().findFirst();
    }

    public Optional<BriefingRound> findById(String id) {
        return jdbc.query(ROUND + " WHERE id=?", rows, id).stream().findFirst();
    }

    /** Exact publication evidence, independent of document-analysis summary ownership. */
    public Optional<ItemEvidence> findItemEvidence(String id) {
        return jdbc.query("""
                SELECT e.id, e.article_id, e.article_version, e.quote, e.start_offset, e.end_offset,
                    v.title, v.publisher, v.url, v.published_at, a.kind, t.sha256
                FROM evidence e JOIN article_versions v ON v.article_id=e.article_id AND v.version=e.article_version
                JOIN articles a ON a.id=v.article_id JOIN artifacts t ON t.id=v.text_artifact_id
                WHERE e.id=? AND a.access_status='available' AND e.quote_verified IS TRUE
                    AND e.verification_artifact_id IS NOT NULL AND e.text_artifact_id=v.text_artifact_id
                    AND e.input_kind='body' AND e.offset_unit='unicode_code_point'
                """, (rs, index) -> new ItemEvidence(rs.getString("id"), rs.getString("article_id"),
                        rs.getString("article_version"), rs.getString("quote"), rs.getLong("start_offset"),
                        rs.getLong("end_offset"), rs.getString("title"), rs.getString("publisher"), rs.getString("url"),
                        instant(rs, "published_at"), rs.getString("kind"), rs.getString("sha256")), id)
                .stream().findFirst();
    }

    public record ItemEvidence(String id, String documentId, String documentVersion, String quote, long start, long end,
            String title, String publisher, String url, Instant publishedAt, String sourceKind, String bodySha256) { }

    /** C collation keeps the cursor comparison and ordering identical across database locales. */
    public List<BriefingHistoryEntry> history(Instant before, String id, int fetchSize) {
        if (before == null) {
            return jdbc.query(HISTORY + " ORDER BY scheduled_at DESC, id COLLATE \"C\" DESC LIMIT ?",
                    this::historyEntry, fetchSize);
        }
        return jdbc.query(HISTORY + """
                 AND (scheduled_at, id COLLATE "C") < (?, ? COLLATE "C")
                 ORDER BY scheduled_at DESC, id COLLATE "C" DESC LIMIT ?
                """, this::historyEntry, Timestamp.from(before), id, fetchSize);
    }

    public List<BriefingChange> changes(String roundId) {
        return jdbc.query("""
                SELECT id, kind, event_id, original, corrected, reason, created_at, suspended
                FROM briefing_changes WHERE round_id=? ORDER BY id ASC
                """, (rs, index) -> new BriefingChange(rs.getLong("id"), rs.getString("kind"), rs.getString("event_id"),
                        rs.getString("original"), rs.getString("corrected"), rs.getString("reason"),
                        instant(rs, "created_at"), rs.getObject("suspended", Boolean.class)), roundId);
    }

    private BriefingHistoryEntry historyEntry(ResultSet rs, int index) throws SQLException {
        return new BriefingHistoryEntry(rs.getString("id"), rs.getObject("round_date", LocalDate.class),
                rs.getString("edition"), instant(rs, "scheduled_at"), rs.getString("status"), instant(rs, "published_at"));
    }

    private BriefingRound round(ResultSet rs, int index) throws SQLException {
        Instant publishedAt = instant(rs, "published_at");
        if (publishedAt != null && !Boolean.TRUE.equals(rs.getObject("payload_digest_valid", Boolean.class))) {
            throw new DataIntegrityViolationException("Stored briefing publication digest is invalid");
        }
        return new BriefingRound(rs.getString("id"), rs.getObject("round_date", LocalDate.class), rs.getString("edition"),
                instant(rs, "scheduled_at"), instant(rs, "window_from"), instant(rs, "window_to"), rs.getBoolean("open_start"),
                rs.getString("status"), publishedAt, instant(rs, "generated_at"), rs.getString("graph_version_id"),
                json(rs.getString("published_payload")), json(rs.getString("public_snapshot")),
                json(rs.getString("comparison_snapshot")));
    }

    private static JsonNode json(String value) {
        if (value == null) return null;
        try {
            return StrictJson.parseObject(value).node();
        } catch (StrictJson.Malformed malformed) {
            throw new DataIntegrityViolationException("Stored briefing JSON is not an object", malformed);
        }
    }

    private static Instant instant(ResultSet rs, String name) throws SQLException {
        Timestamp value = rs.getTimestamp(name);
        return value == null ? null : value.toInstant();
    }
}
