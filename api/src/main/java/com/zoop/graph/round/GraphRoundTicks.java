package com.zoop.graph.round;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * The live round schedulers ({@code graph_round_scheduler_ticks}, #55 PR-P4): a writer beats its row, the public web reads them.
 * The beat time and the liveness are the database's clock, so a skew between the writer's and the web's hosts does not move the
 * window. A status, not a record: rows are updated in place, removed on a graceful stop and pruned after a day of silence.
 */
@Repository
public class GraphRoundTicks {
    /** One scheduler's last beat. {@code alive}: its beat is younger than three of its intervals, by the database's clock. */
    public record Tick(String owner, Instant startedAt, Instant beatAt, Duration interval, Optional<Instant> lastPassAt,
            String calendarDigest, boolean alive) {
    }

    private final NamedParameterJdbcTemplate jdbc;

    public GraphRoundTicks(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public void beat(String owner, Instant startedAt, Duration interval, Optional<Instant> lastPassAt, String calendarDigest) {
        jdbc.update("""
                INSERT INTO graph_round_scheduler_ticks (owner, started_at, beat_at, interval_ms, last_pass_at, calendar_digest)
                VALUES (:owner, :started, clock_timestamp(), :interval, :pass, :calendar)
                ON CONFLICT (owner) DO UPDATE SET beat_at = EXCLUDED.beat_at, interval_ms = EXCLUDED.interval_ms,
                    last_pass_at = EXCLUDED.last_pass_at, calendar_digest = EXCLUDED.calendar_digest
                """, new MapSqlParameterSource("owner", owner).addValue("started", stamp(startedAt))
                .addValue("interval", interval.toMillis()).addValue("pass", lastPassAt.map(GraphRoundTicks::stamp).orElse(null))
                .addValue("calendar", calendarDigest));
    }

    /** Drops the rows silent for a day (writers that stopped without removing theirs); a scheduler runs it when it starts. */
    public void prune() {
        jdbc.update("DELETE FROM graph_round_scheduler_ticks WHERE beat_at < clock_timestamp() - interval '1 day'",
                new MapSqlParameterSource());
    }

    public void remove(String owner) {
        jdbc.update("DELETE FROM graph_round_scheduler_ticks WHERE owner = :owner", new MapSqlParameterSource("owner", owner));
    }

    /** Every row, newest beat first. */
    public List<Tick> all() {
        return jdbc.query("""
                SELECT owner, started_at, beat_at, interval_ms, last_pass_at, calendar_digest,
                    beat_at + interval_ms * 3 * interval '1 millisecond' > clock_timestamp() AS alive
                FROM graph_round_scheduler_ticks ORDER BY beat_at DESC
                """, new MapSqlParameterSource(), GraphRoundTicks::row);
    }

    private static Tick row(ResultSet rs, int ignored) throws SQLException {
        return new Tick(rs.getString("owner"), rs.getTimestamp("started_at").toInstant(), rs.getTimestamp("beat_at").toInstant(),
                Duration.ofMillis(rs.getLong("interval_ms")), Optional.ofNullable(rs.getTimestamp("last_pass_at")).map(Timestamp::toInstant),
                rs.getString("calendar_digest"), rs.getBoolean("alive"));
    }

    private static Timestamp stamp(Instant at) {
        return Timestamp.from(at);
    }
}
