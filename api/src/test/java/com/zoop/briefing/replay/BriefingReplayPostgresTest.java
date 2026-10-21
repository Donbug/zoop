package com.zoop.briefing.replay;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import com.zoop.ZoopApplication;
import com.zoop.artifact.storage.ArtifactFileStore;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.boot.web.server.servlet.context.ServletWebServerApplicationContext;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

import static org.junit.jupiter.api.Assertions.*;

/** No model/network call: directly authored sources/results exercise the actual replay importer and HTTP readers. */
@Tag("briefing-replay-postgres")
@EnabledIfEnvironmentVariable(named = "DB_URL", matches = "jdbc:postgresql:.*briefing_replay.*")
class BriefingReplayPostgresTest {
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final String SCHEMA = "briefing_replay_" + UUID.randomUUID().toString().replace("-", "");
    private static final HttpClient HTTP = HttpClient.newHttpClient();
    private static final String QUERY = "/api/v1/briefings?date=2026-10-09&edition=";
    private static final String INBOX = "inbox/synthetic-test-authorization.md";
    private static Path directory;
    private static Path source;
    private static Path bundle;
    private static Path artifacts;
    private static Path grants;
    private static Path manifest;
    private static String sourceSha;
    private static JdbcTemplate jdbc;
    private static DataSourceTransactionManager transactionManager;
    private static ConfigurableApplicationContext localRead;
    private static ConfigurableApplicationContext defaultRead;
    private static int localPort;
    private static int defaultPort;

    @BeforeAll
    static void migrateImportAndStartBothRealHttpModes() throws Exception {
        directory = Files.createTempDirectory("zoop-synthetic-briefing-replay-").toRealPath();
        source = directory.resolve("source.jsonl");
        bundle = directory.resolve("bundle.json");
        artifacts = Files.createDirectory(directory.resolve("artifacts"));
        grants = directory.resolve("grants.json");
        manifest = directory.resolve("manifest.json");
        sourceSha = ArtifactFileStore.sha256(resource("source.jsonl"));
        var dataSource = new DriverManagerDataSource(url(), username(), password());
        jdbc = new JdbcTemplate(dataSource);
        transactionManager = new DataSourceTransactionManager(dataSource);
        Flyway.configure().dataSource(dataSource).schemas(SCHEMA).defaultSchema(SCHEMA).load().migrate();
        jdbc.update("INSERT INTO companies(id,name) VALUES ('company-synthetic-replay-062','[합성시험] 시험기업')");
        restoreInput();
        importer().importBundle();
        localRead = startReader(true);
        defaultRead = startReader(false);
        localPort = ((ServletWebServerApplicationContext) localRead).getWebServer().getPort();
        defaultPort = ((ServletWebServerApplicationContext) defaultRead).getWebServer().getPort();
    }

    @BeforeEach
    void resetOnlyOwnedSchemaAndSyntheticInputs() throws Exception {
        jdbc.execute("TRUNCATE TABLE briefing_changes, briefing_rounds, ai_executions, evidence, document_analyses, article_versions, articles, artifacts RESTART IDENTITY CASCADE");
        restoreInput();
        Files.deleteIfExists(grants);
        Files.deleteIfExists(manifest);
        try (var files = Files.walk(artifacts)) {
            for (Path path : files.filter(path -> !path.equals(artifacts)).sorted(java.util.Comparator.reverseOrder()).toList()) Files.deleteIfExists(path);
        }
    }

    @AfterAll
    static void closeReadersAndDropOnlyOwnedSchema() throws Exception {
        if (localRead != null) localRead.close();
        if (defaultRead != null) defaultRead.close();
        if (jdbc != null) jdbc.execute("DROP SCHEMA IF EXISTS " + SCHEMA + " CASCADE");
        if (directory != null) {
            try (var files = Files.walk(directory)) {
                for (Path path : files.sorted(java.util.Comparator.reverseOrder()).toList()) Files.deleteIfExists(path);
            }
        }
    }

