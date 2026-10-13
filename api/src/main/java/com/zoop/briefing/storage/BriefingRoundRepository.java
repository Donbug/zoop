package com.zoop.briefing.storage;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

@Repository
public class BriefingRoundRepository {
    private final JdbcTemplate jdbc;
    private final JsonMapper mapper = JsonMapper.builder().build();
    private final RowMapper<BriefingRound> rows = this::row;

    public BriefingRoundRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    /** A scheduler can retry identical creation; changing an established input window is rejected. */
    @Transactional
    public BriefingRound schedule(String id, LocalDate date, String edition, Instant scheduledAt,
            Instant windowFrom, Instant windowTo) {
        if (id == null || id.isBlank() || date == null || !List.of("morning", "evening").contains(edition)
                || scheduledAt == null || windowTo == null || (windowFrom != null && !windowFrom.isBefore(windowTo))) {
            throw new IllegalArgumentException("Invalid briefing round");
        }
        jdbc.update("""
                INSERT INTO briefing_rounds(id, round_date, edition, scheduled_at, window_from, window_to, open_start)
                VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(round_date, edition) DO NOTHING
                """, id, date, edition, Timestamp.from(scheduledAt), stamp(windowFrom), Timestamp.from(windowTo), windowFrom == null);
        BriefingRound stored = find(date, edition).orElseThrow();
        if (!stored.id().equals(id) || !stored.scheduledAt().equals(scheduledAt)
                || !java.util.Objects.equals(stored.windowFrom(), windowFrom) || !stored.windowTo().equals(windowTo)) {
            throw new IllegalStateException("A different briefing input already exists");
        }
        return stored;
    }

    public Optional<BriefingRound> find(LocalDate date, String edition) {
        return jdbc.query("SELECT * FROM briefing_rounds WHERE round_date=? AND edition=?", rows, date, edition).stream().findFirst();
    }

    public List<BriefingRound> history(Instant before, String id, int fetchSize) {
        if (before == null) {
            return jdbc.query("SELECT * FROM briefing_rounds WHERE published_at IS NOT NULL ORDER BY scheduled_at DESC, id DESC LIMIT ?", rows, fetchSize);
        }
        return jdbc.query("""
                SELECT * FROM briefing_rounds WHERE published_at IS NOT NULL AND (scheduled_at, id) < (?, ?)
                ORDER BY scheduled_at DESC, id DESC LIMIT ?
                """, rows, Timestamp.from(before), id, fetchSize);
    }

    private BriefingRound row(ResultSet rs, int index) throws SQLException {
        return new BriefingRound(rs.getString("id"), rs.getObject("round_date", LocalDate.class), rs.getString("edition"),
                instant(rs, "scheduled_at"), instant(rs, "window_from"), instant(rs, "window_to"), rs.getBoolean("open_start"),
                rs.getString("status"), instant(rs, "published_at"), instant(rs, "generated_at"), rs.getString("graph_version_id"),
                json(rs.getString("published_payload")), json(rs.getString("public_snapshot")), json(rs.getString("comparison_snapshot")));
    }
    private JsonNode json(String value) { return value == null ? null : mapper.readTree(value); }
    private static Timestamp stamp(Instant value) { return value == null ? null : Timestamp.from(value); }
    private static Instant instant(ResultSet rs, String name) throws SQLException {
        Timestamp value = rs.getTimestamp(name); return value == null ? null : value.toInstant();
    }
}
