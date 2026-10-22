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
    private static final Path GRAPH_ROOT = createGraphRoot();
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
        properties.add("zoop.document-read.artifact-root", () -> GRAPH_ROOT.toString());
        properties.add("zoop.document-read.ingestion-sources", () -> GRAPH_ROOT.resolve("sources.json").toString());
        properties.add("zoop.graph.snapshot.source", () -> "artifact");
        properties.add("zoop.graph.snapshot.artifact-root", () -> GRAPH_ROOT.toString());
    }

    @BeforeEach
    void loadSyntheticFixture() throws IOException {
        loadFixture(resource("fixture.sql"));
    }

    private void loadFixture(String sql) throws IOException {
        Files.writeString(GRANTS, resource("grants.json"));
        // Every statement is confined to this test class's random schema, never the shared public schema.
        jdbc.execute("TRUNCATE TABLE briefing_changes, briefing_rounds RESTART IDENTITY CASCADE");
        jdbc.execute("DELETE FROM graph_activations");
        jdbc.execute("DELETE FROM graph_versions");
        jdbc.update("DELETE FROM evidence WHERE article_id LIKE 'brf-test-%'");
        jdbc.update("UPDATE articles SET current_version=NULL WHERE id LIKE 'brf-test-%'");
        jdbc.update("DELETE FROM article_versions WHERE article_id LIKE 'brf-test-%'");
        jdbc.update("DELETE FROM articles WHERE id LIKE 'brf-test-%'");
        jdbc.update("DELETE FROM artifacts WHERE id LIKE 'brf-test-%' OR id LIKE 'artifact-receipt-gv-%'");
        jdbc.update("DELETE FROM companies WHERE id LIKE 'brf-test-%'");
        jdbc.execute(sql);
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
        try (var files = Files.walk(GRAPH_ROOT)) {
            for (Path file : files.sorted(java.util.Comparator.reverseOrder()).toList()) Files.deleteIfExists(file);
        }
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
    void missingRegisteredSnapshotIsExplicitlyUnavailableWithoutCurrentGraphFallback() throws Exception {
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
    void publishedRoundGraphRestoresCanonicalTargetsAndNeverUsesANewerActivePointer() throws Exception {
        registerSyntheticGraph();
        var basis = get("/api/v1/briefings/" + ROUND + "/graph", "basis-ready");
        assertEquals(200, basis.status(), basis.body());
        assertEquals("available", basis.json().path("status").asText());
        assertEquals("brf-test-event", basis.json().at("/keyIssueIds/0").asText());
        assertEquals("brf-test-company", basis.json().at("/companyIds/0").asText());
        String query = "/api/v1/graph?round=" + ROUND;
        var graph = get(query, "graph-ready");
        assertEquals(200, graph.status(), graph.body());
        assertEquals("synthetic-graph-v1", graph.json().at("/metadata/graphVersion").asText());
        assertEquals("2026-10-15T08:30:00Z", graph.json().at("/metadata/asOf").asText());
        assertEquals(2, graph.json().path("nodes").size());
        assertEquals(1, graph.json().path("edges").size());
        assertTrue(graph.json().path("nodes").values().stream().allMatch(n -> n.path("isFocus").asBoolean()));
        // The round remains pinned even if the current market pointer is cleared.
        jdbc.update("UPDATE graph_versions SET active=false WHERE id='synthetic-graph-v1'");
        assertEquals(200, get(query, "same-round-after-pointer-change").status());
        assertEquals(422, get(query + "&graphVersion=newest", "wrong-version").status());
        assertEquals(422, get(query + "&asOf=2026-10-16T00:20:00Z", "wrong-cutoff").status());
        Files.writeString(GRANTS, resource("grants.json").replace("\"enabled\": true", "\"enabled\": false"));
        assertEquals(503, get(query, "direct-round-grant-revoked").status());
    }

    @Test
    void originalRoundGraphRelationEvidenceAndDocumentsUseThePinnedReceiptOverHttp() throws Exception {
        String version = "gv-" + com.zoop.common.json.Canonical.sha256("briefing-round-http");
        String evidenceId = "ev-" + "7".repeat(64);
        loadFixture(resource("fixture.sql").replace("synthetic-graph-v1", version).replace("brf-test-evidence", evidenceId));
        byte[] snapshot = resource("graph-snapshot.json").replace("synthetic-graph-v1", version)
                .replace("brf-test-evidence", evidenceId).getBytes(StandardCharsets.UTF_8);
        Files.write(GRAPH_ROOT.resolve("graph/synthetic.json"), snapshot);
        Files.setPosixFilePermissions(GRAPH_ROOT.resolve("graph/synthetic.json"), java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"));
        String digest = java.util.HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(snapshot));
        jdbc.update("INSERT INTO artifacts(id,kind,storage_uri,sha256,bytes,media_type,created_at) VALUES ('brf-test-graph','graph_snapshot','artifact-root:graph/synthetic.json',?,?,'application/json','2026-10-15T09:00:00Z')", digest, snapshot.length);
        jdbc.update("INSERT INTO graph_versions(id,sequence,kind,created_at,published_at,created_by,source_label,issue_count,relation_count,article_count,snapshot_artifact_id,review_revision,active) VALUES (?,1,'snapshot','2026-10-15T09:00:00Z','2026-10-15T09:00:00Z','system','synthetic',1,1,1,'brf-test-graph',1,true)", version);
        jdbc.update("INSERT INTO graph_activations(version_id,action,actor_kind,pointer_changed,admin_email_snapshot,activated_at) VALUES (?,'publish','system',true,'system','2026-10-15T09:00:00Z')", version);
        String receipt = """
                {"schemaVersion":"zoop-graph-handoff-import-receipt-1","handoffId":"briefing-round-http","bundle":{"articles":[
                {"articleId":"brf-test-document","articleVersion":"synthetic-v1","observations":[
                {"sourceId":"authored-replay","grant":{"grantId":"round-read-grant","revision":"r1"}}]}]}}
                """;
        try (var files = com.zoop.artifact.storage.ArtifactFileStore.at(GRAPH_ROOT).open()) {
            var file = files.put("verification_receipt", version + ".json", receipt.getBytes(StandardCharsets.UTF_8));
            jdbc.update("INSERT INTO artifacts(id,kind,storage_uri,sha256,bytes,media_type,created_at) VALUES (?,'verification_receipt',?,?,?,'application/json','2026-10-15T09:00:00Z')", "artifact-receipt-" + version, file.uri(), file.sha256(), file.bytes());
        }
        String sources = """
                {"schemaVersion":"zoop-ingestion-s2-1","revision":"r1","sources":[{"sourceId":"authored-replay","adapter":"authored-files",
                "inputRoot":"/srv/zoop/test","allowedHosts":["example.invalid"],"scopes":[{"scopeId":"body","selection":"authored test",
                "initialCursor":null,"articleXPath":null,"timestampLimitations":["synthetic"]}],"grant":{"grantId":"round-read-grant",
                "revision":"r1","sourceId":"authored-replay","enabled":true,"rights":"known","allowedOperations":["read","store","quote-display"],
                "recipients":[],"purposes":[],"evidence":["authored fixture"],"expiresAt":null}}]}
                """;
        Files.writeString(GRAPH_ROOT.resolve("sources.json"), sources);
        String original = publishedPayload();
        var graph = get("/api/v1/graph?round=" + ROUND, "round-imported-graph");
        assertEquals(200, graph.status(), graph.body());
        String edge = graph.json().path("edges").get(0).path("id").asText();
        var relation = get("/api/v1/graph/edges/" + edge + "?round=" + ROUND, "round-relation");
        assertEquals(200, relation.status(), relation.body());
        assertEquals(evidenceId, relation.json().path("evidenceIds").get(0).asText());
        String query = "?round=" + ROUND + "&graphVersion=" + version + "&asOf=2026-10-15T08:30:00Z";
        var citation = get("/api/v1/evidence/" + evidenceId + query, "round-citation");
        assertEquals(200, citation.status(), citation.body());
        assertEquals("합성시험", citation.json().path("quote").asText());
        assertEquals(version, citation.json().at("/metadata/graphVersion").asText());
        assertEquals("brf-test-event", citation.json().path("eventIds").get(0).asText());
        var documents = get("/api/v1/companies/brf-test-company/documents" + query + "&limit=3", "round-documents");
        assertEquals(200, documents.status(), documents.body());
        assertEquals(1, documents.json().path("items").size());
        assertEquals("brf-test-event", documents.json().at("/items/0/events/0/eventId").asText());
        assertEquals(409, get("/api/v1/evidence/" + evidenceId + "?graphVersion=" + version + "&asOf=2026-10-15T08:30:00Z", "no-round").status(),
                "the import was activated AFTER cutoff; removing round cannot select it");
        assertEquals(422, get("/api/v1/evidence/" + evidenceId + query.replace(version, "other"), "wrong-round-version").status());
        Files.writeString(GRAPH_ROOT.resolve("sources.json"), sources.replace("\"enabled\":true", "\"enabled\":false"));
        assertEquals("EVIDENCE_UNAVAILABLE", get("/api/v1/evidence/" + evidenceId + query, "revoked-quote").json().at("/error/code").asText());
        Files.writeString(GRAPH_ROOT.resolve("sources.json"), sources);
        assertEquals(200, get("/api/v1/evidence/" + evidenceId + query, "restored-quote").status());
        assertEquals(original, publishedPayload(), "all reads preserve the original publication");
    }

    @Test
    void legacyNullVersionIsMissingRecordingRatherThanATemporaryFetchFailure() throws Exception {
        loadFixture(resource("fixture.sql").replace("\"graphVersion\":\"synthetic-graph-v1\"", "\"graphVersion\":null"));
        var basis = get("/api/v1/briefings/" + ROUND + "/graph", "legacy-no-snapshot");
        assertEquals(200, basis.status(), basis.body());
        assertEquals("unavailable", basis.json().path("status").asText());
        assertEquals("snapshot_not_recorded", basis.json().path("unavailableReason").asText());
        assertTrue(basis.json().path("graphVersion").isNull());
        assertTrue(basis.json().path("keyIssueIds").isEmpty());
        assertEquals(409, get("/api/v1/graph?round=" + ROUND, "legacy-direct-no-fallback").status());
    }

    @Test
    void missingOrChangedSnapshotIsUnavailableWithoutAReplacementGraph() throws Exception {
        registerSyntheticGraph();
        Files.writeString(GRAPH_ROOT.resolve("graph/synthetic.json"), "{tampered}");
        var basis = get("/api/v1/briefings/" + ROUND + "/graph", "snapshot-tampered");
        assertEquals(200, basis.status());
        assertEquals("unavailable", basis.json().path("status").asText());
        assertEquals("snapshot_unavailable", basis.json().path("unavailableReason").asText());
        assertTrue(basis.json().path("keyIssueIds").isEmpty());
        assertEquals(503, get("/api/v1/graph?round=" + ROUND, "no-fallback").status());
    }

    private void registerSyntheticGraph() throws Exception {
        byte[] bytes = resource("graph-snapshot.json").getBytes(StandardCharsets.UTF_8);
        Files.write(GRAPH_ROOT.resolve("graph/synthetic.json"), bytes);
        Files.setPosixFilePermissions(GRAPH_ROOT.resolve("graph/synthetic.json"), java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"));
        String sha = java.util.HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(bytes));
        jdbc.update("INSERT INTO artifacts(id,kind,storage_uri,sha256,bytes,media_type,created_at) VALUES ('brf-test-graph','graph_snapshot','artifact-root:graph/synthetic.json',?,?,'application/json','2026-10-15T09:00:00Z')", sha, bytes.length);
        jdbc.execute("""
                INSERT INTO graph_versions(id,sequence,kind,created_at,published_at,created_by,source_label,issue_count,relation_count,article_count,snapshot_artifact_id,review_revision,active)
                VALUES ('synthetic-graph-v1',1,'snapshot','2026-10-15T09:00:00Z','2026-10-15T09:00:00Z','system','synthetic',1,1,1,'brf-test-graph',1,true);
                INSERT INTO graph_activations(version_id,action,actor_kind,pointer_changed,admin_email_snapshot,activated_at)
                VALUES ('synthetic-graph-v1','publish','system',true,'system','2026-10-15T09:00:00Z');
                """);
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
        JsonNode analysis = doc.json().at("/components/schemas/AnalysisSummary/properties/analysis");
        assertFalse(analysis.has("type"), "A top-level null type would reject the actual analysis object");
        assertTrue(analysis.path("anyOf").values().stream().anyMatch(value ->
                "#/components/schemas/MarketOutlookAnalysis".equals(value.path("$ref").asText())));
        assertTrue(analysis.path("anyOf").values().stream().anyMatch(value -> "null".equals(value.path("type").asText())));
        assertFalse(doc.json().at("/components/schemas/AnalysisSummary/required").values().stream()
                .anyMatch(value -> "analysis".equals(value.asText())));
        for (String field : java.util.List.of("direction", "updateAction")) {
            JsonNode nullableEnum = doc.json().at("/components/schemas/MarketOutlookClaim/properties/" + field);
            assertTrue(nullableEnum.path("anyOf").values().stream().anyMatch(value -> value.path("enum").isArray()));
            assertTrue(nullableEnum.path("anyOf").values().stream().anyMatch(value -> "null".equals(value.path("type").asText())));
        }
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
    private static Path createGraphRoot() {
        try {
            Path root = Files.createTempDirectory("zoop-briefing-graph-").toRealPath();
            Files.createDirectory(root.resolve("graph"));
            Files.createDirectory(root.resolve("verification_receipt"));
            Files.setPosixFilePermissions(root.resolve("verification_receipt"), java.nio.file.attribute.PosixFilePermissions.fromString("rwx------"));
            Files.writeString(root.resolve("sources.json"), "{}");
            Files.setPosixFilePermissions(root, java.nio.file.attribute.PosixFilePermissions.fromString("rwx------"));
            Files.setPosixFilePermissions(root.resolve("graph"), java.nio.file.attribute.PosixFilePermissions.fromString("rwx------"));
            return root;
        } catch (IOException failure) {
            throw new IllegalStateException(failure);
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