    @Test
    void explicitLocalReplayRestoresBothEditionsThreeRoutesAndRealArtifactBytes() throws Exception {
        var imported = importer().importBundle();
        assertFalse(imported.alreadyImported());
        assertEquals(2, imported.roundIds().size());
        assertEquals(1, imported.documents());
        assertEquals(1, imported.evidence());
        for (String edition : List.of("morning", "evening")) {
            var response = get(localPort, QUERY + edition);
            assertEquals(200, response.status(), response.body());
            assertEquals("published", response.json().path("status").asText());
            assertTrue(response.json().path("graphVersion").isNull());
            assertEquals(1, response.json().path("items").size());
            assertTrue(response.json().at("/items/0/title").asText().startsWith("[합성시험]"));
            assertEquals("unavailable", response.json().at("/marketVariables/status").asText());
            assertEquals("replay-test-request", response.json().at("/metadata/requestId").asText());
            String id = response.json().path("id").asText();
            var graph = get(localPort, "/api/v1/briefings/" + id + "/graph");
            assertEquals(200, graph.status(), graph.body());
            assertEquals("unavailable", graph.json().path("status").asText());
            assertTrue(graph.json().path("graphVersion").isNull());
        }
        var history = get(localPort, "/api/v1/briefings/rounds");
        assertEquals(200, history.status(), history.body());
        assertEquals(2, history.json().path("items").size());
        var storedFiles = jdbc.query("SELECT storage_uri,sha256,bytes FROM artifacts", (row, n) ->
                ArtifactFileStore.at(artifacts).readVerified(row.getString("storage_uri"), row.getString("sha256"), row.getLong("bytes")));
        assertFalse(storedFiles.isEmpty());
        assertTrue(storedFiles.stream().anyMatch(bytes -> new String(bytes, StandardCharsets.UTF_8).contains("😀")));
        var offsets = jdbc.queryForMap("SELECT quote,start_offset,end_offset FROM evidence");
        String body = JSON.readTree(resource("source.jsonl")).path("body").asText();
        int start = ((Number) offsets.get("start_offset")).intValue();
        int end = ((Number) offsets.get("end_offset")).intValue();
        assertEquals(offsets.get("quote"), body.substring(body.offsetByCodePoints(0, start), body.offsetByCodePoints(0, end)));
    }

    @Test
    void replayDefaultsDoNotAuthorizeNullGraphOriginalEvenWithValidDevelopmentFiles() throws Exception {
        importer().importBundle();
        var denied = get(defaultPort, QUERY + "morning");
        assertEquals(503, denied.status(), denied.body());
        assertEquals("SOURCE_UNAVAILABLE", denied.json().at("/error/code").asText());
        assertFalse(denied.body().contains("시험기업"));
        assertEquals(200, get(localPort, QUERY + "morning").status());
    }

    @Test
    void identicalImportCreatesNothingAndPublishedOriginalAndUsageStayImmutable() throws Exception {
        var first = importer().importBundle();
        String original = jdbc.queryForObject("SELECT published_payload::text FROM briefing_rounds WHERE edition='morning'", String.class);
        int artifactCount = count("artifacts");
        int usageCount = receiptCount();
        byte[] originalManifest = Files.readAllBytes(manifest);
        byte[] originalGrants = Files.readAllBytes(grants);
        var again = importer().importBundle();
        assertTrue(again.alreadyImported());
        assertEquals(first.roundIds(), again.roundIds());
        assertEquals(2, count("briefing_rounds"));
        assertEquals(artifactCount, count("artifacts"));
        assertEquals(usageCount, receiptCount());
        assertArrayEquals(originalManifest, Files.readAllBytes(manifest));
        assertArrayEquals(originalGrants, Files.readAllBytes(grants));
        assertEquals(original, jdbc.queryForObject("SELECT published_payload::text FROM briefing_rounds WHERE edition='morning'", String.class));
        assertThrows(DataAccessException.class, () -> jdbc.update("UPDATE briefing_rounds SET published_payload='{}' WHERE edition='morning'"));
        assertThrows(DataAccessException.class, () -> jdbc.update("UPDATE artifacts SET bytes=0 WHERE kind='ai_call_receipt'"));
    }

    @Test
    void sourceFileDigestBodyDigestAndUnicodeQuoteOffsetsMustMatchBeforeAnyPublication() throws Exception {
        Files.writeString(source, new String(resource("source.jsonl"), StandardCharsets.UTF_8) + "\n");
        rejectWithoutPublication();
        restoreInput();
        var wrongBody = bundleNode();
        ((ObjectNode) wrongBody.at("/selected/0/sources/0")).put("bodySha256", "0".repeat(64));
        writeBundle(wrongBody);
        rejectWithoutPublication();
        restoreInput();
        var wrongOffset = bundleNode();
        var selectedSource = (ObjectNode) wrongOffset.at("/selected/0/sources/0");
        selectedSource.put("start", selectedSource.path("start").asInt() + 1);
        writeBundle(wrongOffset);
        rejectWithoutPublication();
    }

