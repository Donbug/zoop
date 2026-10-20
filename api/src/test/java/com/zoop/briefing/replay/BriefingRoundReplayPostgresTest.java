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
import com.zoop.common.json.Canonical;
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
class BriefingRoundReplayPostgresTest {
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final String SCHEMA = "briefing_round_replay_" + UUID.randomUUID().toString().replace("-", "");
    private static final HttpClient HTTP = HttpClient.newHttpClient();
    private static final String QUERY = "/api/v1/briefings?date=2026-10-02&edition=";
    private static final String INBOX = "inbox/synthetic-round-authorization.md";
    private static Path directory;
    private static Path source;
    private static Path bundle;
    private static Path artifacts;
    private static Path grants;
    private static Path manifest;
    private static Path clocks;
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
        clocks = directory.resolve("clocks.json");
        Files.createDirectory(directory.resolve("html"));
        Files.write(clocks, resource("clocks.json"));
        var registry = JSON.readTree(resource("clocks.json"));
        for (var record : registry.path("records")) {
            String name = record.path("htmlSha256").asText() + ".html";
            Files.write(directory.resolve("html").resolve(name), resource("html/" + name));
        }
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
        if (Files.exists(directory.resolve("calls"))) {
            try (var files = Files.walk(directory.resolve("calls"))) {
                for (Path path : files.sorted(java.util.Comparator.reverseOrder()).toList()) Files.deleteIfExists(path);
            }
        }
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
    void groupedSchemaStoresImmutableArchiveAndKeepsUnverifiedRoundsUnpublished() throws Exception {
        prepareEmptyGroupedArchive();
        var imported = importer().importBundle();
        assertEquals(14, imported.roundIds().size());
        assertEquals(0, jdbc.queryForObject("SELECT count(*) FROM briefing_rounds WHERE published_at IS NOT NULL", Integer.class));
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM artifacts WHERE id LIKE '%-grouped-issues'", Integer.class));
        assertEquals("failed", get(localPort, QUERY + "morning").json().path("status").asText());
        byte[] originalManifest = Files.readAllBytes(manifest);
        assertTrue(importer().importBundle().alreadyImported());
        assertArrayEquals(originalManifest, Files.readAllBytes(manifest));
    }

    @Test
    void groupedArchiveTamperingCannotWriteRowsEvenWhenSourceAndRoundIdentitiesAreValid() throws Exception {
        prepareEmptyGroupedArchive();
        Files.writeString(directory.resolve("grouped-issues.json"), "{\"schemaVersion\":\"changed\"}");
        rejectWithoutPublication();
        assertEquals(0, count("artifacts"));
    }

    private static void prepareEmptyGroupedArchive() throws Exception {
        var candidate = bundleNode();
        ObjectNode archive = JSON.createObjectNode().put("schemaVersion", "zoop-grouped-issues-v1").put("sourceFileSha256", sourceSha);
        archive.putArray("issues"); archive.putArray("documents"); archive.putArray("receipts");
        byte[] bytes = Canonical.write(archive).getBytes(StandardCharsets.UTF_8);
        Files.write(directory.resolve("grouped-issues.json"), bytes);
        candidate.put("schemaVersion", BriefingGroupedSimulationRules.SCHEMA).put("groupArchiveSha256", ArtifactFileStore.sha256(bytes));
        candidate.putArray("groupingReceipts"); candidate.putArray("receipts");
        for (JsonNode node : candidate.path("rounds")) {
            ObjectNode round = (ObjectNode) node;
            ObjectNode previous = JSON.createObjectNode().put("type", "simulated_previous_output")
                    .put("status", "unavailable").put("reason", "Authored grouping fixture has no verified publication");
            round.set("previous", previous);
            round.put("selectionStatus", "HELD_VALIDATION").putNull("result").putNull("resultSha256").putNull("groupedSelectionRequestDigest");
            round.putArray("selected"); round.putArray("receipts");
            ObjectNode identity = (ObjectNode) round.path("identity");
            identity.set("previous", previous.deepCopy()); identity.put("groupArchiveSha256", ArtifactFileStore.sha256(bytes));
            ObjectNode prompts = (ObjectNode) identity.path("promptArtifacts");
            for (String name : List.of("selection.md", "selection.schema.json")) {
                try (var stream = BriefingRoundReplayPostgresTest.class.getResourceAsStream("/briefing/prompts/grouped-issues/" + name)) {
                    if (stream == null) throw new IllegalStateException("Missing grouped prompt resource");
                    prompts.put("grouped-" + name, ArtifactFileStore.sha256(stream.readAllBytes()));
                }
            }
            round.put("identitySha256", Canonical.digest(identity));
        }
        writeBundle(candidate);
    }

