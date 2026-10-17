package com.zoop.briefing.integration;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.DriverManager;
import java.util.UUID;

import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import static org.junit.jupiter.api.Assertions.*;

/** Real HTTP -> Spring -> PostgreSQL -> current grant file. Only synthetic test-authored material is disclosed. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test",
        "ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "ZOOP_AUTH_ALLOWED_ORIGINS=https://zoop.example",
        "zoop.api.cors.allowed-origins=https://zoop.example",
        "springdoc.api-docs.enabled=true",
        "springdoc.swagger-ui.enabled=true"
})
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*")
@Tag("briefing-postgres")
@DirtiesContext(classMode = DirtiesContext.ClassMode.AFTER_CLASS)
class BriefingHttpPostgresTest {
    private static final String SCHEMA = "briefing_http_" + UUID.randomUUID().toString().replace("-", "");
    private static final Path GRANTS = createGrantFile();
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final String MORNING = "/api/v1/briefings?date=2026-10-15&edition=morning";
    private static final String EVENING = "/api/v1/briefings?date=2026-10-15&edition=evening";
    private static final String ROUND = "brf-test-2026-10-15-evening";

    @Autowired JdbcTemplate jdbc;
    @Autowired PlatformTransactionManager transactions;
    @Autowired Flyway flyway;
    @LocalServerPort int port;
    private final HttpClient http = HttpClient.newHttpClient();

    @DynamicPropertySource
    static void isolateDatabaseAndCurrentGrantRegistry(DynamicPropertyRegistry properties) {
        properties.add("spring.datasource.url", () -> databaseUrl(SCHEMA));
        properties.add("spring.flyway.schemas", () -> SCHEMA);
        properties.add("spring.flyway.default-schema", () -> SCHEMA);
        properties.add("spring.jpa.properties.hibernate.default_schema", () -> SCHEMA);
        properties.add("zoop.document-read.grants", () -> GRANTS.toString());
    }

    @BeforeEach
    void loadSyntheticFixture() throws IOException {
        Files.writeString(GRANTS, resource("grants.json"));
        // Every statement is confined to this test class's random schema, never the shared public schema.
        jdbc.execute("TRUNCATE TABLE briefing_changes, briefing_rounds RESTART IDENTITY CASCADE");
        jdbc.update("DELETE FROM evidence WHERE id LIKE 'brf-test-%'");
        jdbc.update("UPDATE articles SET current_version=NULL WHERE id LIKE 'brf-test-%'");
        jdbc.update("DELETE FROM article_versions WHERE article_id LIKE 'brf-test-%'");
        jdbc.update("DELETE FROM articles WHERE id LIKE 'brf-test-%'");
        jdbc.update("DELETE FROM artifacts WHERE id LIKE 'brf-test-%'");
        jdbc.update("DELETE FROM companies WHERE id LIKE 'brf-test-%'");
        jdbc.execute(resource("fixture.sql"));
    }

    @AfterAll
    static void deleteOnlyOwnedSchemaAndGrantFile() throws Exception {
        String url = System.getenv("DB_URL");
        if (url != null) {
            try (var connection = DriverManager.getConnection(url, username(), password());
                    var statement = connection.createStatement()) {
                statement.execute("DROP SCHEMA IF EXISTS " + SCHEMA + " CASCADE");
            }
        }
        Files.deleteIfExists(GRANTS);
    }

    @Test
    void publishedMorningAndEveningRestoreOriginalIssuesMarketAndComparisonOverRealHttp() throws Exception {
        var morning = get(MORNING, "morning-http-request");
        assertEquals(200, morning.status());
        assertEquals("published", morning.json().path("status").asText());
        assertEquals("09:20", morning.json().at("/metadata/schedule/morning").asText());
        assertEquals("17:30", morning.json().at("/metadata/schedule/evening").asText());
        assertTrue(morning.json().path("sinceMorning").isNull());
        assertEquals(1, morning.json().path("items").size());
        assertTrue(morning.json().at("/items/0/title").asText().startsWith("[합성시험]"));
        assertEquals("brf-test-evidence", morning.json().at("/items/0/summary/evidenceIds/0").asText());
        assertTrue(morning.json().at("/marketSummary/text").asText().startsWith("[합성시험]"));
        assertEquals(3, morning.json().at("/marketVariables/indicators").size());
        assertEquals("morning-http-request", morning.header("X-Request-ID"));
        assertEquals(morning.header("X-Request-ID"), morning.json().at("/metadata/requestId").asText());
        assertFalse(morning.body().contains("sourceBindings"));
        var evening = get(EVENING, "evening-http-request");
        assertEquals(200, evening.status());
        assertEquals("available", evening.json().at("/sinceMorning/status").asText());
        assertEquals("brf-test-2026-10-15-morning", evening.json().at("/sinceMorning/morningRoundId").asText());
        assertEquals("continuing", evening.json().at("/sinceMorning/items/0/change").asText());
        assertEquals("synthetic-original-request", jdbc.queryForObject(
                "SELECT published_payload->'metadata'->>'requestId' FROM briefing_rounds WHERE id=?", String.class, ROUND));
    }

    @Test
    void omittedDateUsesLatestStoredRoundRatherThanAssumingTodaysPublication() throws Exception {
        var latest = get("/api/v1/briefings?edition=morning", "latest-http-request");
        assertEquals(200, latest.status());
        assertEquals("brf-test-2026-10-16-morning", latest.json().path("id").asText());
        assertEquals("not_ready", latest.json().path("status").asText());
        var evening = get("/api/v1/briefings?edition=evening", "latest-evening-request");
        assertEquals(200, evening.status());
        assertEquals(ROUND, evening.json().path("id").asText());
        var any = get("/api/v1/briefings", "latest-any-request");
        assertEquals("brf-test-2026-10-16-morning", any.json().path("id").asText());
    }

    @Test
    void historyPaginatesPublishedAndSuspendedRoundsWithoutUnpublishedOrContent() throws Exception {
        var first = get("/api/v1/briefings/rounds?limit=2", "history-first-request");
        assertEquals(200, first.status());
        assertEquals(2, first.json().path("items").size());
        assertEquals(ROUND, first.json().at("/items/0/id").asText());
        assertEquals("brf-test-2026-10-15-morning", first.json().at("/items/1/id").asText());
        String cursor = first.json().path("nextCursor").asText();
        assertFalse(cursor.isBlank());
        var second = get("/api/v1/briefings/rounds?limit=2&cursor=" + encode(cursor), "history-second-request");
        assertEquals(200, second.status());
        assertEquals(2, second.json().path("items").size());
        assertEquals("suspended", second.json().at("/items/0/status").asText());
        assertTrue(second.json().path("nextCursor").isNull());
        assertFalse(second.body().contains("반도체"));
        assertFalse(second.body().contains("brf-test-2026-10-16-morning"));
        assertInvalid("/api/v1/briefings/rounds?limit=3&cursor=" + encode(cursor));
    }

    @Test
    void invalidDatesEditionsCursorsAndLimitsReturn422WithCorrelatedRequestId() throws Exception {
        for (String query : new String[] {"?date=2026-02-30", "?date=not-a-date", "?edition=noon"}) {
            assertInvalid("/api/v1/briefings" + query);
        }
        for (String query : new String[] {"?limit=0", "?limit=101", "?limit=oops", "?cursor=invalid", "?cursor="}) {
            assertInvalid("/api/v1/briefings/rounds" + query);
        }
    }

    @Test
    void honestlyEmptyIssueSetDiffersFromUnpublishedAndSuspendedContent() throws Exception {
        var empty = get("/api/v1/briefings?date=2026-10-14&edition=morning", "empty-request");
        assertEquals(200, empty.status());
        assertEquals("published", empty.json().path("status").asText());
        assertEquals("no_issues_in_window", empty.json().path("emptyReason").asText());
        assertEquals(0, empty.json().path("items").size());
        assertTrue(empty.json().path("marketSummary").has("text"));
        for (String query : new String[] {"?date=2026-10-16&edition=morning", "?date=2026-10-14&edition=evening"}) {
            var hidden = get("/api/v1/briefings" + query, "hidden-request");
            assertEquals(200, hidden.status());
            assertEquals(0, hidden.json().path("items").size());
            assertEquals(0, hidden.json().at("/references/evidenceIds").size());
            assertEquals("unavailable", hidden.json().at("/marketSummary/status").asText());
            assertTrue(hidden.json().path("outlook").isNull());
            assertFalse(hidden.body().contains("반도체"));
        }
    }

    @Test
    void currentGrantRevocationAndMalformedRegistryFailClosedImmediately() throws Exception {
        assertEquals(200, get(EVENING, "before-revoke").status());
        String active = resource("grants.json");
        Files.writeString(GRANTS, active.replace("\"enabled\": true", "\"enabled\": false"));
        assertUnavailable(EVENING);
        assertUnavailable("/api/v1/briefings/" + ROUND + "/graph");
        Files.writeString(GRANTS, active);
        assertEquals(200, get(EVENING, "after-restore").status());
        Files.writeString(GRANTS, "{broken-registry");
        assertUnavailable(MORNING);
    }

    @Test
    void currentPrivateOrDeletedDocumentBlocksPublicSnapshotWithoutChangingOriginal() throws Exception {
        String original = publishedPayload();
        for (String status : new String[] {"private", "deleted"}) {
            jdbc.update("UPDATE articles SET access_status=? WHERE id='brf-test-document'", status);
            assertUnavailable(MORNING);
            assertUnavailable(EVENING);
        }
        jdbc.update("UPDATE articles SET access_status='available' WHERE id='brf-test-document'");
        assertEquals(200, get(EVENING, "available-again").status());
        assertEquals(original, publishedPayload());
    }

    @Test
    void missingVerifiedEvidenceIsUnavailableRatherThanInventedOrEmptySuccess() throws Exception {
        jdbc.update("DELETE FROM evidence WHERE id='brf-test-evidence'");
        assertUnavailable(MORNING);
        assertUnavailable(EVENING);
    }

    @Test
    void sourceGrantRevisionAndRecipientChangesCannotAuthorizePreviouslyPublishedContent() throws Exception {
        String active = resource("grants.json");
        Files.writeString(GRANTS, active.replace("\"revision\": \"synthetic-v1\"", "\"revision\": \"synthetic-v2\""));
        assertUnavailable(MORNING);
        var restricted = JSON.readTree(active);
        ((tools.jackson.databind.node.ObjectNode) restricted.path("grants").get(0)).putArray("recipients").add("another-synthetic-recipient");
        Files.writeString(GRANTS, JSON.writeValueAsString(restricted));
        assertUnavailable(EVENING);
        Files.writeString(GRANTS, active);
        assertEquals(200, get(EVENING, "current-grant-restored").status());
    }

    @Test
    void publisherCannotInsertAnOriginalWithWrongDigestOrUnboundEvidence() {
        String copy = """
                INSERT INTO briefing_rounds(id,round_date,edition,scheduled_at,window_from,window_to,open_start,status,
                    graph_version_id,review_revision,rule_revision,published_payload,public_snapshot,schema_version,
                    payload_sha256,generated_at,published_at)
                SELECT 'brf-test-invalid-original','2026-10-17',edition,scheduled_at,window_from,window_to,open_start,status,
                    graph_version_id,review_revision,rule_revision,
                    published_payload || jsonb_build_object('id','brf-test-invalid-original','date','2026-10-17'),
                    public_snapshot,schema_version,repeat('0',64),generated_at,published_at
                FROM briefing_rounds WHERE id='brf-test-2026-10-15-morning'
                """;
        var digest = assertThrows(DataAccessException.class, () -> jdbc.update(copy));
        assertTrue(digest.getMostSpecificCause().getMessage().contains("digest"));
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM briefing_rounds WHERE id='brf-test-invalid-original'", Integer.class));
        String unbound = copy.replace("public_snapshot,schema_version,repeat('0',64)",
                "jsonb_set(public_snapshot,'{sourceBindings,0,documentVersion}','\"not-a-version\"'),schema_version,"
                    + "encode(sha256(convert_to((published_payload || jsonb_build_object('id','brf-test-invalid-original','date','2026-10-17'))::text,'UTF8')),'hex')");
        var binding = assertThrows(DataAccessException.class, () -> jdbc.update(unbound));
        assertTrue(binding.getMostSpecificCause().getMessage().contains("source binding"));
    }

    @Test
    void graphBasisUsesFrozenVersionAndExplicitUnavailableUntilGraphOwnerIsConnected() throws Exception {
        var graph = get("/api/v1/briefings/" + ROUND + "/graph", "graph-request");
        assertEquals(200, graph.status());
        assertEquals("unavailable", graph.json().path("status").asText());
        assertEquals("synthetic-graph-v1", graph.json().path("graphVersion").asText());
        assertEquals(ROUND, graph.json().path("roundId").asText());
        assertEquals(0, graph.json().path("keyIssueIds").size());
        assertEquals(404, get("/api/v1/briefings/no-such-round/graph", "missing-graph").status());
        var suspended = get("/api/v1/briefings/brf-test-2026-10-14-evening/graph", "suspended-graph");
        assertEquals("suspended", suspended.json().path("status").asText());
        assertEquals(0, suspended.json().path("keyIssueIds").size());
    }

    @Test
    void publishedOriginalCannotBeUpdatedDeletedOrDetachedFromSuspensionHistory() {
        String original = publishedPayload();
        for (String sql : new String[] {
                "UPDATE briefing_rounds SET published_payload=jsonb_set(published_payload,'{items}','[]') WHERE id=?",
                "UPDATE briefing_rounds SET public_snapshot='{}' WHERE id=?",
                "UPDATE briefing_rounds SET graph_version_id='newest-graph' WHERE id=?",
                "UPDATE briefing_rounds SET published_at=published_at+interval '1 second' WHERE id=?",
                "UPDATE briefing_rounds SET window_to=window_to+interval '1 second' WHERE id=?",
                "UPDATE briefing_rounds SET status='suspended',revision=revision+1 WHERE id=?",
                "DELETE FROM briefing_rounds WHERE id=?"}) {
            assertThrows(DataAccessException.class, () -> jdbc.update(sql, ROUND), sql);
        }
        assertEquals(original, publishedPayload());
    }

    @Test
    void correctionsAreAppendedBesideOriginalAndCannotBeRewrittenOrSkipSequence() throws Exception {
        String original = publishedPayload();
        String correction = """
                INSERT INTO briefing_changes(round_id,kind,seq,event_id,original,corrected,reason,admin_id,admin_email_snapshot,created_at)
                VALUES(?, 'correction', ?, 'brf-test-event','[합성시험] 원문','[합성시험] 정정문','[합성시험] 정정 이유',
                       'synthetic-admin','synthetic-admin@example.invalid','2026-10-15T09:00:00Z')
                """;
        jdbc.update(correction, ROUND, 1);
        var result = get(EVENING, "correction-request");
        assertEquals(200, result.status());
        assertEquals("[합성시험] 정정문", result.json().at("/corrections/0/corrected").asText());
        assertEquals(original, publishedPayload());
        assertThrows(DataAccessException.class, () -> jdbc.update(correction, ROUND, 3));
        assertThrows(DataAccessException.class, () -> jdbc.update("UPDATE briefing_changes SET corrected='overwrite' WHERE round_id=?", ROUND));
        assertThrows(DataAccessException.class, () -> jdbc.update("DELETE FROM briefing_changes WHERE round_id=?", ROUND));
    }

    @Test
    void suspensionHistoryAndStatusCommitTogetherAndOriginalIsStillPreserved() throws Exception {
        String original = publishedPayload();
        new TransactionTemplate(transactions).executeWithoutResult(tx -> {
            jdbc.update("""
                    INSERT INTO briefing_changes(round_id,kind,seq,suspended,reason,admin_id,admin_email_snapshot,created_at)
                    VALUES(?, 'suspension',1,true,'[합성시험] 중단','synthetic-admin','synthetic-admin@example.invalid','2026-10-15T09:00:00Z')
                    """, ROUND);
            jdbc.update("UPDATE briefing_rounds SET status='suspended',revision=revision+1 WHERE id=?", ROUND);
        });
        var suspended = get(EVENING, "committed-suspension");
        assertEquals(200, suspended.status());
        assertEquals("suspended", suspended.json().path("status").asText());
        assertEquals(0, suspended.json().path("items").size());
        assertEquals(original, publishedPayload());
    }

    @Test
    void generatedSwaggerIncludesAllThreeOperationsAndResponseSchemas() throws Exception {
        var doc = get("/v3/api-docs", "swagger-request");
        assertEquals(200, doc.status());
        assertEquals("getBriefing", doc.json().at("/paths/~1api~1v1~1briefings/get/operationId").asText());
        assertEquals("listBriefingRounds", doc.json().at("/paths/~1api~1v1~1briefings~1rounds/get/operationId").asText());
        assertEquals("getBriefingGraphBasis", doc.json().at("/paths/~1api~1v1~1briefings~1{id}~1graph/get/operationId").asText());
        assertTrue(doc.json().at("/components/schemas/BriefingResponse").has("properties"));
        assertTrue(doc.json().at("/components/schemas/BriefingResponse/properties/marketSummary").isObject());
        for (String name : java.util.List.of("AnalysisSummary", "MarketVariables", "MarketIndicator", "SinceMorning"))
            assertTrue(doc.json().at("/components/schemas/" + name).has("properties"), name);
        assertTrue(doc.json().at("/components/schemas/MarketIndicator/properties/valueKind/enum").values().stream()
                .anyMatch(value -> "reference".equals(value.asText())));
        for (JsonNode reference : doc.json().findValues("$ref")) {
            String path = reference.asText();
            if (path.startsWith("#/components/schemas/")) assertFalse(doc.json().at(path.substring(1)).isMissingNode(), path);
        }
    }

    @Test
    void configuredBrowserOriginCanReadRealApiAndPreflightWithRequestIdHeader() throws Exception {
        var request = HttpRequest.newBuilder(URI.create(base() + MORNING)).header("Origin", "https://zoop.example")
                .header("X-Request-ID", "browser-request").GET().build();
        var response = http.send(request, HttpResponse.BodyHandlers.ofString());
        assertEquals(200, response.statusCode());
        assertEquals("https://zoop.example", response.headers().firstValue("Access-Control-Allow-Origin").orElseThrow());
        var preflight = HttpRequest.newBuilder(URI.create(base() + "/api/v1/briefings"))
                .header("Origin", "https://zoop.example").header("Access-Control-Request-Method", "GET")
                .header("Access-Control-Request-Headers", "x-request-id").method("OPTIONS", HttpRequest.BodyPublishers.noBody()).build();
        assertTrue(http.send(preflight, HttpResponse.BodyHandlers.discarding()).statusCode() < 300);
    }

    @Test
    void appliedDocumentSchemaUpgradesAdditivelyAndExistingRegistryRowsRemainIntact() throws Exception {
        String upgradeSchema = "briefing_upgrade_" + UUID.randomUUID().toString().replace("-", "");
        // pg_trgm is database-wide and may have been installed into the isolated HTTP schema by the first migration.
        // Expose its actual namespace to this second isolated schema; never move/recreate the extension or edit old DDL.
        String extensionSchema = jdbc.queryForObject("SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='pg_trgm'", String.class);
        String upgradeUrl = databaseUrl(upgradeSchema) + "," + encode(extensionSchema);
        try {
            var baseline = Flyway.configure().dataSource(upgradeUrl, username(), password())
                    .schemas(upgradeSchema).defaultSchema(upgradeSchema).target("20261016090000").load();
            baseline.migrate();
            jdbc.execute("INSERT INTO " + upgradeSchema + ".artifacts(id,kind,storage_uri,sha256,bytes,media_type,created_at) "
                    + "VALUES ('synthetic-upgrade-artifact','briefing_input','artifact://synthetic/upgrade',repeat('a',64),0,'application/json',now())");
            var upgrade = Flyway.configure().dataSource(upgradeUrl, username(), password())
                    .schemas(upgradeSchema).defaultSchema(upgradeSchema).load();
            upgrade.migrate();
            upgrade.validate();
            assertEquals(0, upgrade.migrate().migrationsExecuted);
            assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM " + upgradeSchema + ".artifacts WHERE id='synthetic-upgrade-artifact'", Integer.class));
            assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM " + upgradeSchema + ".flyway_schema_history WHERE version='20261017230000' AND success", Integer.class));
            assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM " + upgradeSchema + ".flyway_schema_history WHERE version='20261016170000' AND description='create graph versions' AND success", Integer.class));
            assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM information_schema.tables WHERE table_schema=? AND table_name='graph_versions'", Integer.class, upgradeSchema));
            assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM information_schema.tables WHERE table_schema=? AND table_name='briefing_rounds'", Integer.class, upgradeSchema));
        } finally {
            jdbc.execute("DROP SCHEMA IF EXISTS " + upgradeSchema + " CASCADE");
        }
    }

    private void assertInvalid(String path) throws Exception {
        var result = get(path, "invalid-request");
        assertEquals(422, result.status(), result.body());
        assertEquals(path.contains("cursor=") ? "INVALID_CURSOR" : "INVALID_REQUEST", result.json().at("/error/code").asText());
        assertEquals(result.header("X-Request-ID"), result.json().at("/error/requestId").asText());
    }

    private void assertUnavailable(String path) throws Exception {
        var result = get(path, "unavailable-request");
        assertEquals(503, result.status(), result.body());
        assertEquals("SOURCE_UNAVAILABLE", result.json().at("/error/code").asText());
        assertEquals(result.header("X-Request-ID"), result.json().at("/error/requestId").asText());
        assertFalse(result.body().contains("반도체"));
    }

    private String publishedPayload() {
        return jdbc.queryForObject("SELECT published_payload::text FROM briefing_rounds WHERE id=?", String.class, ROUND);
    }

    private Reply get(String path, String requestId) throws Exception {
        var response = http.send(HttpRequest.newBuilder(URI.create(base() + path)).header("X-Request-ID", requestId).GET().build(),
                HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        return new Reply(response.statusCode(), response.body(), JSON.readTree(response.body()), response);
    }

    private String base() { return "http://127.0.0.1:" + port; }
    private static String encode(String value) { return URLEncoder.encode(value, StandardCharsets.UTF_8); }
    private static String username() { return System.getenv().getOrDefault("DB_USERNAME", "company_test"); }
    private static String password() { return System.getenv().getOrDefault("DB_PASSWORD", ""); }
    private static String databaseUrl(String schema) {
        String url = System.getenv("DB_URL");
        return url + (url.contains("?") ? "&" : "?") + "currentSchema=" + schema + ",public";
    }
    private static String resource(String name) throws IOException {
        try (var input = BriefingHttpPostgresTest.class.getResourceAsStream("/briefing/" + name)) {
            if (input == null) throw new IOException("Missing synthetic briefing resource");
            return new String(input.readAllBytes(), StandardCharsets.UTF_8);
        }
    }
    private static Path createGrantFile() {
        try {
            Path path = Files.createTempFile("zoop-briefing-http-synthetic-grants-", ".json").toAbsolutePath();
            Files.writeString(path, resource("grants.json"));
            return path;
        } catch (IOException failure) {
            throw new IllegalStateException("Cannot prepare synthetic grant registry", failure);
        }
    }
    private record Reply(int status, String body, JsonNode json, HttpResponse<String> response) {
        String header(String name) { return response.headers().firstValue(name).orElse(null); }
    }
}
