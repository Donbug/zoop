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
 * A status, not a record: rows are updated in place, removed on a graceful stop and pruned after a day of silence.
 */
@Repository
public class GraphRoundTicks {
    static final Duration PRUNE_AFTER = Duration.ofDays(1);

    /** One scheduler's last beat. {@code lastPassAt} is when its last pass started; empty before the first. */
    public record Tick(String owner, Instant startedAt, Instant beatAt, Duration interval, Optional<Instant> lastPassAt,
            Optional<Instant> nextSlotAt) {
        /** Alive while its beat is younger than three intervals. */
        public boolean alive(Instant now) {
            return beatAt.plus(interval.multipliedBy(3)).isAfter(now);
        }
    }

    private final NamedParameterJdbcTemplate jdbc;

    public GraphRoundTicks(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public void beat(Tick tick) {
        jdbc.update("""
                INSERT INTO graph_round_scheduler_ticks (owner, started_at, beat_at, interval_ms, last_pass_at, next_slot_at)
                VALUES (:owner, :started, :beat, :interval, :pass, :next)
                ON CONFLICT (owner) DO UPDATE SET beat_at = EXCLUDED.beat_at, interval_ms = EXCLUDED.interval_ms,
                    last_pass_at = EXCLUDED.last_pass_at, next_slot_at = EXCLUDED.next_slot_at
                """, new MapSqlParameterSource("owner", tick.owner()).addValue("started", stamp(tick.startedAt()))
                .addValue("beat", stamp(tick.beatAt())).addValue("interval", tick.interval().toMillis())
                .addValue("pass", tick.lastPassAt().map(GraphRoundTicks::stamp).orElse(null))
                .addValue("next", tick.nextSlotAt().map(GraphRoundTicks::stamp).orElse(null)));
        jdbc.update("DELETE FROM graph_round_scheduler_ticks WHERE beat_at < :before",
                new MapSqlParameterSource("before", stamp(tick.beatAt().minus(PRUNE_AFTER))));
    }

    public void remove(String owner) {
        jdbc.update("DELETE FROM graph_round_scheduler_ticks WHERE owner = :owner", new MapSqlParameterSource("owner", owner));
    }

    /** Every row, newest beat first. */
    public List<Tick> all() {
        return jdbc.query("""
                SELECT owner, started_at, beat_at, interval_ms, last_pass_at, next_slot_at
                FROM graph_round_scheduler_ticks ORDER BY beat_at DESC
                """, new MapSqlParameterSource(), GraphRoundTicks::row);
    }

    private static Tick row(ResultSet rs, int ignored) throws SQLException {
        return new Tick(rs.getString("owner"), rs.getTimestamp("started_at").toInstant(), rs.getTimestamp("beat_at").toInstant(),
                Duration.ofMillis(rs.getLong("interval_ms")), Optional.ofNullable(rs.getTimestamp("last_pass_at")).map(Timestamp::toInstant),
                Optional.ofNullable(rs.getTimestamp("next_slot_at")).map(Timestamp::toInstant));
    }

    private static Timestamp stamp(Instant at) {
        return Timestamp.from(at);
    }
}
