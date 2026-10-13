package com.zoop.briefing.storage;

import com.zoop.briefing.controller.BriefingController;
import com.zoop.briefing.query.BriefingQueryService;
import com.zoop.common.exception.GlobalExceptionHandler;
import com.zoop.common.request.RequestIdFilter;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.UUID;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;
import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@Tag("briefing-db")
class BriefingStorageDbTest {
    private JdbcTemplate jdbc;
    private JdbcTemplate admin;
    private String schema;
    private BriefingRoundRepository repository;
    private final LocalDate date = LocalDate.of(2026, 10, 13);
    private final Instant scheduled = Instant.parse("2026-10-13T00:20:00Z");
    private final JsonMapper mapper = JsonMapper.builder().build();

    @BeforeEach void setup() {
        String url = required("ZOOP_BRIEFING_TEST_DB_URL");
        String username = required("ZOOP_BRIEFING_TEST_DB_USERNAME");
        String password = required("ZOOP_BRIEFING_TEST_DB_PASSWORD");
        schema = "briefing_" + UUID.randomUUID().toString().replace("-", "");
        var base = new DriverManagerDataSource(url, username, password);
        admin = new JdbcTemplate(base); admin.execute("CREATE SCHEMA " + schema);
        var ds = new DriverManagerDataSource(url + (url.contains("?") ? "&" : "?") + "currentSchema=" + schema, username, password);
        jdbc = new JdbcTemplate(ds);
        // Exercise incremental application as well as a fresh schema. Published auth migrations stay untouched.
        Flyway.configure().dataSource(ds).defaultSchema(schema).schemas(schema).target("20261013000000").load().migrate();
        assertEquals(2, jdbc.queryForObject("SELECT count(*) FROM flyway_schema_history WHERE success AND type='SQL'", Integer.class));
        Flyway.configure().dataSource(ds).defaultSchema(schema).schemas(schema).load().migrate();
        repository = new BriefingRoundRepository(jdbc);
    }
    @AfterEach void cleanup() {
        // Only this test's unique schema in the explicitly supplied test DB.
        if (admin != null && schema != null) admin.execute("DROP SCHEMA " + schema + " CASCADE");
    }
    private static String required(String key) {
        String value = System.getenv(key);
        if (value == null || value.isBlank()) throw new IllegalStateException("Explicit isolated test DB required: " + key);
        return value;
    }
    private ObjectNode payload(String id) {
        var p = mapper.createObjectNode().put("id", id).put("date", date.toString()).put("edition", "morning")
            .put("scheduledAt", scheduled.toString()).put("generatedAt", scheduled.toString()).put("graphVersion", "fixture-g1")
            .put("reviewRevision", 0).put("ruleRevision", 0).put("selectedFrom", 0).put("emptyReason", "no_issues_in_window")
            .putNull("marketVariables").putNull("outlook");
        p.putArray("items");
        p.putObject("dataWindow").putNull("start").put("end", scheduled.toString()).put("openStart", true);
        var refs = p.putObject("references"); refs.putArray("eventIds"); refs.putArray("evidenceIds"); refs.putArray("companyIds");
        var meta = p.putObject("metadata");
        meta.put("source", "synthetic-test").put("asOf", scheduled.toString()).put("graphVersion", "fixture-g1")
            .put("requestId", "stored-request").put("partial", false); meta.putArray("failures");
        meta.putObject("schedule").put("morning", "09:20").put("evening", "17:30").put("confirmed", true);
        meta.putObject("selection").put("basis", "market").putNull("reason");
        return p;
    }
    private void publishFixture(String id, ObjectNode payload) {
        var snap = mapper.createObjectNode(); snap.putObject("marketSummary").put("status", "unavailable").put("reason", "synthetic-no-producer");
        jdbc.update("""
            UPDATE briefing_rounds SET status='published', graph_version_id='fixture-g1', review_revision=0, rule_revision=0,
            published_payload=?::jsonb, public_snapshot=?::jsonb, generated_at=?, published_at=?, schema_version='briefing-v1', payload_sha256=? WHERE id=?
            """, payload.toString(), snap.toString(), Timestamp.from(scheduled), Timestamp.from(scheduled.plusSeconds(30)),
            sha(payload.toString()), id);
    }
    private static String sha(String content) {
        try { return java.util.HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(content.getBytes(java.nio.charset.StandardCharsets.UTF_8))); }
        catch (java.security.NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
    }