    @Test
    void partialFailedUnknownOrMissingVerificationCannotCreatePublicRound() throws Exception {
        for (String mutation : List.of("FAIL", "UNKNOWN", "MISSING")) {
            restoreInput();
            var candidate = bundleNode();
            var verification = (ObjectNode) candidate.at("/editions/morning/verification");
            if (mutation.equals("FAIL")) verification.put("status", "FAIL");
            else if (mutation.equals("UNKNOWN")) ((ObjectNode) verification.path("checks").get(0)).put("verdict", "UNKNOWN");
            else ((tools.jackson.databind.node.ArrayNode) verification.path("checks")).remove(1);
            writeBundle(candidate);
            rejectWithoutPublication();
        }
    }

    @Test
    void developmentAuthorizationCannotBeRelabeledProductionOrDetachedFromSourceAndUserInstruction() throws Exception {
        for (String field : List.of("scope", "sourceSha256", "userInboxRef")) {
            restoreInput();
            var candidate = bundleNode();
            ((ObjectNode) candidate.path("authorization")).put(field, switch (field) {
                case "scope" -> "production";
                case "sourceSha256" -> "0".repeat(64);
                default -> "inbox/a-different-user-instruction.md";
            });
            writeBundle(candidate);
            rejectWithoutPublication();
        }
    }

    @Test
    void explicitUnknownUsageRemainsNullAndCannotBeSilentlyCountedAsZero() throws Exception {
        var candidate = bundleNode();
        List<JsonNode> lists = new ArrayList<>(List.of(candidate.path("receipts"), candidate.at("/editions/morning/usage"), candidate.at("/editions/evening/usage")));
        for (var list : lists) for (var receipt : list) {
            var unknown = (ObjectNode) receipt;
            unknown.put("usageKnown", false).putNull("inputTokens").putNull("outputTokens");
        }
        writeBundle(candidate);
        importer().importBundle();
        assertTrue(receiptCount() > 0);
        var receipts = jdbc.query("SELECT storage_uri,sha256,bytes FROM artifacts WHERE kind='ai_call_receipt'", (row, n) ->
                JSON.readTree(ArtifactFileStore.at(artifacts).readVerified(row.getString("storage_uri"), row.getString("sha256"), row.getLong("bytes"))));
        for (var receipt : receipts) {
            assertTrue(receipt.path("inputTokens").isNull(), receipt.toString());
            assertTrue(receipt.path("outputTokens").isNull(), receipt.toString());
            assertFalse(receipt.path("usageKnown").asBoolean());
        }
        assertEquals(0, count("ai_executions"), "No fabricated briefing attempt owner may be created");
    }

    @Test
    void replayManifestAndCurrentGrantBytesAreVerifiedFreshForEveryRead() throws Exception {
        importer().importBundle();
        byte[] savedManifest = Files.readAllBytes(manifest);
        byte[] savedGrants = Files.readAllBytes(grants);
        var changedManifest = (ObjectNode) JSON.readTree(savedManifest);
        changedManifest.put("runId", "a-different-replay-run");
        Files.writeString(manifest, JSON.writeValueAsString(changedManifest));
        assertEquals(503, get(localPort, QUERY + "morning").status());
        Files.write(manifest, savedManifest);
        assertEquals(200, get(localPort, QUERY + "morning").status());
        Files.writeString(grants, new String(savedGrants, StandardCharsets.UTF_8) + "\n");
        assertEquals(503, get(localPort, QUERY + "morning").status());
        Files.write(grants, savedGrants);
        assertEquals(200, get(localPort, QUERY + "morning").status());
    }