    @Test
    void eachRoundSelectsOnlyItsOwnWindowAndMorningEveningHaveDifferentIssues() throws Exception {
        var imported = importer().importBundle();
        assertEquals(14, imported.roundIds().size());
        assertEquals(14, count("briefing_rounds"));
        assertEquals(4, count("articles"));
        assertEquals(4, count("evidence"));
        var morning = get(localPort, QUERY + "morning");
        var evening = get(localPort, QUERY + "evening");
        assertEquals(200, morning.status(), morning.body());
        assertEquals(200, evening.status(), evening.body());
        assertEquals("published", morning.json().path("status").asText());
        assertEquals("published", evening.json().path("status").asText());
        assertNotEquals(morning.json().at("/items/0/eventId"), evening.json().at("/items/0/eventId"));
        assertEquals(1, morning.json().at("/items/0/evidenceIds").size());
        assertEquals(2, evening.json().at("/items/0/evidenceIds").size());
        var documents = jdbc.queryForList("SELECT id FROM articles ORDER BY id", String.class);
        assertFalse(documents.contains("doc-synthetic-round-lower-bound"));
        assertFalse(documents.contains("doc-synthetic-round-unknown"));
        assertTrue(documents.containsAll(List.of("doc-synthetic-round-morning", "doc-synthetic-round-evening-a",
                "doc-synthetic-round-evening-b", "doc-synthetic-round-next-morning")));
        assertEquals("2026-10-01T08:30:00Z", morning.json().at("/dataWindow/start").asText());
        assertEquals("2026-10-02T00:20:00Z", morning.json().at("/dataWindow/end").asText());
        assertEquals("2026-10-02T00:20:00Z", evening.json().at("/dataWindow/start").asText());
        assertEquals("2026-10-02T08:30:00Z", evening.json().at("/dataWindow/end").asText());
        assertTrue(morning.json().path("graphVersion").isNull());
        assertEquals("unavailable", evening.json().at("/marketVariables/status").asText());
    }

    @Test
    void heldSourceCoverageRoundsRemainUnpublishedAndAreAbsentFromPublicHistory() throws Exception {
        importer().importBundle();
        assertEquals(3, jdbc.queryForObject("SELECT count(*) FROM briefing_rounds WHERE published_at IS NOT NULL", Integer.class));
        assertEquals(11, jdbc.queryForObject("SELECT count(*) FROM briefing_rounds WHERE published_at IS NULL AND published_payload IS NULL", Integer.class));
        var held = get(localPort, "/api/v1/briefings?date=2026-10-08&edition=evening");
        assertEquals(200, held.status(), held.body());
        assertEquals("not_ready", held.json().path("status").asText());
        assertEquals(0, held.json().path("items").size());
        assertTrue(held.json().path("emptyReason").isNull());
        assertFalse(held.body().contains("독립 선정"));
        var history = get(localPort, "/api/v1/briefings/rounds");
        assertEquals(200, history.status(), history.body());
        assertEquals(3, history.json().path("items").size());
        assertEquals(12, receiptCount(), "Held empty windows must not fabricate model calls");
    }

    @Test
    void originalClockSourceIdentityAndHtmlDigestsAreRequiredBeforeAnyDatabaseWrite() throws Exception {
        for (String mutation : List.of("source_sha", "clock_file_sha", "clock_record_sha", "identity_sha", "identity_window")) {
            restoreInput();
            var candidate = bundleNode();
            var first = (ObjectNode) candidate.path("rounds").get(0);
            switch (mutation) {
                case "source_sha" -> candidate.put("sourceFileSha256", "0".repeat(64));
                case "clock_file_sha" -> candidate.put("clockFileSha256", "0".repeat(64));
                case "clock_record_sha" -> ((ObjectNode) first.path("clockRefs").get(0)).put("clockRecordSha256", "0".repeat(64));
                case "identity_sha" -> first.put("identitySha256", "0".repeat(64));
                case "identity_window" -> {
                    ((ObjectNode) first.at("/identity/window")).put("from", "2026-10-01T08:30:01Z");
                    first.put("identitySha256", Canonical.digest(first.path("identity")));
                }
                default -> throw new IllegalStateException(mutation);
            }
            writeBundle(candidate);
            rejectWithoutPublication();
            assertEquals(0, count("artifacts"), mutation);
        }
        restoreInput();
        var registry = JSON.readTree(Files.readAllBytes(clocks));
        String html = registry.path("records").get(1).path("htmlSha256").asText() + ".html";
        Path htmlPath = directory.resolve("html").resolve(html);
        byte[] originalHtml = Files.readAllBytes(htmlPath);
        try {
            Files.writeString(htmlPath, "[합성시험] 변경된 HTML 바이트");
            rejectWithoutPublication();
        } finally { Files.write(htmlPath, originalHtml); }
    }

