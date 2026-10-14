package com.zoop.auth.repository;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcAuthRateEventStore implements AuthRateEventStore {
    private final NamedParameterJdbcTemplate jdbc;

    public JdbcAuthRateEventStore(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public void lock(String scope, String subjectHash) {
        jdbc.query("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))",
                new MapSqlParameterSource("key", scope + ":" + subjectHash), rs -> {
                    rs.next();
                    return null;
                });
    }

    @Override
    public List<Instant> recent(String scope, String subjectHash, Instant after, int limit) {
        return jdbc.query("""
                SELECT occurred_at FROM auth_rate_events
                WHERE scope = :scope AND subject_hash = :subjectHash AND occurred_at > :after
                ORDER BY occurred_at LIMIT :limit
                """, new MapSqlParameterSource()
                .addValue("scope", scope).addValue("subjectHash", subjectHash)
                .addValue("after", Timestamp.from(after)).addValue("limit", limit),
                (rs, index) -> rs.getTimestamp("occurred_at").toInstant());
    }

    @Override
    public void add(String scope, String subjectHash, Instant at) {
        jdbc.update("""
                INSERT INTO auth_rate_events (scope, subject_hash, occurred_at)
                VALUES (:scope, :subjectHash, :at)
                """, new MapSqlParameterSource()
                .addValue("scope", scope).addValue("subjectHash", subjectHash)
                .addValue("at", Timestamp.from(at)));
    }

    @Override
    public void clear(String scope, String subjectHash) {
        jdbc.update("DELETE FROM auth_rate_events WHERE scope = :scope AND subject_hash = :subjectHash",
                new MapSqlParameterSource().addValue("scope", scope).addValue("subjectHash", subjectHash));
    }

    @Override
    public void purgeBefore(Instant before) {
        jdbc.update("DELETE FROM auth_rate_events WHERE occurred_at <= :before",
                new MapSqlParameterSource("before", Timestamp.from(before)));
    }
}