    @Test
    void secondRoundDatabaseFailureRollsBackAllRowsAndIdenticalRetryRecoversFiles() throws Exception {
        jdbc.execute("""
                CREATE FUNCTION synthetic_reject_evening_replay() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.edition='evening' THEN RAISE EXCEPTION 'synthetic second-round storage failure'; END IF;
                    RETURN NEW;
                END $$;
                CREATE TRIGGER synthetic_second_round_failure BEFORE INSERT ON briefing_rounds
                FOR EACH ROW EXECUTE FUNCTION synthetic_reject_evening_replay()
                """);
        try {
            assertThrows(RuntimeException.class, () -> importer().importBundle());
            assertEquals(0, count("briefing_rounds"));
            assertEquals(0, count("articles"));
            assertEquals(0, count("evidence"));
            assertEquals(0, count("artifacts"));
            assertFalse(Files.exists(manifest));
            assertFalse(Files.exists(grants));
        } finally {
            jdbc.execute("DROP TRIGGER synthetic_second_round_failure ON briefing_rounds");
            jdbc.execute("DROP FUNCTION synthetic_reject_evening_replay()");
        }
        var recovered = importer().importBundle();
        assertFalse(recovered.alreadyImported());
        assertEquals(2, count("briefing_rounds"));
        assertEquals(200, get(localPort, QUERY + "evening").status());
    }

    @Test
    void requiredReceiptStagesAndEditionOwnershipCannotBeOmittedOrReused() throws Exception {
        var missing = bundleNode();
        ((tools.jackson.databind.node.ArrayNode) missing.path("receipts")).remove(1);
        writeBundle(missing);
        rejectWithoutPublication();
        restoreInput();
        var reused = bundleNode();
        ((ObjectNode) reused.at("/editions/morning")).set("usage", reused.at("/editions/evening/usage").deepCopy());
        writeBundle(reused);
        rejectWithoutPublication();
    }

    @Test
    void identicalImportRecoversOnlyMissingOwnSidecarsWithoutCreatingDuplicateRows() throws Exception {
        importer().importBundle();
        int artifactsBefore = count("artifacts");
        String original = jdbc.queryForObject("SELECT published_payload::text FROM briefing_rounds WHERE edition='morning'", String.class);
        byte[] grantsBefore = Files.readAllBytes(grants);
        byte[] manifestBefore = Files.readAllBytes(manifest);
        Files.delete(manifest);
        Files.delete(grants);
        assertEquals(503, get(localPort, QUERY + "morning").status());
        var recovered = importer().importBundle();
        assertTrue(recovered.alreadyImported());
        assertEquals(artifactsBefore, count("artifacts"));
        assertEquals(2, count("briefing_rounds"));
        assertArrayEquals(grantsBefore, Files.readAllBytes(grants));
        assertArrayEquals(manifestBefore, Files.readAllBytes(manifest));
        assertEquals(original, jdbc.queryForObject("SELECT published_payload::text FROM briefing_rounds WHERE edition='morning'", String.class));
        assertEquals(200, get(localPort, QUERY + "morning").status());
    }

    @Test
    void credentialNamedFieldsAreRejectedBeforeAnyArtifactOrDatabaseWrite() throws Exception {
        for (String field : List.of("apiKey", "accessToken")) {
            restoreInput();
            var candidate = bundleNode();
            candidate.put(field, "synthetic-placeholder-only");
            writeBundle(candidate);
            rejectWithoutPublication();
            assertEquals(0, count("artifacts"));
            assertFalse(Files.exists(manifest));
        }
    }

    @Test
    void operatorAuthorizedKnownTruncatedImportanceKeepsOriginalStatusAndEveryToken() throws Exception {
        var candidate = correctedAssessment(false);
        writeBundle(candidate);
        importer().importBundle();
        var stored = storedReceipts();
        var original = stored.stream().filter(receipt -> "incomplete".equals(receipt.path("status").asText())).findFirst().orElseThrow();
        assertEquals(24466, original.path("inputTokens").asLong());
        assertEquals(8000, original.path("outputTokens").asLong());
        assertEquals(200, original.path("httpStatus").asInt());
        assertTrue(original.path("usageKnown").asBoolean());
        assertEquals(7, stored.size());
        long expectedInput = 0, expectedOutput = 0;
        for (var receipt : candidate.path("receipts")) {
            expectedInput += receipt.path("inputTokens").asLong();
            expectedOutput += receipt.path("outputTokens").asLong();
        }
        assertEquals(expectedInput, stored.stream().mapToLong(receipt -> receipt.path("inputTokens").asLong()).sum());
        assertEquals(expectedOutput, stored.stream().mapToLong(receipt -> receipt.path("outputTokens").asLong()).sum());
        assertEquals(200, get(localPort, QUERY + "morning").status());
    }