    @Test
    void contradictoryPreviouslyVerifiedPublicationTimeIsRejectedEvenAfterAllHashesAreRebound() throws Exception {
        var originalRows = new ArrayList<JsonNode>();
        for (String line : Files.readAllLines(source)) if (!line.isBlank()) originalRows.add(JSON.readTree(line));
        for (var row : originalRows) {
            if (row.path("documentId").asText().equals("doc-synthetic-round-morning")) {
                ((ObjectNode) row).put("publishedAt", "2026-10-02T00:20:01Z");
            }
        }
        Files.writeString(source, originalRows.stream().map(Canonical::write).collect(java.util.stream.Collectors.joining("\n", "", "\n")));
        String updatedSourceSha = ArtifactFileStore.sha256(Files.readAllBytes(source));
        var registry = (ObjectNode) JSON.readTree(Files.readAllBytes(clocks));
        registry.put("sourceFileSha256", updatedSourceSha);
        for (var record : registry.path("records")) ((ObjectNode) record).put("sourceFileSha256", updatedSourceSha);
        Files.writeString(clocks, Canonical.write(registry));
        String updatedClockSha = ArtifactFileStore.sha256(Files.readAllBytes(clocks));
        var candidate = bundleNode();
        candidate.put("sourceFileSha256", updatedSourceSha).put("clockFileSha256", updatedClockSha);
        ((ObjectNode) candidate.path("authorization")).put("sourceSha256", updatedSourceSha);
        for (var round : candidate.path("rounds")) {
            var identity = (ObjectNode) round.path("identity");
            identity.put("sourceFileSha256", updatedSourceSha).put("clockFileSha256", updatedClockSha);
            ((ObjectNode) identity.path("authorization")).put("sourceSha256", updatedSourceSha);
            for (var ref : round.path("clockRefs")) {
                for (var record : registry.path("records")) {
                    if (ref.path("documentId").equals(record.path("documentId"))) {
                        ((ObjectNode) ref).put("clockRecordSha256", Canonical.digest(record));
                    }
                }
            }
            ((ObjectNode) round).put("identitySha256", Canonical.digest(identity));
        }
        writeBundle(candidate);
        var differentSource = new BriefingReplayImporter(jdbc, transactionManager,
                new BriefingReplaySettings(source, bundle, artifacts, grants, manifest, updatedSourceSha, INBOX, clocks));
        assertThrows(RuntimeException.class, differentSource::importBundle);
        assertEquals(0, count("briefing_rounds"));
        assertEquals(0, count("artifacts"));
    }

    @Test
    void aClockRefAtTheLowerBoundCannotBeSmuggledIntoTheNextRound() throws Exception {
        var candidate = bundleNode();
        var morning = (ObjectNode) candidate.path("rounds").get(0);
        var evening = (ObjectNode) candidate.path("rounds").get(1);
        ((tools.jackson.databind.node.ArrayNode) evening.path("clockRefs")).add(morning.path("clockRefs").get(0).deepCopy());
        ((tools.jackson.databind.node.ArrayNode) evening.path("inputSources")).add(morning.path("inputSources").get(0).deepCopy());
        ((ObjectNode) evening.path("identity")).put("candidateInputSha256", Canonical.digest(evening.path("inputSources")));
        evening.put("identitySha256", Canonical.digest(evening.path("identity")));
        writeBundle(candidate);
        rejectWithoutPublication();
    }

    @Test
    void previousOutputMustBeTheImmediatelyPriorPassWithTheExactPreservedResultHash() throws Exception {
        for (String mutation : List.of("result_hash", "skip_held")) {
            restoreInput();
            var candidate = bundleNode();
            ObjectNode changed;
            if (mutation.equals("result_hash")) {
                changed = (ObjectNode) candidate.path("rounds").get(1);
                ((ObjectNode) changed.path("previous")).put("resultSha256", "0".repeat(64));
            } else {
                changed = (ObjectNode) candidate.path("rounds").get(4);
                changed.set("previous", candidate.path("rounds").get(1).path("previous").deepCopy());
            }
            ((ObjectNode) changed.path("identity")).set("previous", changed.path("previous").deepCopy());
            changed.put("identitySha256", Canonical.digest(changed.path("identity")));
            writeBundle(candidate);
            rejectWithoutPublication();
        }
    }

