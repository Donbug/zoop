package com.zoop.graph.round;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import com.zoop.graph.round.GraphRoundTicks.Tick;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import static org.junit.jupiter.api.Assertions.*;

/** The scheduler heartbeat table (#55 PR-P4) against the real migrations, on a schema of its own. */
@Tag("graph-postgres")
class GraphRoundTicksPostgresTest {
    private static final Instant STARTED = Instant.parse("2026-11-03T00:00:00Z");
    private static final String DIGEST = "d".repeat(64);
    private String schema;
    private JdbcTemplate jdbc;
    private GraphRoundTicks ticks;

    @BeforeEach void start() {
        schema = "ticks_" + UUID.randomUUID().toString().replace("-", "");
        String url = System.getenv("ZOOP_COMPANY_TEST_DB_URL");
        if (url == null || !url.matches("jdbc:postgresql://127\\.0\\.0\\.1:[0-9]+/zoop_company_test_19")) {
            throw new IllegalStateException("Set ZOOP_COMPANY_TEST_DB_URL to the dedicated localhost zoop_company_test_19 database");
        }
        var dataSource = new DriverManagerDataSource(url + "?currentSchema=" + schema + ",public", "company_test",
                System.getenv().getOrDefault("ZOOP_COMPANY_TEST_DB_PASSWORD", ""));
        jdbc = new JdbcTemplate(dataSource);
        jdbc.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public");
        jdbc.execute("CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public");
        Flyway.configure().dataSource(dataSource).schemas(schema).defaultSchema(schema).load().migrate();
        ticks = new GraphRoundTicks(new NamedParameterJdbcTemplate(jdbc));
    }

    @AfterEach void stop() {
        if (jdbc != null) jdbc.execute("DROP SCHEMA IF EXISTS " + schema + " CASCADE");
    }

    @Test void aBeatUpdatesItsRowInPlaceByTheDatabaseClockAndAStopRemovesIt() {
        ticks.beat("writer-a-0000000a", STARTED, Duration.ofSeconds(15), Optional.empty(), DIGEST);
        ticks.beat("writer-a-0000000a", STARTED, Duration.ofSeconds(15), Optional.of(STARTED.plusSeconds(10)), DIGEST);
        List<Tick> rows = ticks.all();
        assertEquals(1, rows.size());
        Tick tick = rows.getFirst();
        assertTrue(tick.alive(), "beaten just now, by the database's clock");
        assertEquals(STARTED, tick.startedAt());
        assertEquals(Optional.of(STARTED.plusSeconds(10)), tick.lastPassAt());
        assertEquals(DIGEST, tick.calendarDigest());
        ticks.remove("writer-a-0000000a");
        assertEquals(List.of(), ticks.all());
    }

    @Test void aSilentRowIsNotAliveAndADaySilentRowIsPruned() {
        ticks.beat("writer-a-0000000a", STARTED, Duration.ofSeconds(15), Optional.empty(), DIGEST);
        jdbc.update("""
                INSERT INTO graph_round_scheduler_ticks (owner, started_at, beat_at, interval_ms, calendar_digest)
                VALUES ('writer-b-0000000b', now(), clock_timestamp() - interval '46 seconds', 15000, ?),
                       ('writer-old-0000000c', now(), clock_timestamp() - interval '2 days', 15000, ?)
                """, DIGEST, DIGEST);
        var rows = ticks.all();
        assertEquals(List.of(true, false, false), rows.stream().map(Tick::alive).toList());
        ticks.prune();
        assertEquals(List.of("writer-a-0000000a", "writer-b-0000000b"), ticks.all().stream().map(Tick::owner).toList());
        assertThrows(Exception.class, () -> ticks.beat("not an owner", STARTED, Duration.ofSeconds(15), Optional.empty(), DIGEST));
    }
}