    @Test
    void historicalCompletedCoverageAuditKeepsItsRealArrayPolicyAndKnownUsage() throws Exception {
        var candidate = correctedAssessment(true);
        writeBundle(candidate);
        importer().importBundle();
        assertEquals(7, receiptCount());
        var original = storedReceipts().stream().filter(receipt -> receipt.path("inputTokens").asLong() == 24466).findFirst().orElseThrow();
        assertEquals("completed", original.path("status").asText());
        assertEquals(8000, original.path("outputTokens").asLong());
        assertEquals(200, get(localPort, QUERY + "evening").status());
    }

    @Test
    void correctionCannotAuthorizeUnknownUnapprovedWrongScopeOrUnfinishedReplacement() throws Exception {
        for (String mutation : List.of("missing_audit", "unapproved", "same_digest", "global_stage", "edition_stage",
                "source", "inbox", "http", "unknown_usage", "replacement_incomplete")) {
            restoreInput();
            var candidate = correctedAssessment(false);
            var correction = (ObjectNode) candidate.path("coverageCorrections").get(0);
            var original = (ObjectNode) candidate.path("receipts").get(0);
            var replacement = (ObjectNode) candidate.path("receipts").get(6);
            switch (mutation) {
                case "missing_audit" -> candidate.remove("coverageCorrections");
                case "unapproved" -> correction.put("operatorAuthorized", false);
                case "same_digest" -> correction.put("correctedRequestDigest", original.path("requestDigest").asText());
                case "global_stage" -> { original.put("stage", "briefing_global_selection"); replacement.put("stage", "briefing_global_selection"); }
                case "edition_stage" -> { original.put("stage", "briefing_morning_generation"); replacement.put("stage", "briefing_morning_generation"); }
                case "source" -> correction.put("sourceSha256", "0".repeat(64));
                case "inbox" -> correction.put("operatorInboxRef", "inbox/some-other-instruction.md");
                case "http" -> original.put("httpStatus", 403);
                case "unknown_usage" -> original.put("usageKnown", false).putNull("inputTokens").putNull("outputTokens");
                case "replacement_incomplete" -> replacement.put("status", "incomplete");
                default -> throw new IllegalStateException(mutation);
            }
            writeBundle(candidate);
            rejectWithoutPublication();
            assertEquals(0, count("artifacts"), mutation);
        }
    }

    @Test
    void incompleteAssessmentCannotUseHistoricalCompletedArrayPolicyToBypassCorrectionRules() throws Exception {
        var candidate = correctedAssessment(false);
        var correction = (ObjectNode) candidate.path("coverageCorrections").get(0);
        correction.put("correctionPolicy", "input-id-array-v1").put("maxOutputTokens", 8000);
        writeBundle(candidate);
        rejectWithoutPublication();
        assertEquals(0, count("artifacts"));
    }

    private static ObjectNode correctedAssessment(boolean historicalCompleted) throws Exception {
        var candidate = bundleNode();
        var receipts = (tools.jackson.databind.node.ArrayNode) candidate.path("receipts");
        var original = (ObjectNode) receipts.get(0);
        var replacement = original.deepCopy();
        replacement.put("requestDigest", ArtifactFileStore.sha256("synthetic-corrected-importance-request".getBytes(StandardCharsets.UTF_8)))
                .put("responseId", "resp_synthetic_corrected_importance").put("httpStatus", 200);
        receipts.add(replacement);
        original.put("status", historicalCompleted ? "completed" : "incomplete").put("httpStatus", 200)
                .put("usageKnown", true).put("inputTokens", 24466).put("outputTokens", 8000);
        var correction = candidate.putArray("coverageCorrections").addObject();
        correction.put("schemaVersion", "zoop-assessment-coverage-correction-v2")
                .put("originalRequestDigest", original.path("requestDigest").asText())
                .put("correctedRequestDigest", replacement.path("requestDigest").asText())
                .put("reason", historicalCompleted ? "completed_response_document_coverage_error" : "operator_authorized_known_output_truncation")
                .put("originalStatus", historicalCompleted ? "completed" : "incomplete")
                .put("originalHttpStatus", 200).put("originalUsageKnown", true)
                .put("operatorAuthorized", true).put("operatorInboxRef", INBOX).put("sourceSha256", sourceSha)
                .put("correctionPolicy", historicalCompleted ? "input-id-array-v1" : "required-document-id-object-v2")
                .put("maxOutputTokens", historicalCompleted ? 8000 : 12000);
        if (historicalCompleted) correction.putNull("originalIncompleteReason");
        else correction.put("originalIncompleteReason", "max_output_tokens");
        return candidate;
    }