    @Test
    void emptyOrHeldRoundCannotBePromotedToAFalsePublishedZeroIssueResult() throws Exception {
        var candidate = bundleNode();
        var held = (ObjectNode) candidate.path("rounds").get(3);
        held.put("selectionStatus", "EMPTY_CONFIRMED");
        var falseEmpty = JSON.createObjectNode().put("generatedAt", "2026-10-16T01:05:00Z");
        falseEmpty.putArray("items");
        falseEmpty.putObject("verification").put("status", "PASS").putArray("checks");
        falseEmpty.putArray("usage");
        held.set("result", falseEmpty);
        held.put("resultSha256", Canonical.digest(falseEmpty));
        writeBundle(candidate);
        rejectWithoutPublication();
    }

    @Test
    void defaultServingRejectsSimulationWhileLocalManifestAllowsReadAndOriginalNeverChanges() throws Exception {
        importer().importBundle();
        var original = jdbc.queryForList("SELECT published_payload::text FROM briefing_rounds WHERE published_at IS NOT NULL ORDER BY scheduled_at", String.class);
        assertEquals(503, get(defaultPort, QUERY + "morning").status());
        var current = get(localPort, QUERY + "morning");
        assertEquals(200, current.status(), current.body());
        var graph = get(localPort, "/api/v1/briefings/" + current.json().path("id").asText() + "/graph");
        assertEquals(200, graph.status(), graph.body());
        assertEquals("unavailable", graph.json().path("status").asText());
        var duplicate = importer().importBundle();
        assertTrue(duplicate.alreadyImported());
        assertEquals(14, count("briefing_rounds"));
        assertEquals(original, jdbc.queryForList("SELECT published_payload::text FROM briefing_rounds WHERE published_at IS NOT NULL ORDER BY scheduled_at", String.class));
        assertThrows(DataAccessException.class, () -> jdbc.update("UPDATE briefing_rounds SET published_payload='{}' WHERE published_at IS NOT NULL"));
    }

    @Test
    void earlierFailedIncompleteAndUnknownPaidAttemptsStayInAccountingWithoutReplacingSuccess() throws Exception {
        var candidate = withPriorAttempts();
        writeBundle(candidate);
        importer().importBundle();
        assertEquals(3, jdbc.queryForObject("SELECT count(*) FROM briefing_rounds WHERE published_at IS NOT NULL", Integer.class));
        assertEquals(11, jdbc.queryForObject("SELECT count(*) FROM briefing_rounds WHERE published_at IS NULL", Integer.class));
        assertEquals(15, receiptCount());
        var saved = jdbc.query("SELECT storage_uri,sha256,bytes FROM artifacts WHERE kind='ai_call_receipt'", (row, n) ->
                JSON.readTree(ArtifactFileStore.at(artifacts).readVerified(row.getString("storage_uri"), row.getString("sha256"), row.getLong("bytes"))));
        var failed = saved.stream().filter(receipt -> "failed".equals(receipt.path("status").asText())).findFirst().orElseThrow();
        assertEquals(123, failed.path("inputTokens").asLong());
        assertEquals(3, failed.path("outputTokens").asLong());
        var incomplete = saved.stream().filter(receipt -> "incomplete".equals(receipt.path("status").asText())).findFirst().orElseThrow();
        assertEquals(24466, incomplete.path("inputTokens").asLong());
        assertEquals(8000, incomplete.path("outputTokens").asLong());
        var unknown = saved.stream().filter(receipt -> "unknown".equals(receipt.path("status").asText())).findFirst().orElseThrow();
        assertFalse(unknown.path("usageKnown").asBoolean());
        assertTrue(unknown.path("inputTokens").isNull());
        assertTrue(unknown.path("outputTokens").isNull());
        assertTrue(unknown.path("httpStatus").isNull());
        assertEquals(200, get(localPort, QUERY + "morning").status());
    }

