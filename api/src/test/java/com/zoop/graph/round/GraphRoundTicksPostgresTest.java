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
    private static final Instant NOW = Instant.parse("2026-11-03T01:00:00Z");
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

    @Test void aBeatUpdatesItsRowInPlaceAndAStopRemovesIt() {
        ticks.beat(tick("writer-a-0000000a", NOW, Optional.empty()));
        ticks.beat(tick("writer-a-0000000a", NOW.plusSeconds(15), Optional.of(NOW.plusSeconds(10))));
        List<Tick> rows = ticks.all();
        assertEquals(1, rows.size());
        assertEquals(NOW.plusSeconds(15), rows.getFirst().beatAt());
        assertEquals(NOW.minusSeconds(3600), rows.getFirst().startedAt(), "the start time is the first beat's");
        assertEquals(Optional.of(NOW.plusSeconds(10)), rows.getFirst().lastPassAt());
        assertEquals(Duration.ofSeconds(15), rows.getFirst().interval());
        ticks.remove("writer-a-0000000a");
        assertEquals(List.of(), ticks.all());
    }

    @Test void twoWritersAreBothSeenNewestFirstAndADaySilentRowIsPruned() {
        ticks.beat(tick("writer-old-0000000c", NOW.minus(Duration.ofDays(2)), Optional.empty()));
        ticks.beat(tick("writer-a-0000000a", NOW.minusSeconds(5), Optional.empty()));
        ticks.beat(tick("writer-b-0000000b", NOW, Optional.empty()));
        assertEquals(List.of("writer-b-0000000b", "writer-a-0000000a"), ticks.all().stream().map(Tick::owner).toList());
        assertThrows(Exception.class, () -> ticks.beat(tick("not an owner", NOW, Optional.empty())));
    }

    private static Tick tick(String owner, Instant beatAt, Optional<Instant> lastPassAt) {
        return new Tick(owner, NOW.minusSeconds(3600), beatAt, Duration.ofSeconds(15), lastPassAt, Optional.of(NOW.plusSeconds(300)));
    }
}