    private static List<JsonNode> storedReceipts() {
        return jdbc.query("SELECT storage_uri,sha256,bytes FROM artifacts WHERE kind='ai_call_receipt'", (row, n) ->
                JSON.readTree(ArtifactFileStore.at(artifacts).readVerified(row.getString("storage_uri"), row.getString("sha256"), row.getLong("bytes"))));
    }

    @Test
    void changedBundleCannotOverwriteAnAlreadyPublishedReplay() throws Exception {
        importer().importBundle();
        String original = jdbc.queryForObject("SELECT published_payload::text FROM briefing_rounds WHERE edition='morning'", String.class);
        var changed = bundleNode();
        ((ObjectNode) changed.at("/editions/morning/items/0")).put("title", "[합성시험] 원본을 덮어쓰려는 다른 제목");
        writeBundle(changed);
        assertThrows(RuntimeException.class, () -> importer().importBundle());
        assertEquals(original, jdbc.queryForObject("SELECT published_payload::text FROM briefing_rounds WHERE edition='morning'", String.class));
        assertEquals(2, count("briefing_rounds"));
    }

    private static BriefingReplayImporter importer() {
        return new BriefingReplayImporter(jdbc, transactionManager,
                new BriefingReplaySettings(source, bundle, artifacts, grants, manifest, sourceSha, INBOX));
    }
    private static ConfigurableApplicationContext startReader(boolean enabled) {
        return new SpringApplicationBuilder(ZoopApplication.class).web(WebApplicationType.SERVLET).profiles("local")
                .run("--server.port=0", "--server.address=127.0.0.1",
                        "--spring.datasource.url=" + url(), "--spring.datasource.username=" + username(),
                        "--spring.datasource.password=" + password(), "--spring.flyway.schemas=" + SCHEMA,
                        "--spring.flyway.default-schema=" + SCHEMA, "--spring.jpa.properties.hibernate.default_schema=" + SCHEMA,
                        "--ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=test", "--ZOOP_AUTH_CSRF_KEYS=test=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                        "--zoop.briefing.replay.read-enabled=" + enabled, "--zoop.briefing.replay.manifest=" + manifest,
                        "--zoop.document-read.grants=" + grants, "--zoop.document-read.artifact-root=" + artifacts);
    }
    private static void restoreInput() throws Exception {
        Files.write(source, resource("source.jsonl"));
        Files.write(bundle, resource("bundle.json"));
    }
    private static ObjectNode bundleNode() throws Exception { return (ObjectNode) JSON.readTree(Files.readAllBytes(bundle)); }
    private static void writeBundle(JsonNode candidate) throws Exception { Files.writeString(bundle, JSON.writeValueAsString(candidate)); }
    private void rejectWithoutPublication() {
        assertThrows(RuntimeException.class, () -> importer().importBundle());
        assertEquals(0, count("briefing_rounds"));
        assertEquals(0, count("ai_executions"));
    }
    private static int receiptCount() { return jdbc.queryForObject("SELECT count(*) FROM artifacts WHERE kind='ai_call_receipt'", Integer.class); }
    private static int count(String table) { return jdbc.queryForObject("SELECT count(*) FROM " + table, Integer.class); }
    private static String url() {
        String base = System.getenv("DB_URL");
        return base + (base.contains("?") ? "&" : "?") + "currentSchema=" + SCHEMA + ",public";
    }
    private static String username() { return System.getenv().getOrDefault("DB_USERNAME", "company_test"); }
    private static String password() { return System.getenv().getOrDefault("DB_PASSWORD", ""); }
    private static byte[] resource(String name) throws Exception {
        try (var stream = BriefingReplayPostgresTest.class.getResourceAsStream("/briefing-replay/" + name)) {
            if (stream == null) throw new IllegalStateException("Missing synthetic replay test resource");
            return stream.readAllBytes();
        }
    }
    private static Reply get(int port, String path) throws Exception {
        var response = HTTP.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path))
                .header("X-Request-ID", "replay-test-request").GET().build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        return new Reply(response.statusCode(), response.body(), JSON.readTree(response.body()));
    }
    private record Reply(int status, String body, JsonNode json) { }
}