    @Test
    void earlierFailedOrUnknownAttemptCannotBeUsedAsTheSuccessfulGenerationReceipt() throws Exception {
        for (String status : List.of("failed", "unknown")) {
            restoreInput();
            var candidate = withPriorAttempts();
            var first = (ObjectNode) candidate.path("rounds").get(0);
            JsonNode prior = null;
            for (var receipt : first.path("receipts")) if (status.equals(receipt.path("status").asText())) prior = receipt;
            assertNotNull(prior);
            ((tools.jackson.databind.node.ArrayNode) first.at("/result/usage")).set(0, prior.deepCopy());
            rebindResultsAndPrevious(candidate);
            writeBundle(candidate);
            var failure = assertThrows(RuntimeException.class, () -> importer().importBundle());
            assertTrue(failure.getMessage().contains("simulation_result_usage_binding"), failure.getMessage());
            assertEquals(0, count("briefing_rounds"));
            assertEquals(0, count("artifacts"));
        }
    }

    @Test
    void anOlderSuccessfulGenerationCannotReplaceTheExplicitFinalGenerationDigest() throws Exception {
        var candidate = withPriorAttempts();
        var first = (ObjectNode) candidate.path("rounds").get(0);
        var olderSuccess = (ObjectNode) first.path("receipts").get(4);
        olderSuccess.put("status", "completed").put("httpStatus", 200);
        for (var receipt : candidate.path("receipts")) {
            if (receipt.path("requestDigest").equals(olderSuccess.path("requestDigest"))) {
                ((ObjectNode) receipt).put("status", "completed").put("httpStatus", 200);
            }
        }
        ((tools.jackson.databind.node.ArrayNode) first.at("/result/usage")).set(0, olderSuccess.deepCopy());
        rebindResultsAndPrevious(candidate);
        writeBundle(candidate);
        var failure = assertThrows(RuntimeException.class, () -> importer().importBundle());
        assertTrue(failure.getMessage().contains("simulation_final_request_binding"), failure.getMessage());
        assertEquals(0, count("briefing_rounds"));
        assertEquals(0, count("artifacts"));
    }

    @Test
    void rawProviderRequestAndResponseArePreservedForHeldValidationAndCannotBeMissingOrChanged() throws Exception {
        var candidate = withHeldProviderRecording();
        writeBundle(candidate);
        importer().importBundle();
        assertEquals(2, jdbc.queryForObject("SELECT count(*) FROM briefing_rounds WHERE published_at IS NOT NULL", Integer.class));
        assertEquals(1, jdbc.queryForObject("SELECT count(*) FROM briefing_rounds WHERE status='failed' AND published_payload IS NULL", Integer.class));
        var saved = jdbc.query("SELECT storage_uri,sha256,bytes FROM artifacts", (row, n) ->
                ArtifactFileStore.at(artifacts).readVerified(row.getString("storage_uri"), row.getString("sha256"), row.getLong("bytes")));
        assertTrue(saved.stream().anyMatch(bytes -> java.util.Arrays.equals(bytes, syntheticRequest())));
        assertTrue(saved.stream().anyMatch(bytes -> java.util.Arrays.equals(bytes, syntheticResponse())));
        var held = get(localPort, "/api/v1/briefings?date=2026-10-03&edition=morning");
        assertEquals("failed", held.json().path("status").asText());
        assertEquals(0, held.json().path("items").size());
        for (String mutation : List.of("missing_response", "wrong_response", "wrong_request")) {
            resetOnlyOwnedSchemaAndSyntheticInputs();
            candidate = withHeldProviderRecording();
            String digest = Canonical.sha256(syntheticRequest());
            Path request = directory.resolve("calls").resolve(digest + ".request.json");
            Path response = directory.resolve("calls").resolve(digest + ".response.json");
            if (mutation.equals("missing_response")) Files.delete(response);
            else Files.writeString(mutation.equals("wrong_response") ? response : request, "[합성시험] 변경된 바이트");
            writeBundle(candidate);
            rejectWithoutPublication();
            assertEquals(0, count("artifacts"), mutation);
        }
    }