    @Test void migrationAndScheduleSurviveRepositoryRestartWithoutDuplicateRounds() {
        repository.schedule("fixture-round", date, "morning", scheduled, null, scheduled);
        new BriefingRoundRepository(jdbc).schedule("fixture-round", date, "morning", scheduled, null, scheduled);
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM briefing_rounds", Integer.class));
        assertThrows(IllegalStateException.class, () -> repository.schedule("another-id", date, "morning", scheduled, null, scheduled));
        assertThrows(DataAccessException.class, () -> jdbc.update("UPDATE briefing_rounds SET open_start=false WHERE id='fixture-round'"));
    }
    @Test void publishedSnapshotCannotBeChangedDeletedOrRegenerated() {
        repository.schedule("fixture-round", date, "morning", scheduled, null, scheduled);
        publishFixture("fixture-round", payload("fixture-round"));
        for (String assignment : new String[]{"published_payload='{}'::jsonb", "public_snapshot='{}'::jsonb", "graph_version_id='new'", "review_revision=1", "published_at=NULL", "window_to=window_to+interval '1 minute'"}) {
            assertThrows(DataAccessException.class, () -> jdbc.update("UPDATE briefing_rounds SET " + assignment + " WHERE id='fixture-round'"));
        }
        assertThrows(DataAccessException.class, () -> jdbc.update("DELETE FROM briefing_rounds WHERE id='fixture-round'"));
        jdbc.update("UPDATE briefing_rounds SET status='suspended', revision=revision+1 WHERE id='fixture-round'");
        assertEquals("fixture-g1", repository.find(date, "morning").orElseThrow().graphVersion());
    }
    @Test void publishedItemKeysAndRanksAreValidatedByDb() {
        repository.schedule("fixture-round", date, "morning", scheduled, null, scheduled);
        var duplicate = payload("fixture-round");
        duplicate.withArray("items").addObject().put("eventId", "event-a").put("rank", 1);
        duplicate.withArray("items").addObject().put("eventId", "event-a").put("rank", 2);
        assertThrows(DataAccessException.class, () -> publishFixture("fixture-round", duplicate));
        var wrongGraph = payload("fixture-round").put("graphVersion", "other-graph");
        assertThrows(DataAccessException.class, () -> publishFixture("fixture-round", wrongGraph));
        var tooMany = payload("fixture-round");
        for (int i = 1; i <= 4; i++) tooMany.withArray("items").addObject().put("eventId", "e-"+i).put("rank", i);
        assertThrows(DataAccessException.class, () -> publishFixture("fixture-round", tooMany));
    }
    @Test void httpRestoresCommittedSnapshotAndRedactsAfterSuspension() throws Exception {
        repository.schedule("fixture-round", date, "morning", scheduled, null, scheduled);
        publishFixture("fixture-round", payload("fixture-round"));
        // Explicit allow only for synthetic test content. Production's missing rights adapter denies access.
        var service = new BriefingQueryService(new BriefingRoundRepository(jdbc), Clock.fixed(scheduled, ZoneOffset.UTC), r -> true);
        var mvc = MockMvcBuilders.standaloneSetup(new BriefingController(service))
            .setControllerAdvice(new GlobalExceptionHandler()).addFilters(new RequestIdFilter()).build();
        mvc.perform(get("/api/v1/briefings?date=2026-10-13&edition=morning").header("X-Request-ID", "fresh-request"))
            .andExpect(status().isOk()).andExpect(jsonPath("$.status").value("published"))
            .andExpect(jsonPath("$.graphVersion").value("fixture-g1"))
            .andExpect(jsonPath("$.marketSummary.reason").value("synthetic-no-producer"))
            .andExpect(jsonPath("$.metadata.requestId").value("fresh-request"));
        mvc.perform(get("/api/v1/briefings/rounds?limit=1")).andExpect(status().isOk()).andExpect(jsonPath("$.items[0].id").value("fixture-round"));
        jdbc.update("UPDATE briefing_rounds SET status='suspended', revision=revision+1 WHERE id='fixture-round'");
        mvc.perform(get("/api/v1/briefings?date=2026-10-13&edition=morning"))
            .andExpect(status().isOk()).andExpect(jsonPath("$.status").value("suspended"))
            .andExpect(jsonPath("$.items").isEmpty()).andExpect(jsonPath("$.marketSummary.status").value("unavailable"));
    }
}