    private static byte[] syntheticRequest() {
        return "{\"synthetic\":true,\"kind\":\"held-verification-fixture\"}".getBytes(StandardCharsets.UTF_8);
    }
    private static byte[] syntheticResponse() {
        return "{\"synthetic\":true,\"status\":\"FAIL\",\"message\":\"[합성시험] 원검증 body\"}".getBytes(StandardCharsets.UTF_8);
    }
    private static ObjectNode withHeldProviderRecording() throws Exception {
        var candidate = bundleNode();
        var third = (ObjectNode) candidate.path("rounds").get(2);
        third.put("selectionStatus", "HELD_VALIDATION").putNull("result").putNull("resultSha256");
        third.putArray("selected");
        var receipt = (ObjectNode) third.path("receipts").get(3);
        String oldDigest = receipt.path("requestDigest").asText();
        String digest = Canonical.sha256(syntheticRequest());
        receipt.put("requestDigest", digest).put("responseSha256", Canonical.sha256(syntheticResponse()));
        for (var value : candidate.path("receipts")) {
            if (value.path("requestDigest").asText().equals(oldDigest)) {
                ((ObjectNode) value).put("requestDigest", digest).put("responseSha256", Canonical.sha256(syntheticResponse()));
            }
        }
        Files.createDirectories(directory.resolve("calls"));
        Files.write(directory.resolve("calls").resolve(digest + ".request.json"), syntheticRequest());
        Files.write(directory.resolve("calls").resolve(digest + ".response.json"), syntheticResponse());
        rebindResultsAndPrevious(candidate);
        return candidate;
    }

    private static ObjectNode withPriorAttempts() throws Exception {
        var candidate = bundleNode();
        var first = (ObjectNode) candidate.path("rounds").get(0);
        for (String status : List.of("failed", "incomplete", "unknown")) {
            var prior = ((ObjectNode) first.path("receipts").get(0)).deepCopy();
            prior.put("requestDigest", Canonical.sha256("synthetic-previous-" + status)).put("responseId", "resp_synthetic_prior_" + status)
                    .put("status", status).put("stage", status.equals("incomplete") ? "round_simulation_importance" : "round_simulation_morning_generation");
            if (status.equals("unknown")) prior.put("usageKnown", false).putNull("inputTokens").putNull("outputTokens").putNull("httpStatus").putNull("responseId");
            else prior.put("usageKnown", true).put("inputTokens", status.equals("incomplete") ? 24466 : 123)
                    .put("outputTokens", status.equals("incomplete") ? 8000 : 3).put("httpStatus", status.equals("incomplete") ? 200 : 500);
            ((tools.jackson.databind.node.ArrayNode) first.path("receipts")).add(prior);
            ((tools.jackson.databind.node.ArrayNode) candidate.path("receipts")).add(prior.deepCopy());
        }
        return candidate;
    }

    private static void rebindResultsAndPrevious(ObjectNode candidate) {
        JsonNode previous = null;
        for (var value : candidate.path("rounds")) {
            var round = (ObjectNode) value;
            if (!round.path("result").isNull()) round.put("resultSha256", Canonical.digest(round.path("result")));
            var metadata = JSON.createObjectNode().put("type", "simulated_previous_output");
            if (previous == null) metadata.put("status", "unavailable").put("reason", "[합성시험] 바로 직전 PASS 회차가 없습니다.");
            else metadata.put("status", "available").put("roundId", previous.path("roundId").asText()).put("resultSha256", previous.path("resultSha256").asText());
            round.set("previous", metadata);
            ((ObjectNode) round.path("identity")).set("previous", metadata.deepCopy());
            round.put("identitySha256", Canonical.digest(round.path("identity")));
            previous = !round.path("result").isNull() && !round.path("selected").isEmpty() ? round : null;
        }
    }

    private static BriefingReplayImporter importer() {
        return new BriefingReplayImporter(jdbc, transactionManager,
                new BriefingReplaySettings(source, bundle, artifacts, grants, manifest, sourceSha, INBOX, clocks));
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
        Files.write(clocks, resource("clocks.json"));
        var candidate = (ObjectNode) JSON.readTree(resource("bundle.json"));
        for (var round : candidate.path("rounds")) {
            var identity = (ObjectNode) round.path("identity");
            var promptArtifacts = identity.putObject("promptArtifacts");
            for (String name : List.of("importance.md", "selection.md", "generation-morning.md", "generation-evening.md", "verification.md",
                    "importance.schema.json", "selection.schema.json", "generation.schema.json", "verification.schema.json")) {
                try (var stream = BriefingRoundReplayPostgresTest.class.getResourceAsStream("/briefing/prompts/round-simulation/" + name)) {
                    if (stream == null) throw new IllegalStateException("Missing round simulation prompt resource");
                    promptArtifacts.put(name, ArtifactFileStore.sha256(stream.readAllBytes()));
                }
            }
            ((ObjectNode) round).put("identitySha256", Canonical.digest(identity));
        }
        Files.writeString(bundle, Canonical.write(candidate));
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
        try (var stream = BriefingRoundReplayPostgresTest.class.getResourceAsStream("/briefing-round-replay/" + name)) {
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
